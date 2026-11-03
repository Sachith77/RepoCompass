"""Pipeline stage 2: areas and activity from the clone only.

Resolve the canonical name, clone or fetch, fit the area rule to the current tree,
read twelve months of commits, and store one area_stats row per area. Apart from
the single name lookup there are no API calls, so this is the first result a
report can show.

v0 re-analyses in full (ADR-0007): a run replaces the repository's area rows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg.types.json import Jsonb

from repocompass.activity import ActivitySummary, summarise_activity
from repocompass.areas import area_names, drop_excluded, fit_area_depths
from repocompass.config import Settings
from repocompass.db import connect
from repocompass.gitclone import clone_or_update, clone_path, list_files, read_commits
from repocompass.github import RepoInfo, parse_repo_slug, resolve_repository

__all__ = ["GitIngestResult", "ingest_git"]


@dataclass(frozen=True)
class GitIngestResult:
    repo: RepoInfo
    snapshot: datetime
    files_considered: int
    depths: dict[str, int]
    activity: ActivitySummary
    seconds: dict[str, float]


UPSERT_REPO = """
INSERT INTO repos (requested_slug, canonical_slug, default_branch, snapshot_at,
                   window_start, window_end, area_depths, excluded_dirs,
                   sweep_commits_excluded)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (canonical_slug) DO UPDATE SET
    requested_slug = EXCLUDED.requested_slug,
    default_branch = EXCLUDED.default_branch,
    snapshot_at = EXCLUDED.snapshot_at,
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    area_depths = EXCLUDED.area_depths,
    excluded_dirs = EXCLUDED.excluded_dirs,
    sweep_commits_excluded = EXCLUDED.sweep_commits_excluded,
    updated_at = now()
RETURNING id
"""

INSERT_AREA = """
INSERT INTO area_stats (repo_id, area, commits_90d, commits_12mo, commit_authors_12mo,
                        activity_band)
VALUES (%s, %s, %s, %s, %s, %s)
"""


def _save(settings: Settings, result: GitIngestResult) -> None:
    rule = {
        "threshold_share": settings.area_threshold_share,
        "max_depth": settings.area_max_depth,
        "depths": result.depths,
    }
    window_start = result.snapshot - timedelta(days=settings.window_days)
    with connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            UPSERT_REPO,
            (
                result.repo.requested_slug,
                result.repo.canonical_slug,
                result.repo.default_branch,
                result.snapshot,
                window_start,
                result.snapshot,
                Jsonb(rule),
                Jsonb(list(settings.excluded_dirs)),
                result.activity.sweep_commits,
            ),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING always yields a row
            raise RuntimeError("repos upsert returned no id")
        repo_id = row[0]
        cur.execute("DELETE FROM area_stats WHERE repo_id = %s", (repo_id,))
        cur.executemany(
            INSERT_AREA,
            [
                (repo_id, a.area, a.commits_recent, a.commits_window, a.authors_window, a.band)
                for a in result.activity.areas
            ],
        )


def ingest_git(settings: Settings, repo_text: str, *, save: bool = True) -> GitIngestResult:
    """Run stage 2 for one repository and, unless `save` is False, store the result."""
    seconds: dict[str, float] = {}
    owner, name = parse_repo_slug(repo_text)

    start = time.perf_counter()
    repo = resolve_repository(settings.github_token, owner, name)
    seconds["resolve"] = time.perf_counter() - start

    dest = clone_path(Path(settings.clone_dir), repo.canonical_slug)
    start = time.perf_counter()
    clone_or_update(f"https://github.com/{repo.canonical_slug}.git", dest)
    seconds["clone_or_fetch"] = time.perf_counter() - start

    snapshot = datetime.now(UTC)
    rev = f"origin/{repo.default_branch}"

    start = time.perf_counter()
    files = drop_excluded(list_files(dest, rev), settings.excluded_dirs)
    depths = fit_area_depths(files, settings.area_threshold_share, settings.area_max_depth)
    areas = area_names(files, depths)
    seconds["tree_and_areas"] = time.perf_counter() - start

    start = time.perf_counter()
    commits = read_commits(dest, rev, snapshot - timedelta(days=settings.window_days))
    seconds["git_log"] = time.perf_counter() - start

    activity = summarise_activity(commits, areas, depths, settings, snapshot)
    result = GitIngestResult(
        repo=repo,
        snapshot=snapshot,
        files_considered=len(files),
        depths=depths,
        activity=activity,
        seconds=seconds,
    )
    if save:
        _save(settings, result)
    return result
