"""Tests for the metrics: newcomers, maturity, Wilson, bands, per-area stats, sample note."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from repocompass.config import load_settings
from repocompass.metrics import (
    ABOVE,
    BELOW,
    NO_CLEAR_DIFFERENCE,
    NOT_ENOUGH_DATA,
    AreaStats,
    area_stats,
    band,
    is_mature,
    mark_newcomers,
    repo_rate,
    sample_note,
    wilson_interval,
)
from repocompass.prs import new_fetch_state
from repocompass.records import PrRecord

SETTINGS = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": "postgresql://u:p@h/d"})
SNAPSHOT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _pr(
    number: int,
    *,
    author: str = "ada",
    days_ago: float = 60,
    state: str = "MERGED",
    area_files: dict[str, int] | None = None,
    newcomer: bool = True,
    complete: bool = True,
    review_hours: float | None = None,
    response_hours: float | None = None,
    responses_known: bool = True,
    reviewers: tuple[str, ...] = (),
) -> PrRecord:
    created = SNAPSHOT - timedelta(days=days_ago)

    def later(hours: float | None) -> datetime | None:
        return None if hours is None else created + timedelta(hours=hours)

    return PrRecord(
        number=number,
        author=author,
        association="NONE",
        created_at=created,
        merged_at=created + timedelta(days=1) if state == "MERGED" else None,
        closed_at=created + timedelta(days=1) if state != "OPEN" else None,
        state=state,
        merged=state == "MERGED",
        changed_files=1,
        files_complete=complete,
        area_files=area_files if area_files is not None else {"docs": 1},
        first_formal_review_at=later(review_hours),
        first_human_response_at=later(response_hours),
        response_times_complete=responses_known,
        reviewers=reviewers,
        is_newcomer=newcomer,
    )


# --- newcomers ----------------------------------------------------------------


def test_a_pr_is_a_newcomer_pr_until_the_authors_first_merged_pr() -> None:
    first = _pr(1, days_ago=100, newcomer=False)
    second = _pr(2, days_ago=50, newcomer=False)
    earliest = {"ada": first.created_at.isoformat()}
    marked = mark_newcomers([first, second], earliest)
    assert [r.is_newcomer for r in marked] == [True, False]


def test_an_author_with_no_merged_pr_is_a_newcomer_on_every_pr() -> None:
    marked = mark_newcomers([_pr(1, newcomer=False), _pr(2, newcomer=False)], {"ada": None})
    assert all(r.is_newcomer for r in marked)


# --- maturity and the merge rate ---------------------------------------------


def test_mature_means_thirty_days_old_and_no_longer_open() -> None:
    assert is_mature(_pr(1, days_ago=30), SNAPSHOT, SETTINGS)
    assert not is_mature(_pr(1, days_ago=29.9), SNAPSHOT, SETTINGS)
    assert not is_mature(_pr(1, days_ago=200, state="OPEN"), SNAPSHOT, SETTINGS)
    assert is_mature(_pr(1, days_ago=200, state="CLOSED"), SNAPSHOT, SETTINGS)


def test_repo_rate_counts_mature_newcomer_prs_only() -> None:
    records = [
        _pr(1, state="MERGED"),
        _pr(2, state="CLOSED"),
        _pr(3, state="OPEN"),  # never in the denominator
        _pr(4, days_ago=5),  # too young
        _pr(5, newcomer=False),  # not a newcomer
        _pr(6, complete=False),  # file list incomplete: excluded
    ]
    assert repo_rate(records, SNAPSHOT, SETTINGS) == (pytest.approx(0.5), 2)


def test_repo_rate_includes_prs_that_touched_no_current_area() -> None:
    assert repo_rate([_pr(1, area_files={})], SNAPSHOT, SETTINGS) == (pytest.approx(1.0), 1)


def test_repo_rate_is_none_without_mature_newcomer_prs() -> None:
    assert repo_rate([], SNAPSHOT, SETTINGS) == (None, 0)


# --- Wilson and bands ---------------------------------------------------------


def test_wilson_matches_textbook_and_phase0_values() -> None:
    low, high = wilson_interval(5, 10, SETTINGS.wilson_z)
    assert (low, high) == (pytest.approx(0.2366, abs=1e-4), pytest.approx(0.7634, abs=1e-4))
    # optuna/visualization in results/phase0/area_sample_sizes.json: 9 of 15
    low, high = wilson_interval(9, 15, SETTINGS.wilson_z)
    assert (low, high) == (pytest.approx(0.3575, abs=1e-4), pytest.approx(0.8018, abs=1e-4))
    low, high = wilson_interval(0, 10, SETTINGS.wilson_z)
    assert low == pytest.approx(0.0, abs=1e-12)
    assert high == pytest.approx(0.2775, abs=1e-4)


def test_wilson_needs_at_least_one_pr() -> None:
    assert wilson_interval(0, 0, SETTINGS.wilson_z) is None


@pytest.mark.parametrize(
    ("interval", "rate", "meets", "expected"),
    [
        ((0.6, 0.9), 0.5, True, ABOVE),
        ((0.1, 0.4), 0.5, True, BELOW),
        ((0.4, 0.7), 0.5, True, NO_CLEAR_DIFFERENCE),
        ((0.5, 0.7), 0.5, True, NO_CLEAR_DIFFERENCE),  # touching is overlapping
        ((0.6, 0.9), 0.5, False, NOT_ENOUGH_DATA),
        ((0.6, 0.9), None, True, NOT_ENOUGH_DATA),
        (None, 0.5, True, NOT_ENOUGH_DATA),
    ],
)
def test_band_compares_the_interval_with_the_repo_rate(
    interval: tuple[float, float] | None, rate: float | None, meets: bool, expected: str
) -> None:
    assert band(interval, rate, meets) == expected


# --- per-area stats ----------------------------------------------------------


def _stats(records: list[PrRecord], areas: tuple[str, ...] = ("docs", "tests")) -> dict:
    rate, _n = repo_rate(records, SNAPSHOT, SETTINGS)
    return {s.area: s for s in area_stats(records, areas, SNAPSHOT, SETTINGS, rate)}


def _docs(records: list[PrRecord]) -> AreaStats:
    return _stats(records)["docs"]


def test_nine_prs_are_not_enough_data_but_keep_their_counts() -> None:
    stats = _stats([_pr(i, author=f"u{i}") for i in range(9)])
    docs = stats["docs"]
    assert (docs.mature_newcomer_prs, docs.merged_prs) == (9, 9)
    assert docs.meets_min_sample is False
    assert docs.band == NOT_ENOUGH_DATA
    assert stats["tests"].mature_newcomer_prs == 0


def test_exactly_ten_prs_meet_the_minimum_sample() -> None:
    assert _docs([_pr(i, author=f"u{i}") for i in range(10)]).meets_min_sample is True


def test_area_bands_against_the_repo_rate() -> None:
    docs = [_pr(i, author=f"d{i}", state="MERGED") for i in range(20)]
    tests = [
        _pr(100 + i, author=f"t{i}", area_files={"tests": 1}, state="CLOSED") for i in range(20)
    ]
    stats = _stats(docs + tests)
    assert stats["docs"].band == ABOVE
    assert stats["tests"].band == BELOW
    assert stats["docs"].merge_rate == pytest.approx(1.0)


def test_tied_prs_count_for_each_tied_area() -> None:
    stats = _stats([_pr(1, area_files={"docs": 2, "tests": 2})])
    assert stats["docs"].mature_newcomer_prs == 1
    assert stats["tests"].mature_newcomer_prs == 1


def test_distinct_authors_and_the_concentration_flag() -> None:
    records = [_pr(i, author="ada") for i in range(4)] + [
        _pr(10 + i, author=f"u{i}") for i in range(8)
    ]
    docs = _docs(records)
    assert docs.mature_newcomer_prs == 12
    assert docs.distinct_newcomer_authors == 9
    assert docs.top_author_pr_share == pytest.approx(4 / 12)
    assert docs.author_concentration_flag is True  # 33% > 30%


def test_exactly_thirty_percent_does_not_raise_the_flag() -> None:
    records = [_pr(i, author="ada") for i in range(3)] + [
        _pr(10 + i, author=f"u{i}") for i in range(7)
    ]
    docs = _docs(records)
    assert docs.top_author_pr_share == pytest.approx(0.3)
    assert docs.author_concentration_flag is False


def test_stale_open_means_more_than_ninety_days_and_stays_out_of_the_rate() -> None:
    records = [
        _pr(1, state="OPEN", days_ago=120),  # stale
        _pr(2, state="OPEN", days_ago=90),  # exactly 90 days: not yet "more than"
        _pr(3, state="OPEN", days_ago=60),
        _pr(4, state="OPEN", days_ago=120, newcomer=False),  # not a newcomer
    ]
    docs = _docs(records)
    assert docs.stale_open_newcomer_prs == 1
    assert docs.mature_newcomer_prs == 0


def test_medians_use_newcomer_prs_that_got_a_response_and_say_how_many() -> None:
    records = [
        _pr(1, review_hours=2, response_hours=1),
        _pr(2, review_hours=10, response_hours=10),
        _pr(3, review_hours=None, response_hours=3),
        _pr(4, review_hours=None, response_hours=None),
        _pr(5, review_hours=1, response_hours=1, responses_known=False),  # unknown: left out
    ]
    docs = _docs(records)
    assert (docs.median_hours_first_formal_review, docs.formal_review_prs) == (6.0, 2)
    assert (docs.median_hours_first_human_response, docs.human_response_prs) == (3.0, 3)


def test_no_response_share_counts_mature_prs_unanswered_within_thirty_days() -> None:
    records = [
        _pr(1, response_hours=5),  # answered
        _pr(2, response_hours=24 * 31),  # answered, but after 30 days
        _pr(3, response_hours=None),  # never answered
        _pr(4, response_hours=None, responses_known=False),  # unknown: left out
        _pr(5, response_hours=None, state="OPEN"),  # not mature: left out
    ]
    docs = _docs(records)
    assert docs.no_response_base_prs == 3
    assert docs.no_response_share == pytest.approx(2 / 3)


def test_top_people_count_merged_prs_and_reviews() -> None:
    records = [
        _pr(1, author="ada", newcomer=False, reviewers=("grace", "grace", "linus")),
        _pr(2, author="ada", newcomer=False, reviewers=("grace",)),
        _pr(3, author="bob", state="CLOSED", newcomer=False, reviewers=("linus",)),
    ]
    docs = _docs(records)
    assert docs.top_contributors == [{"login": "ada", "count": 2}]
    assert docs.top_reviewers == [{"login": "grace", "count": 3}, {"login": "linus", "count": 2}]


def test_every_area_gets_stats_even_without_prs() -> None:
    stats = _stats([], areas=("docs", "tests"))
    assert set(stats) == {"docs", "tests"}
    assert all(s.band == NOT_ENOUGH_DATA for s in stats.values())


def test_incomplete_prs_are_left_out_of_area_stats() -> None:
    assert _docs([replace(_pr(1), files_complete=False)]).mature_newcomer_prs == 0


# --- sample note ----------------------------------------------------------------


def _fetch_state(**months: dict[str, object]) -> dict:
    state = new_fetch_state()
    for key, values in months.items():
        state[key] = values
    return state


def test_sample_note_totals_months_dates_and_flags_capping() -> None:
    sep_first, sep_last = "2026-09-10T00:00:00+00:00", "2026-09-30T00:00:00+00:00"
    oct_first, oct_last = "2026-10-01T00:00:00+00:00", "2026-10-31T00:00:00+00:00"
    note = sample_note(
        _fetch_state(
            month_totals={"2026-09": 300, "2026-10": 40},
            month_bots={"2026-09": 12},
            month_sampled={"2026-09": 250, "2026-10": 40},
            month_first={"2026-09": sep_first, "2026-10": oct_first},
            month_last={"2026-09": sep_last, "2026-10": oct_last},
        )
    )
    assert (note.total_prs, note.bot_prs, note.sampled_prs) == (340, 12, 290)
    assert note.per_month["2026-09"] == {
        "total": 300,
        "bots": 12,
        "sampled": 250,
        "first": sep_first,
        "last": sep_last,
    }
    assert note.is_sampled is True
    assert (note.covered_from, note.covered_to) == (sep_first, oct_last)


def test_sample_note_is_not_sampled_when_no_month_was_capped() -> None:
    note = sample_note(_fetch_state(month_totals={"2026-10": 40}, month_sampled={"2026-10": 40}))
    assert note.is_sampled is False
