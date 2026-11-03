"""Command line entry point.

Usage:
    python -m repocompass init-db               apply the schema
    python -m repocompass check                 report configuration without printing secrets
    python -m repocompass analyze OWNER/REPO    run a full analysis as a new job and store it
    python -m repocompass resume JOB_ID         continue a failed or interrupted job
    python -m repocompass ingest-git OWNER/REPO developer command: print the git stage only
"""

from __future__ import annotations

import contextlib
import sys
from collections import Counter
from collections.abc import Callable

from repocompass.analysis import AnalysisResult, run_analysis, save_analysis
from repocompass.config import ConfigError, Settings, load_settings
from repocompass.db import DatabaseError, apply_schema, schema_table_names
from repocompass.gitclone import GitError
from repocompass.github import GitHubClient, GitHubError, parse_repo_slug
from repocompass.ingest_git import GitIngestResult, git_stage
from repocompass.jobs import create_job, finish_job, load_job, save_job_checkpoint
from repocompass.metrics import NOT_ENOUGH_DATA

# Failures an analysis reports as a message; their text never holds a secret.
EXPECTED_ERRORS = (GitHubError, GitError, DatabaseError, LookupError)


def _load() -> Settings:
    try:
        return load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def cmd_check(args: list[str]) -> int:
    """Confirm configuration resolves. Prints no secret values."""
    settings = _load()
    print("configuration loaded")
    print(f"  window_days                     {settings.window_days}")
    print(f"  maturity_days                   {settings.maturity_days}")
    print(f"  monthly_sample_cap              {settings.monthly_sample_cap}")
    print(f"  min_sample                      {settings.min_sample}")
    print(f"  stale_open_days                 {settings.stale_open_days}")
    print(f"  no_response_days                {settings.no_response_days}")
    print(f"  author_concentration_threshold  {settings.author_concentration_threshold}")
    print(f"  activity_recent_days            {settings.activity_recent_days}")
    print(f"  sweep_area_share                {settings.sweep_area_share}")
    print(f"  sweep_min_areas                 {settings.sweep_min_areas}")
    print(f"  excluded_dirs                   {', '.join(settings.excluded_dirs)}")
    print(f"  clone_dir                       {settings.clone_dir}")
    print(f"  schema tables                   {', '.join(schema_table_names())}")
    return 0


def cmd_init_db(args: list[str]) -> int:
    settings = _load()
    try:
        tables = apply_schema(settings.database_url)
    except DatabaseError as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 1
    print(f"schema applied; tables present: {', '.join(tables)}")
    return 0


def cmd_ingest_git(args: list[str]) -> int:
    if len(args) != 1:
        print("usage: python -m repocompass ingest-git OWNER/REPO", file=sys.stderr)
        return 2
    settings = _load()
    try:
        with GitHubClient(settings.github_token) as client:
            result = git_stage(settings, client, args[0])
    except (GitHubError, GitError) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1
    _print_git(result)
    print("(developer command: nothing was stored; use analyze to store a full analysis)")
    return 0


def _print_git(result: GitIngestResult) -> None:
    a = result.activity
    bands = Counter(r.band for r in a.areas)
    repo = result.repo
    print(f"repository        {repo.canonical_slug} (requested {repo.requested_slug})")
    print(f"snapshot          {result.snapshot.isoformat(timespec='seconds')}")
    print(f"files considered  {result.files_considered}")
    print(f"area depths       {result.depths or 'one level everywhere'}")
    band_text = ", ".join(f"{b} {bands[b]}" for b in ("active", "steady", "dormant"))
    print(f"areas             {len(a.areas)}  ({band_text})")
    print(
        f"commits           {a.commits_in_window} in window; {a.bot_commits} bot, "
        f"{a.sweep_commits} sweep, {a.counted_commits} counted toward an area"
    )
    print("seconds           " + ", ".join(f"{k} {v:.1f}" for k, v in result.seconds.items()))


def _rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _hours(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _share(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _print_analysis(result: AnalysisResult, settings: Settings) -> None:
    _print_git(result.git)
    note = result.note
    sampled = "sampled (at least one month capped)" if note.is_sampled else "complete"
    print(
        f"PRs in window     {note.total_prs} human "
        f"({note.bot_prs} bot or non-user PRs dropped first); kept {note.sampled_prs}; {sampled}"
    )
    print(f"dates covered     {note.covered_from} to {note.covered_to}")
    unknown = sum(1 for r in result.records if not r.response_times_complete)
    print(f"response times    unknown for {unknown} PRs (no human answer in the fetched slice)")
    incomplete = sum(1 for r in result.records if not r.files_complete)
    print(f"file lists        {incomplete} PRs could not be fetched in full and are excluded")
    print(
        f"repo rate         {_rate(result.repo_rate)} over "
        f"{result.repo_mature_newcomer_prs} mature newcomer PRs"
    )
    bands = Counter(s.band for s in result.stats)
    print("bands             " + ", ".join(f"{b} {n}" for b, n in sorted(bands.items())))
    for s in result.stats:
        if s.band == NOT_ENOUGH_DATA:
            continue
        limit = f"{settings.author_concentration_threshold:.0%}"
        flag = f"; one author >{limit}" if s.author_concentration_flag else ""
        print(
            f"  {s.area:<40} n={s.mature_newcomer_prs:<4} rate {_rate(s.merge_rate)} "
            f"[{_rate(s.wilson_low)}, {_rate(s.wilson_high)}]  {s.band}; "
            f"{s.distinct_newcomer_authors} authors, {s.stale_open_newcomer_prs} stale open{flag}"
        )
        print(
            f"  {'':<40} median hours to review {_hours(s.median_hours_first_formal_review)} "
            f"(n={s.formal_review_prs}), to human response "
            f"{_hours(s.median_hours_first_human_response)} (n={s.human_response_prs}); "
            f"no response in {settings.no_response_days} days {_share(s.no_response_share)} "
            f"(n={s.no_response_base_prs})"
        )
    usage = result.usage
    seconds = ", ".join(f"{k} {v:.1f}" for k, v in usage["seconds"].items())
    print(f"stage seconds     {seconds}")
    print(f"API               {usage['requests']} requests, {usage['points']} points")


def _run_job(settings: Settings, job_id: int, slug: str, checkpoint: dict) -> int:
    def save(stage: str, progress: int, state: dict) -> None:
        save_job_checkpoint(settings.database_url, job_id, stage, progress, state)

    try:
        with GitHubClient(settings.github_token) as client:
            result = run_analysis(
                settings, slug, client, checkpoint=checkpoint, save_checkpoint=save
            )
        repo_id = save_analysis(settings, result)
    except EXPECTED_ERRORS as exc:
        _fail(settings, job_id, str(exc))
        print(f"job {job_id} failed: {exc}", file=sys.stderr)
        print(f"resume with: python -m repocompass resume {job_id}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        _fail(settings, job_id, "interrupted")
        print(f"job {job_id} interrupted; resume with: python -m repocompass resume {job_id}")
        return 130
    except Exception as exc:  # an unexpected bug: record only its type, never its text
        _fail(settings, job_id, f"unexpected {type(exc).__name__}")
        raise
    finish_job(settings.database_url, job_id, repo_id=repo_id)
    print(f"job {job_id} done")
    _print_analysis(result, settings)
    return 0


def _fail(settings: Settings, job_id: int, error: str) -> None:
    # if the database is down too, the original failure is still what gets reported
    with contextlib.suppress(DatabaseError):
        finish_job(settings.database_url, job_id, error=error)


def cmd_analyze(args: list[str]) -> int:
    if len(args) != 1:
        print("usage: python -m repocompass analyze OWNER/REPO", file=sys.stderr)
        return 2
    settings = _load()
    try:
        parse_repo_slug(args[0])
        job_id = create_job(settings.database_url, args[0].strip())
    except (GitHubError, DatabaseError) as exc:
        print(f"analysis not started: {exc}", file=sys.stderr)
        return 1
    print(f"job {job_id} started for {args[0].strip()}")
    return _run_job(settings, job_id, args[0], {})


def cmd_resume(args: list[str]) -> int:
    if len(args) != 1 or not args[0].isdigit():
        print("usage: python -m repocompass resume JOB_ID", file=sys.stderr)
        return 2
    settings = _load()
    job_id = int(args[0])
    try:
        slug, checkpoint = load_job(settings.database_url, job_id)
    except (DatabaseError, LookupError) as exc:
        print(f"cannot resume: {exc}", file=sys.stderr)
        return 1
    print(f"job {job_id} resumed for {slug}")
    return _run_job(settings, job_id, slug, checkpoint)


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "check": cmd_check,
    "init-db": cmd_init_db,
    "analyze": cmd_analyze,
    "resume": cmd_resume,
    "ingest-git": cmd_ingest_git,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print(f"usage: python -m repocompass {{{'|'.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    return COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
