"""Commit-based area activity, as pure functions over parsed commits.

Which commits count:
- merge commits never reach this module (git log runs with --no-merges);
- bot commits are dropped, using the same bot rule as PR authors;
- sweep commits are dropped: a commit touching more than `sweep_area_share` of all
  areas and at least `sweep_min_areas` areas is formatting, licence headers or a
  mass rename, not work in an area.

A counted commit adds one to every area it touches, however many files it changes
there. The band uses only the brief's two windows, so it introduces no new numbers:
active = a commit in the last 90 days, steady = commits in the last 12 months but none
in 90 days, dormant = none in 12 months.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from repocompass.areas import area_of, drop_excluded
from repocompass.config import Settings

__all__ = [
    "ActivitySummary",
    "AreaActivity",
    "Commit",
    "activity_band",
    "is_bot_commit",
    "is_sweep",
    "summarise_activity",
]

NOREPLY_DOMAIN = "@users.noreply.github.com"


@dataclass(frozen=True)
class Commit:
    sha: str
    committed_at: datetime
    author_name: str
    author_email: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class AreaActivity:
    area: str
    commits_recent: int
    commits_window: int
    authors_window: int
    band: str


@dataclass(frozen=True)
class ActivitySummary:
    areas: tuple[AreaActivity, ...]
    commits_in_window: int
    bot_commits: int
    sweep_commits: int
    counted_commits: int


def is_bot_commit(name: str, email: str, settings: Settings) -> bool:
    """Bot rule applied to a commit author's name and email.

    GitHub's noreply addresses look like `49699333+dependabot[bot]@users.noreply...`,
    so the part after '+' is the login and gets the same check as a PR author.
    An empty name alone does not make a bot: a real email is still a person. With
    neither name nor email the author is unknown and excluded, like a deleted PR author.
    """
    if not name and not email:
        return True
    if name and settings.is_bot_login(name):
        return True
    local = email.split("@", 1)[0]
    if email.lower().endswith(NOREPLY_DOMAIN) and "+" in local:
        local = local.split("+", 1)[1]
    return bool(local) and settings.is_bot_login(local)


def is_sweep(areas_touched: int, total_areas: int, share: float, min_areas: int) -> bool:
    """More than `share` of all areas AND at least `min_areas` of them.

    Config keeps `min_areas` at 2 or more, so a commit touching one area is never a
    sweep, even in a one-area repository.
    """
    return areas_touched >= min_areas and areas_touched > share * total_areas


def activity_band(commits_recent: int, commits_window: int) -> str:
    if commits_recent > 0:
        return "active"
    if commits_window > 0:
        return "steady"
    return "dormant"


def _author_key(commit: Commit) -> str:
    """Identify an author by email, falling back to name. Never stored, only counted."""
    return (commit.author_email or commit.author_name).strip().lower()


def summarise_activity(
    commits: Iterable[Commit],
    areas: Iterable[str],
    depths: dict[str, int],
    settings: Settings,
    snapshot: datetime,
) -> ActivitySummary:
    """Per-area commit counts and bands for the window ending at `snapshot`."""
    area_set = set(areas)
    window_start = snapshot - timedelta(days=settings.window_days)
    recent_start = snapshot - timedelta(days=settings.activity_recent_days)

    recent: Counter[str] = Counter()
    window: Counter[str] = Counter()
    authors: defaultdict[str, set[str]] = defaultdict(set)
    in_window = bots = sweeps = counted = 0

    for commit in commits:
        if not window_start <= commit.committed_at <= snapshot:
            continue
        in_window += 1
        if is_bot_commit(commit.author_name, commit.author_email, settings):
            bots += 1
            continue
        touched = {
            area
            for path in drop_excluded(commit.paths, settings.excluded_dirs)
            if (area := area_of(path, depths)) in area_set
        }
        if is_sweep(
            len(touched), len(area_set), settings.sweep_area_share, settings.sweep_min_areas
        ):
            sweeps += 1
            continue
        if touched:
            counted += 1
        for area in touched:
            window[area] += 1
            authors[area].add(_author_key(commit))
            if commit.committed_at >= recent_start:
                recent[area] += 1

    rows = tuple(
        AreaActivity(
            area=area,
            commits_recent=recent[area],
            commits_window=window[area],
            authors_window=len(authors[area]),
            band=activity_band(recent[area], window[area]),
        )
        for area in sorted(area_set)
    )
    return ActivitySummary(
        areas=rows,
        commits_in_window=in_window,
        bot_commits=bots,
        sweep_commits=sweeps,
        counted_commits=counted,
    )
