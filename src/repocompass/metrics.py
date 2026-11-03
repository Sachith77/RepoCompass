"""Metrics: pure functions from PR records to newcomer flags, merge rates and bands.

Definitions (docs/BRIEF.md, section "Definitions"):
- usable PR: a complete file list (only human-authored PRs are kept at all);
- newcomer PR: no merged PR by this author was created before this one, over all
  repository history (ADR-0002);
- mature: created at least `maturity_days` before the snapshot and no longer open;
- merge rate: merged / (merged + closed unmerged) over mature newcomer PRs;
- band: the area's 95% Wilson interval compared with the repo rate (ADR-0003);
- stale open: newcomer PRs still open more than `stale_open_days` after creation,
  kept outside the merge rate on purpose.

A PR belongs to the current area holding most of its changed files; ties count for
each tied area. Response times are reported two ways, because each alone misleads:
- the median time to a response, over the newcomer PRs that got one, with how many
  that is. It says how fast answers come, but hides PRs that were never answered;
- the share of mature newcomer PRs with no human response within `no_response_days`.
  It catches an area that answers quickly when it answers, but often does not.
PRs whose response times are unknown (see records.py) are in neither.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from repocompass.config import Settings
from repocompass.records import PrRecord, pr_areas

__all__ = [
    "ABOVE",
    "BELOW",
    "NOT_ENOUGH_DATA",
    "NO_CLEAR_DIFFERENCE",
    "AreaStats",
    "SampleNote",
    "area_stats",
    "band",
    "is_mature",
    "mark_newcomers",
    "repo_rate",
    "sample_note",
    "wilson_interval",
]

ABOVE = "above repo average"
BELOW = "below repo average"
NO_CLEAR_DIFFERENCE = "no clear difference"
NOT_ENOUGH_DATA = "not enough data"
TOP_PEOPLE = 5  # how many contributors and reviewers each area lists


@dataclass(frozen=True)
class AreaStats:
    area: str
    mature_newcomer_prs: int
    merged_prs: int
    merge_rate: float | None
    wilson_low: float | None
    wilson_high: float | None
    band: str
    meets_min_sample: bool
    distinct_newcomer_authors: int
    top_author_pr_share: float | None
    author_concentration_flag: bool
    stale_open_newcomer_prs: int
    median_hours_first_formal_review: float | None
    formal_review_prs: int  # how many PRs that median is over
    median_hours_first_human_response: float | None
    human_response_prs: int
    no_response_share: float | None
    no_response_base_prs: int  # mature newcomer PRs with known response times
    top_contributors: list[dict[str, object]]
    top_reviewers: list[dict[str, object]]


@dataclass(frozen=True)
class SampleNote:
    total_prs: int  # human-authored PRs created in the window
    bot_prs: int  # dropped before sampling
    sampled_prs: int
    per_month: dict[str, dict[str, Any]]
    is_sampled: bool
    covered_from: str | None  # oldest and newest sampled PR creation times
    covered_to: str | None


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def mark_newcomers(records: Iterable[PrRecord], earliest: dict[str, str | None]) -> list[PrRecord]:
    """Set is_newcomer from each author's earliest merged PR (ISO text or None)."""
    out = []
    for record in records:
        first_merged = earliest.get(record.author)
        newcomer = first_merged is None or record.created_at <= _parse(first_merged)
        out.append(replace(record, is_newcomer=newcomer))
    return out


def is_mature(record: PrRecord, snapshot: datetime, settings: Settings) -> bool:
    old_enough = record.created_at <= snapshot - timedelta(days=settings.maturity_days)
    return old_enough and record.state != "OPEN"


def _mature_newcomers(
    records: Iterable[PrRecord], snapshot: datetime, settings: Settings
) -> list[PrRecord]:
    return [
        r
        for r in records
        if r.files_complete and r.is_newcomer and is_mature(r, snapshot, settings)
    ]


def repo_rate(
    records: Iterable[PrRecord], snapshot: datetime, settings: Settings
) -> tuple[float | None, int]:
    """The repo-wide mature newcomer merge rate and how many PRs it is based on.

    Every mature newcomer PR counts here, including PRs that changed no current area
    (only root files, or only directories that have since been deleted).
    """
    mature = _mature_newcomers(records, snapshot, settings)
    if not mature:
        return None, 0
    return sum(r.merged for r in mature) / len(mature), len(mature)


def wilson_interval(successes: int, n: int, z: float) -> tuple[float, float] | None:
    """The Wilson score interval for a proportion; None when there is nothing to measure."""
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half_width = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def band(interval: tuple[float, float] | None, rate: float | None, meets_min_sample: bool) -> str:
    """Entirely above, entirely below, or overlapping the repo rate. Touching overlaps."""
    if interval is None or rate is None or not meets_min_sample:
        return NOT_ENOUGH_DATA
    low, high = interval
    if low > rate:
        return ABOVE
    if high < rate:
        return BELOW
    return NO_CLEAR_DIFFERENCE


def _median_hours(records: Iterable[PrRecord], field: str) -> tuple[float | None, int]:
    hours = [
        (getattr(r, field) - r.created_at).total_seconds() / 3600
        for r in records
        if r.response_times_complete and getattr(r, field) is not None
    ]
    return (median(hours) if hours else None), len(hours)


def _no_response(mature: list[PrRecord], days: int) -> tuple[float | None, int]:
    known = [r for r in mature if r.response_times_complete]
    if not known:
        return None, 0
    limit = timedelta(days=days)
    silent = sum(
        1
        for r in known
        if r.first_human_response_at is None or r.first_human_response_at - r.created_at > limit
    )
    return silent / len(known), len(known)


def _top(counts: Counter[str]) -> list[dict[str, object]]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:TOP_PEOPLE]
    return [{"login": login, "count": n} for login, n in ranked]


def _one_area(
    area: str,
    prs: list[PrRecord],
    snapshot: datetime,
    settings: Settings,
    rate: float | None,
) -> AreaStats:
    newcomers = [r for r in prs if r.is_newcomer]
    mature = _mature_newcomers(newcomers, snapshot, settings)
    n = len(mature)
    merged = sum(r.merged for r in mature)
    interval = wilson_interval(merged, n, settings.wilson_z)
    meets = n >= settings.min_sample
    authors = Counter(r.author for r in mature)
    top_share = max(authors.values()) / n if n else None
    stale_before = snapshot - timedelta(days=settings.stale_open_days)
    review_median, review_n = _median_hours(newcomers, "first_formal_review_at")
    response_median, response_n = _median_hours(newcomers, "first_human_response_at")
    silent_share, silent_base = _no_response(mature, settings.no_response_days)
    return AreaStats(
        area=area,
        mature_newcomer_prs=n,
        merged_prs=merged,
        merge_rate=merged / n if n else None,
        wilson_low=interval[0] if interval else None,
        wilson_high=interval[1] if interval else None,
        band=band(interval, rate, meets),
        meets_min_sample=meets,
        distinct_newcomer_authors=len(authors),
        top_author_pr_share=top_share,
        author_concentration_flag=(
            top_share is not None and top_share > settings.author_concentration_threshold
        ),
        stale_open_newcomer_prs=sum(
            1 for r in newcomers if r.state == "OPEN" and r.created_at < stale_before
        ),
        median_hours_first_formal_review=review_median,
        formal_review_prs=review_n,
        median_hours_first_human_response=response_median,
        human_response_prs=response_n,
        no_response_share=silent_share,
        no_response_base_prs=silent_base,
        top_contributors=_top(Counter(r.author for r in prs if r.merged)),
        top_reviewers=_top(Counter(login for r in prs for login in r.reviewers)),
    )


def area_stats(
    records: Iterable[PrRecord],
    areas: Iterable[str],
    snapshot: datetime,
    settings: Settings,
    rate: float | None,
) -> list[AreaStats]:
    """One row per area, including areas with no PRs at all."""
    by_area: defaultdict[str, list[PrRecord]] = defaultdict(list)
    for record in records:
        if record.files_complete:
            for area in pr_areas(record.area_files):
                by_area[area].append(record)
    return [_one_area(a, by_area.get(a, []), snapshot, settings, rate) for a in sorted(areas)]


def sample_note(fetch_state: dict[str, Any]) -> SampleNote:
    """What the PR sample covers: totals, per-month counts and dates, and any capping."""
    totals = fetch_state["month_totals"]
    months = sorted(set(totals) | set(fetch_state["month_bots"]))
    per_month = {
        m: {
            "total": totals.get(m, 0),
            "bots": fetch_state["month_bots"].get(m, 0),
            "sampled": fetch_state["month_sampled"].get(m, 0),
            "first": fetch_state["month_first"].get(m),
            "last": fetch_state["month_last"].get(m),
        }
        for m in months
    }
    firsts = [v["first"] for v in per_month.values() if v["first"]]
    lasts = [v["last"] for v in per_month.values() if v["last"]]
    return SampleNote(
        total_prs=sum(totals.values()),
        bot_prs=sum(fetch_state["month_bots"].values()),
        sampled_prs=sum(fetch_state["month_sampled"].values()),
        per_month=per_month,
        is_sampled=any(v["sampled"] < v["total"] for v in per_month.values()),
        covered_from=min(firsts, key=_parse) if firsts else None,
        covered_to=max(lasts, key=_parse) if lasts else None,
    )
