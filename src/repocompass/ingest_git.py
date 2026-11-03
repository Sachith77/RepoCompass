"""Pipeline stage 2: areas and activity from the clone only.

Resolve the canonical name, clone or fetch, fit the area rule to the current tree,
read twelve months of commits, and summarise activity per area. Apart from the
single name lookup there are no API calls.

This stage writes nothing to the database. An analysis stores the git stage and the
PR stage together, in one transaction (ADR-0008); the `ingest-git` command only
prints this stage's result, for development.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from repocompass.activity import ActivitySummary, AreaActivity, summarise_activity
from repocompass.areas import area_names, drop_excluded, fit_area_depths
from repocompass.config import Settings
from repocompass.gitclone import clone_or_update, clone_path, list_files, read_commits
from repocompass.github import GitHubClient, RepoInfo, parse_repo_slug, resolve_repository

__all__ = ["GitIngestResult", "git_from_json", "git_stage", "git_to_json"]


@dataclass(frozen=True)
class GitIngestResult:
    repo: RepoInfo
    snapshot: datetime
    files_considered: int
    depths: dict[str, int]
    activity: ActivitySummary
    seconds: dict[str, float]


def git_stage(settings: Settings, client: GitHubClient, repo_text: str) -> GitIngestResult:
    """Run stage 2 for one repository. The snapshot time is taken here."""
    seconds: dict[str, float] = {}
    owner, name = parse_repo_slug(repo_text)

    start = time.perf_counter()
    repo = resolve_repository(client, owner, name)
    seconds["resolve"] = time.perf_counter() - start

    dest = clone_path(Path(settings.clone_dir), repo.canonical_slug)
    start = time.perf_counter()
    clone_or_update(f"https://github.com/{repo.canonical_slug}.git", dest)
    seconds["clone_or_fetch"] = time.perf_counter() - start

    snapshot = datetime.now(UTC).replace(microsecond=0)
    rev = f"origin/{repo.default_branch}"

    start = time.perf_counter()
    files = drop_excluded(list_files(dest, rev), settings.excluded_dirs)
    depths = fit_area_depths(files, settings.area_threshold_share, settings.area_max_depth)
    areas = area_names(files, depths)
    seconds["tree_and_areas"] = time.perf_counter() - start

    start = time.perf_counter()
    commits = read_commits(dest, rev, snapshot - timedelta(days=settings.window_days))
    seconds["git_log"] = time.perf_counter() - start

    return GitIngestResult(
        repo=repo,
        snapshot=snapshot,
        files_considered=len(files),
        depths=depths,
        activity=summarise_activity(commits, areas, depths, settings, snapshot),
        seconds=seconds,
    )


def git_to_json(result: GitIngestResult) -> dict[str, Any]:
    """The stage result as plain JSON, for the job checkpoint."""
    out = asdict(result)
    out["snapshot"] = result.snapshot.isoformat()
    return out


def git_from_json(data: dict[str, Any]) -> GitIngestResult:
    activity = dict(data["activity"])
    activity["areas"] = tuple(AreaActivity(**a) for a in activity["areas"])
    return GitIngestResult(
        repo=RepoInfo(**data["repo"]),
        snapshot=datetime.fromisoformat(data["snapshot"]),
        files_considered=data["files_considered"],
        depths=dict(data["depths"]),
        activity=ActivitySummary(**activity),
        seconds=dict(data["seconds"]),
    )
