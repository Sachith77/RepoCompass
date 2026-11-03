"""One analysis: git stage, then PR stage, then one transaction that replaces the rows.

ADR-0008: an analysis is always a full rebuild. Everything fetched so far lives in
the job checkpoint, saved after the git stage, after every PR page and after every
lookback request, so an interrupted run resumes instead of restarting. Only when
every stage is done does `save_analysis` replace all of the repository's rows in a
single transaction, so a reader never sees half of one snapshot and half of another.

The checkpoint also carries running totals of requests, points and seconds, so the
numbers for a job that was interrupted and resumed cover the whole job.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from repocompass.config import Settings
from repocompass.db import connect
from repocompass.github import GitHubClient
from repocompass.ingest_git import GitIngestResult, git_from_json, git_stage, git_to_json
from repocompass.lookback import lookback_earliest_merged
from repocompass.metrics import (
    AreaStats,
    SampleNote,
    area_stats,
    mark_newcomers,
    repo_rate,
    sample_note,
)
from repocompass.prs import fetch_prs
from repocompass.records import PrRecord, pr_areas, record_from_json

__all__ = ["AnalysisResult", "SaveCheckpoint", "run_analysis", "save_analysis"]

# (stage, progress 0-100, checkpoint) -> None
SaveCheckpoint = Callable[[str, int, dict[str, Any]], None]


@dataclass(frozen=True)
class AnalysisResult:
    git: GitIngestResult
    records: list[PrRecord]
    stats: list[AreaStats]
    note: SampleNote
    repo_rate: float | None
    repo_mature_newcomer_prs: int
    usage: dict[str, Any]  # {"requests", "points", "seconds": {stage: s}} for the whole job


class _Usage:
    """Requests, points and seconds per stage, added to what earlier runs recorded."""

    def __init__(self, saved: dict[str, Any] | None, client: GitHubClient) -> None:
        self._base = saved or {"requests": 0, "points": 0, "seconds": {}}
        self._client = client
        self._seconds: dict[str, float] = dict(self._base["seconds"])
        self._stage: str | None = None
        self._started = 0.0

    def start(self, stage: str) -> None:
        self._stage, self._started = stage, time.perf_counter()

    def stop(self) -> None:
        if self._stage is not None:
            elapsed = time.perf_counter() - self._started
            self._seconds[self._stage] = self._seconds.get(self._stage, 0.0) + elapsed
            self._stage = None

    def total(self) -> dict[str, Any]:
        seconds = dict(self._seconds)
        if self._stage is not None:  # include the stage still running
            elapsed = time.perf_counter() - self._started
            seconds[self._stage] = seconds.get(self._stage, 0.0) + elapsed
        return {
            "requests": self._base["requests"] + self._client.requests,
            "points": self._base["points"] + self._client.points,
            "seconds": seconds,
        }


def _page_progress(prs: dict[str, Any], snapshot: datetime, window_days: int) -> int:
    """10-80%: how far back in the window the PR pages have reached."""
    if prs["done"]:
        return 80
    if not prs["records"]:
        return 10
    oldest = datetime.fromisoformat(prs["records"][-1]["created_at"])
    covered = (snapshot - oldest) / timedelta(days=window_days)
    return 10 + int(70 * min(covered, 1.0))


def run_analysis(
    settings: Settings,
    repo_text: str,
    client: GitHubClient,
    *,
    checkpoint: dict[str, Any] | None,
    save_checkpoint: SaveCheckpoint,
) -> AnalysisResult:
    """Run every stage, resuming from `checkpoint`. Writes nothing but checkpoints."""
    state: dict[str, Any] = dict(checkpoint or {})
    usage = _Usage(state.get("usage"), client)

    def save(stage: str, progress: int) -> None:
        state["usage"] = usage.total()
        save_checkpoint(stage, progress, state)

    if "git" in state:
        git = git_from_json(state["git"])
    else:
        usage.start("git_stage")
        git = git_stage(settings, client, repo_text)
        usage.stop()
        state["git"] = git_to_json(git)
        save("prs", 10)

    snapshot = git.snapshot
    canonical = git.repo.canonical_slug
    owner, name = canonical.split("/")

    def page_saved(prs: dict[str, Any]) -> None:
        state["prs"] = prs
        save("prs", _page_progress(prs, snapshot, settings.window_days))

    usage.start("pr_pages")
    prs = fetch_prs(
        client,
        owner,
        name,
        settings=settings,
        window_start=snapshot - timedelta(days=settings.window_days),
        snapshot=snapshot,
        depths=git.depths,
        areas={a.area for a in git.activity.areas},
        state=state.get("prs"),
        save=page_saved,
    )
    usage.stop()
    records = [record_from_json(r) for r in prs["records"]]
    logins = sorted({r.author for r in records})

    def batch_saved(earliest: dict[str, str | None]) -> None:
        state["earliest"] = earliest
        save("lookback", min(95, 80 + int(15 * len(earliest) / max(len(logins), 1))))

    usage.start("lookback")
    earliest = lookback_earliest_merged(
        client, canonical, logins, dict(state.get("earliest") or {}), save=batch_saved
    )
    usage.stop()

    records = mark_newcomers(records, earliest)
    rate, rate_n = repo_rate(records, snapshot, settings)
    return AnalysisResult(
        git=git,
        records=records,
        stats=area_stats(records, [a.area for a in git.activity.areas], snapshot, settings, rate),
        note=sample_note(prs),
        repo_rate=rate,
        repo_mature_newcomer_prs=rate_n,
        usage=usage.total(),
    )


def _insert(table: str, columns: tuple[str, ...]) -> str:
    placeholders = ", ".join(["%s"] * len(columns))
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


REPO_COLUMNS = (
    "requested_slug", "canonical_slug", "default_branch", "snapshot_at", "window_start",
    "window_end", "area_depths", "excluded_dirs", "sweep_commits_excluded",
    "total_prs_in_window", "bot_prs_in_window", "sampled_prs", "prs_per_month", "is_sampled",
    "sample_first_created", "sample_last_created", "repo_merge_rate", "repo_mature_newcomer_prs",
)  # fmt: skip
UPSERT_REPO = (
    _insert("repos", REPO_COLUMNS)
    + " ON CONFLICT (canonical_slug) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in REPO_COLUMNS if c != "canonical_slug")
    + ", updated_at = now() RETURNING id"
)

# (column, PrRecord attribute)
PR_COLUMNS = (
    ("number", "number"), ("author_login", "author"), ("author_association", "association"),
    ("created_at", "created_at"), ("merged_at", "merged_at"), ("closed_at", "closed_at"),
    ("state", "state"), ("is_merged", "merged"), ("changed_files", "changed_files"),
    ("files_complete", "files_complete"), ("is_newcomer", "is_newcomer"),
    ("first_formal_review_at", "first_formal_review_at"),
    ("first_human_response_at", "first_human_response_at"),
    ("response_times_complete", "response_times_complete"),
)  # fmt: skip
INSERT_PR = _insert("prs", ("repo_id", *(column for column, _ in PR_COLUMNS)))

INSERT_PR_AREA = _insert("pr_areas", ("repo_id", "pr_number", "area", "file_count"))

# AreaStats fields are named after their area_stats columns; activity comes from git.
STATS_COLUMNS = tuple(f.name for f in fields(AreaStats))
ACTIVITY_COLUMNS = ("commits_90d", "commits_12mo", "commit_authors_12mo", "activity_band")
INSERT_AREA = _insert("area_stats", ("repo_id", *STATS_COLUMNS, *ACTIVITY_COLUMNS))


def _jsonb(value: Any) -> Any:
    return Jsonb(value) if isinstance(value, (dict, list)) else value


def save_analysis(settings: Settings, result: AnalysisResult) -> int:
    """Replace all of the repository's rows in one transaction. Returns the repo id."""
    git, note = result.git, result.note
    rule = {
        "threshold_share": settings.area_threshold_share,
        "max_depth": settings.area_max_depth,
        "depths": git.depths,
    }
    repo_values = (
        git.repo.requested_slug, git.repo.canonical_slug, git.repo.default_branch,
        git.snapshot, git.snapshot - timedelta(days=settings.window_days), git.snapshot,
        Jsonb(rule), Jsonb(list(settings.excluded_dirs)), git.activity.sweep_commits,
        note.total_prs, note.bot_prs, note.sampled_prs, Jsonb(note.per_month), note.is_sampled,
        note.covered_from, note.covered_to, result.repo_rate, result.repo_mature_newcomer_prs,
    )  # fmt: skip
    activity = {a.area: a for a in git.activity.areas}
    with connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(UPSERT_REPO, repo_values)
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING always yields a row
            raise RuntimeError("repos upsert returned no id")
        repo_id = int(row[0])
        # pr_areas rows go with their PRs (ON DELETE CASCADE)
        cur.execute("DELETE FROM prs WHERE repo_id = %s", (repo_id,))
        cur.execute("DELETE FROM area_stats WHERE repo_id = %s", (repo_id,))
        cur.executemany(
            INSERT_PR,
            [(repo_id, *(getattr(r, a) for _, a in PR_COLUMNS)) for r in result.records],
        )
        cur.executemany(
            INSERT_PR_AREA,
            [
                (repo_id, r.number, area, r.area_files[area])
                for r in result.records
                for area in pr_areas(r.area_files)
            ],
        )
        rows = []
        for s in result.stats:
            a = activity[s.area]
            stats = (_jsonb(getattr(s, c)) for c in STATS_COLUMNS)
            rows.append(
                (repo_id, *stats, a.commits_recent, a.commits_window, a.authors_window, a.band)
            )
        cur.executemany(INSERT_AREA, rows)
    return repo_id
