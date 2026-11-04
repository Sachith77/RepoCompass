"""Cutoff validation (docs/BRIEF.md, "Evaluation"): do bands made before a cutoff hold after it?

For one stored analysis:
- before: newcomer PRs that were mature *at the cutoff* — created at least maturity_days
  before it and already merged or closed by then, judged from merged_at / closed_at rather
  than from today's state;
- after: newcomer PRs created on or after the cutoff and mature at the snapshot.
Each area is banded on the before sample exactly as a report would band it (Wilson
interval against the before repo rate, minimum sample). An area "held" if its after merge
rate is on the same side of the after repo rate: above for "above repo average", below
for "below repo average". Only areas meeting the minimum sample in both periods count.

What can still leak from after the cutoff, or bend the before sample:
- newcomer status comes from the stored analysis, which used merges up to the snapshot, so a
  before-cutoff PR whose author's earlier PR merged only after the cutoff is not counted as
  a newcomer PR. `possible_newcomer_leaks` gives an upper bound for each repository;
- only the last close or merge time is stored, so a PR closed before the cutoff and reopened
  after it looks open at the cutoff and drops out of the before sample;
- areas are those of the tree at the snapshot.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from repocompass.config import Settings
from repocompass.db import connect
from repocompass.metrics import ABOVE, BELOW, NO_CLEAR_DIFFERENCE, band, wilson_interval

__all__ = [
    "AreaCheck",
    "RepoCheck",
    "StoredPr",
    "after_sample",
    "before_sample",
    "bootstrap_ci",
    "check_repo",
    "load_repo",
    "outcome_at",
    "pool",
]


@dataclass(frozen=True)
class StoredPr:
    number: int
    author: str
    created_at: datetime
    merged_at: datetime | None
    closed_at: datetime | None
    state: str
    merged: bool
    files_complete: bool
    is_newcomer: bool
    areas: tuple[str, ...]


@dataclass(frozen=True)
class AreaCheck:
    area: str
    n_before: int
    merged_before: int
    wilson_before: tuple[float, float] | None
    band_before: str
    n_after: int
    merged_after: int
    rate_after: float | None
    qualifies: bool  # at least min_sample in both periods
    held: bool | None  # None unless the area qualifies and was banded above or below


@dataclass(frozen=True)
class RepoCheck:
    slug: str
    snapshot: datetime
    cutoff: datetime
    n_before: int
    repo_rate_before: float | None
    n_after: int
    repo_rate_after: float | None
    areas: list[AreaCheck]
    # before-sample candidates stored as non-newcomer with no earlier PR by the same author in
    # the stored data that merged before the cutoff. An upper bound on newcomer-status leaks:
    # the earlier merged PR may simply be older than the stored 12 months.
    possible_newcomer_leaks: int


def outcome_at(pr: StoredPr, when: datetime) -> str | None:
    """'merged' or 'closed' if that had happened by `when`, else None (still open then)."""
    if pr.merged_at is not None and pr.merged_at < when:
        return "merged"
    if pr.merged_at is None and pr.closed_at is not None and pr.closed_at < when:
        return "closed"
    return None


def before_sample(
    prs: list[StoredPr], cutoff: datetime, *, maturity_days: int
) -> list[tuple[StoredPr, bool]]:
    """Newcomer PRs mature at the cutoff, with whether they were merged by then."""
    latest = cutoff - timedelta(days=maturity_days)
    out = []
    for pr in prs:
        if pr.is_newcomer and pr.files_complete and pr.created_at <= latest:
            outcome = outcome_at(pr, cutoff)
            if outcome is not None:
                out.append((pr, outcome == "merged"))
    return out


def after_sample(
    prs: list[StoredPr], cutoff: datetime, snapshot: datetime, *, maturity_days: int
) -> list[tuple[StoredPr, bool]]:
    """Newcomer PRs created from the cutoff on and mature at the snapshot."""
    latest = snapshot - timedelta(days=maturity_days)
    return [
        (pr, pr.merged)
        for pr in prs
        if pr.is_newcomer
        and pr.files_complete
        and cutoff <= pr.created_at <= latest
        and pr.state != "OPEN"
    ]


def _counts(sample: list[tuple[StoredPr, bool]]) -> dict[str, list[int]]:
    """Per area: [mature newcomer PRs, merged]. Ties count for each tied area, as in reports."""
    counts: dict[str, list[int]] = {}
    for pr, merged in sample:
        for area in pr.areas:
            entry = counts.setdefault(area, [0, 0])
            entry[0] += 1
            entry[1] += int(merged)
    return counts


def _rate(sample: list[tuple[StoredPr, bool]]) -> float | None:
    return sum(m for _, m in sample) / len(sample) if sample else None


def check_repo(
    slug: str, prs: list[StoredPr], snapshot: datetime, cutoff: datetime, params: dict[str, Any]
) -> RepoCheck:
    before = before_sample(prs, cutoff, maturity_days=params["maturity_days"])
    after = after_sample(prs, cutoff, snapshot, maturity_days=params["maturity_days"])
    rate_before, rate_after = _rate(before), _rate(after)
    counts_before, counts_after = _counts(before), _counts(after)
    minimum = params["min_sample"]
    areas = []
    for area in sorted(counts_before.keys() | counts_after.keys()):
        n_b, m_b = counts_before.get(area, [0, 0])
        n_a, m_a = counts_after.get(area, [0, 0])
        interval = wilson_interval(m_b, n_b, params["wilson_z"])
        banded = band(interval, rate_before, n_b >= minimum)
        qualifies = n_b >= minimum and n_a >= minimum
        rate_a = m_a / n_a if n_a else None
        held = None
        if qualifies and rate_a is not None and rate_after is not None:
            if banded == ABOVE:
                held = rate_a > rate_after
            elif banded == BELOW:
                held = rate_a < rate_after
        areas.append(AreaCheck(area, n_b, m_b, interval, banded, n_a, m_a, rate_a, qualifies, held))
    leaks = _possible_newcomer_leaks(prs, cutoff, params["maturity_days"])
    return RepoCheck(
        slug, snapshot, cutoff, len(before), rate_before, len(after), rate_after, areas, leaks
    )


def _possible_newcomer_leaks(prs: list[StoredPr], cutoff: datetime, maturity_days: int) -> int:
    latest = cutoff - timedelta(days=maturity_days)
    merged_before: dict[str, list[datetime]] = {}
    for pr in prs:
        if pr.merged_at is not None and pr.merged_at < cutoff:
            merged_before.setdefault(pr.author, []).append(pr.created_at)
    count = 0
    for pr in prs:
        if pr.is_newcomer or not pr.files_complete or pr.created_at > latest:
            continue
        if outcome_at(pr, cutoff) is None:
            continue
        earlier = [c for c in merged_before.get(pr.author, []) if c < pr.created_at]
        if not earlier:
            count += 1
    return count


def bootstrap_ci(values: list[bool], *, resamples: int, seed: int) -> tuple[float, float] | None:
    """Percentile bootstrap 95% interval for a proportion, resampling the values themselves."""
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(resamples))
    return means[int(0.025 * resamples)], means[min(resamples - 1, int(0.975 * resamples))]


def pool(checks: list[RepoCheck], *, resamples: int, seed: int) -> dict[str, Any]:
    """Across repositories: for each band, how many qualifying areas held, with a bootstrap CI."""
    out: dict[str, Any] = {}
    for key, name in (("above", ABOVE), ("below", BELOW)):
        held = [a.held for c in checks for a in c.areas if a.qualifies and a.band_before == name]
        values = [bool(h) for h in held]
        out[key] = {
            "areas": len(values),
            "held": sum(values),
            "proportion": sum(values) / len(values) if values else None,
            "bootstrap_95": bootstrap_ci(values, resamples=resamples, seed=seed),
        }
    # for comparison: how often a "no clear difference" area ended up above the repo rate after
    flat = [
        a.rate_after > c.repo_rate_after
        for c in checks
        for a in c.areas
        if a.qualifies
        and a.band_before == NO_CLEAR_DIFFERENCE
        and a.rate_after is not None
        and c.repo_rate_after is not None
    ]
    out["no_clear_difference_above_after"] = {"areas": len(flat), "above": sum(flat)}
    return out


def load_repo(
    settings: Settings, owner: str, name: str
) -> tuple[str, datetime, dict[str, Any], list[StoredPr]]:
    """A stored analysis: canonical slug, snapshot, parameters, and its PRs with their areas."""
    with connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, canonical_slug, snapshot_at, parameters FROM repos"
            " WHERE lower(canonical_slug) = %s OR lower(requested_slug) = %s",
            (f"{owner}/{name}".lower(),) * 2,
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"{owner}/{name} has not been analysed")
        repo_id, slug, snapshot, params = row
        cur.execute(
            "SELECT p.number, p.author_login, p.created_at, p.merged_at, p.closed_at, p.state,"
            " p.is_merged, p.files_complete, p.is_newcomer,"
            " coalesce(array_agg(a.area ORDER BY a.area) FILTER (WHERE a.area IS NOT NULL), '{}')"
            " FROM prs p LEFT JOIN pr_areas a ON a.repo_id = p.repo_id AND a.pr_number = p.number"
            " WHERE p.repo_id = %s GROUP BY p.repo_id, p.number",
            (repo_id,),
        )
        prs = [StoredPr(*r[:9], areas=tuple(r[9])) for r in cur.fetchall()]
    return slug, snapshot, params, prs


def to_json(check: RepoCheck) -> dict[str, Any]:
    out = asdict(check)
    out["snapshot"] = check.snapshot.isoformat()
    out["cutoff"] = check.cutoff.isoformat()
    return out
