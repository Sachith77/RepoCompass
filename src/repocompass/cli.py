"""Command line entry point.

Usage:
    python -m repocompass init-db               apply the schema
    python -m repocompass check                 report configuration without printing secrets
    python -m repocompass ingest-git OWNER/REPO clone, fit areas, store commit activity
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable

from repocompass.config import ConfigError, Settings, load_settings
from repocompass.db import DatabaseError, apply_schema, schema_table_names
from repocompass.gitclone import GitError
from repocompass.github import GitHubError
from repocompass.ingest_git import ingest_git


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
        result = ingest_git(settings, args[0])
    except (GitHubError, GitError, DatabaseError) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1

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
    return 0


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "check": cmd_check,
    "init-db": cmd_init_db,
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
