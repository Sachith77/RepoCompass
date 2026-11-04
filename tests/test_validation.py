"""Tests for the cutoff validation: nothing from after the cutoff, bands, pooled result."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from repocompass.metrics import ABOVE, BELOW, NO_CLEAR_DIFFERENCE
from repocompass.validation import (
    StoredPr,
    after_sample,
    before_sample,
    bootstrap_ci,
    check_repo,
    outcome_at,
    pool,
)

SNAPSHOT = datetime(2026, 11, 3, tzinfo=UTC)
CUTOFF = SNAPSHOT - timedelta(days=182)
PARAMS = {"maturity_days": 30, "min_sample": 10, "wilson_z": 1.959963985}


def _pr(
    number: int,
    *,
    created: datetime,
    merged: datetime | None = None,
    closed: datetime | None = None,
    newcomer: bool = True,
    complete: bool = True,
    areas: tuple[str, ...] = ("docs",),
) -> StoredPr:
    if merged is not None:
        closed = merged
    state = "MERGED" if merged else ("CLOSED" if closed else "OPEN")
    return StoredPr(
        number=number,
        author=f"u{number}",
        created_at=created,
        merged_at=merged,
        closed_at=closed,
        state=state,
        merged=merged is not None,
        files_complete=complete,
        is_newcomer=newcomer,
        areas=areas,
    )


# --- no information from after the cutoff -----------------------------------------


def test_outcome_at_the_cutoff_uses_only_what_had_happened_by_then() -> None:
    early = CUTOFF - timedelta(days=60)
    assert outcome_at(_pr(1, created=early, merged=CUTOFF - timedelta(days=1)), CUTOFF) == "merged"
    assert outcome_at(_pr(2, created=early, closed=CUTOFF - timedelta(days=1)), CUTOFF) == "closed"
    # merged after the cutoff: at the cutoff it was still open
    assert outcome_at(_pr(3, created=early, merged=CUTOFF + timedelta(days=1)), CUTOFF) is None
    assert outcome_at(_pr(4, created=early), CUTOFF) is None


def test_the_before_sample_is_mature_at_the_cutoff_not_at_the_snapshot() -> None:
    prs = [
        _pr(1, created=CUTOFF - timedelta(days=40), merged=CUTOFF - timedelta(days=30)),
        _pr(
            2, created=CUTOFF - timedelta(days=20), merged=CUTOFF - timedelta(days=10)
        ),  # too young
        _pr(3, created=CUTOFF - timedelta(days=40), merged=CUTOFF + timedelta(days=5)),  # open then
        _pr(
            4,
            created=CUTOFF - timedelta(days=40),
            closed=CUTOFF - timedelta(days=1),
            newcomer=False,
        ),
        _pr(
            5,
            created=CUTOFF - timedelta(days=40),
            closed=CUTOFF - timedelta(days=1),
            complete=False,
        ),
        _pr(6, created=CUTOFF - timedelta(days=40), closed=CUTOFF - timedelta(days=2)),
    ]
    sample = before_sample(prs, CUTOFF, maturity_days=30)
    assert [(pr.number, merged) for pr, merged in sample] == [(1, True), (6, False)]


def test_the_after_sample_starts_at_the_cutoff_and_is_mature_at_the_snapshot() -> None:
    prs = [
        _pr(1, created=CUTOFF - timedelta(days=1), merged=CUTOFF + timedelta(days=3)),  # before
        _pr(2, created=CUTOFF + timedelta(days=1), merged=CUTOFF + timedelta(days=3)),
        _pr(3, created=SNAPSHOT - timedelta(days=10), merged=SNAPSHOT - timedelta(days=2)),  # young
        _pr(4, created=CUTOFF + timedelta(days=5)),  # still open
        _pr(5, created=CUTOFF + timedelta(days=5), closed=CUTOFF + timedelta(days=9)),
    ]
    sample = after_sample(prs, CUTOFF, SNAPSHOT, maturity_days=30)
    assert [(pr.number, merged) for pr, merged in sample] == [(2, True), (5, False)]


# --- per repository ---------------------------------------------------------------


def _period(start: datetime, area: str, merged: int, closed: int, offset: int) -> list[StoredPr]:
    out = []
    for i in range(merged + closed):
        created = start + timedelta(days=i % 20)
        resolved = created + timedelta(days=1)
        out.append(
            _pr(
                offset + i,
                created=created,
                merged=resolved if i < merged else None,
                closed=None if i < merged else resolved,
                areas=(area,),
            )
        )
    return out


def test_an_area_banded_above_before_is_checked_against_the_repo_rate_after() -> None:
    before_start = CUTOFF - timedelta(days=150)
    after_start = CUTOFF + timedelta(days=5)
    prs = (
        _period(before_start, "docs", 18, 2, 0)  # 90% merged before
        + _period(before_start, "src", 4, 16, 100)  # 20% merged before
        + _period(after_start, "docs", 8, 4, 200)  # 67% after
        + _period(after_start, "src", 3, 9, 300)  # 25% after
    )
    result = check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS)
    areas = {a.area: a for a in result.areas}
    assert result.repo_rate_before == pytest.approx(22 / 40)
    assert result.repo_rate_after == pytest.approx(11 / 24)
    assert areas["docs"].band_before == ABOVE
    assert areas["docs"].held is True  # 0.667 > 0.458
    assert areas["src"].band_before == BELOW
    assert areas["src"].held is True  # 0.25 < 0.458
    assert areas["docs"].qualifies and areas["src"].qualifies


def test_an_area_below_the_minimum_in_either_period_does_not_qualify() -> None:
    before_start = CUTOFF - timedelta(days=150)
    prs = _period(before_start, "docs", 18, 2, 0) + _period(
        CUTOFF + timedelta(days=5), "docs", 5, 4, 100
    )
    (docs,) = check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS).areas
    assert (docs.n_before, docs.n_after) == (20, 9)
    assert docs.qualifies is False
    assert docs.held is None


def test_no_clear_difference_and_not_enough_data_are_not_held_or_broken() -> None:
    before_start = CUTOFF - timedelta(days=150)
    prs = _period(before_start, "docs", 5, 5, 0) + _period(
        CUTOFF + timedelta(days=5), "docs", 5, 5, 50
    )
    (docs,) = check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS).areas
    assert docs.band_before == NO_CLEAR_DIFFERENCE
    assert docs.held is None


# --- pooled result -----------------------------------------------------------------


def test_bootstrap_is_reproducible_and_brackets_the_proportion() -> None:
    values = [True] * 6 + [False] * 4
    low, high = bootstrap_ci(values, resamples=2000, seed=0)
    assert low <= 0.6 <= high
    assert bootstrap_ci(values, resamples=2000, seed=0) == (low, high)
    assert bootstrap_ci([], resamples=10, seed=0) is None


def test_pool_counts_held_areas_per_band_across_repositories() -> None:
    before_start = CUTOFF - timedelta(days=150)
    after_start = CUTOFF + timedelta(days=5)
    prs = (
        _period(before_start, "docs", 18, 2, 0)
        + _period(before_start, "src", 4, 16, 100)
        + _period(after_start, "docs", 8, 4, 200)
        + _period(after_start, "src", 3, 9, 300)
    )
    checks = [check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS)]
    pooled = pool(checks, resamples=500, seed=0)
    assert pooled["above"]["held"] == 1 and pooled["above"]["areas"] == 1
    assert pooled["below"]["held"] == 1 and pooled["below"]["areas"] == 1


def test_the_summary_is_written_from_the_same_numbers(tmp_path) -> None:
    from repocompass.validation_report import write_results

    before_start = CUTOFF - timedelta(days=150)
    after_start = CUTOFF + timedelta(days=5)
    prs = _period(before_start, "docs", 18, 2, 0) + _period(after_start, "docs", 8, 4, 200)
    prs += _period(before_start, "src", 4, 16, 100) + _period(after_start, "src", 3, 9, 300)
    checks = [check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS)]
    summary = write_results(checks, pool(checks, resamples=200, seed=0), PARAMS, 182, tmp_path)
    text = summary.read_text(encoding="utf-8")
    assert "Cutoff: 182 days before" in text
    assert "| `docs` | above repo average | 20 | 0.900" in text
    assert "**above repo average**: 1 of 1 qualifying areas held" in text
    assert (tmp_path / "o__r.json").exists() and (tmp_path / "pooled.json").exists()


def test_an_above_area_that_falls_below_the_after_repo_rate_did_not_hold() -> None:
    """Also shows bands use the before repo rate: against the after rate docs would not be above."""
    before_start = CUTOFF - timedelta(days=150)
    after_start = CUTOFF + timedelta(days=5)
    prs = (
        _period(before_start, "docs", 18, 2, 0)  # 0.90 before
        + _period(before_start, "src", 2, 18, 100)  # before repo rate 0.50
        + _period(after_start, "docs", 8, 4, 200)  # 0.667 after
        + _period(after_start, "src", 12, 0, 300)  # after repo rate 20/24 = 0.833
    )
    areas = {a.area: a for a in check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS).areas}
    assert areas["docs"].band_before == ABOVE  # Wilson low 0.699 > 0.50, but < 0.833
    assert areas["docs"].held is False


def test_exactly_the_minimum_sample_in_both_periods_qualifies() -> None:
    before_start = CUTOFF - timedelta(days=150)
    prs = _period(before_start, "docs", 9, 1, 0) + _period(
        CUTOFF + timedelta(days=5), "docs", 5, 5, 50
    )
    (docs,) = check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS).areas
    assert (docs.n_before, docs.n_after) == (10, 10)
    assert docs.qualifies is True


def test_a_tied_pr_counts_for_each_tied_area() -> None:
    created = CUTOFF - timedelta(days=60)
    tied = _pr(1, created=created, merged=created + timedelta(days=1), areas=("docs", "src"))
    areas = {a.area: a for a in check_repo("o/r", [tied], SNAPSHOT, CUTOFF, PARAMS).areas}
    assert areas["docs"].n_before == areas["src"].n_before == 1


def test_pool_skips_areas_that_do_not_qualify_and_counts_the_comparison_group() -> None:
    before_start = CUTOFF - timedelta(days=150)
    after_start = CUTOFF + timedelta(days=5)
    prs = (
        _period(before_start, "docs", 18, 2, 0)  # above before, but only 5 after: skipped
        + _period(after_start, "docs", 4, 1, 200)
        + _period(before_start, "mid", 10, 10, 100)  # no clear difference, 10 after
        + _period(after_start, "mid", 9, 1, 300)
        + _period(before_start, "src", 4, 16, 400)  # below before, 12 after
        + _period(after_start, "src", 3, 9, 500)
    )
    pooled = pool([check_repo("o/r", prs, SNAPSHOT, CUTOFF, PARAMS)], resamples=200, seed=0)
    assert pooled["above"]["areas"] == 0
    assert pooled["above"]["bootstrap_95"] is None
    assert pooled["below"] == {**pooled["below"], "areas": 1, "held": 1}
    assert pooled["no_clear_difference_above_after"] == {"areas": 1, "above": 1}


def test_a_bootstrap_of_identical_values_is_degenerate() -> None:
    assert bootstrap_ci([True, True], resamples=500, seed=0) == (1.0, 1.0)


def test_possible_newcomer_leaks_counts_non_newcomers_without_an_earlier_merge_by_the_cutoff() -> (
    None
):
    early = CUTOFF - timedelta(days=90)
    later_merge = _pr(1, created=early, merged=CUTOFF + timedelta(days=3))  # merged after cutoff
    suspect = replace(
        _pr(2, created=early + timedelta(days=1), closed=CUTOFF - timedelta(days=40)),
        author="u1",
        is_newcomer=False,
    )
    clean_first = _pr(3, created=early, merged=early + timedelta(days=1))
    clean = replace(
        _pr(4, created=early + timedelta(days=5), closed=CUTOFF - timedelta(days=40)),
        author="u3",
        is_newcomer=False,
    )
    result = check_repo("o/r", [later_merge, suspect, clean_first, clean], SNAPSHOT, CUTOFF, PARAMS)
    assert result.possible_newcomer_leaks == 1
