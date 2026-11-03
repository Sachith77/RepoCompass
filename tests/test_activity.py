"""Tests for commit-based area activity: bot and sweep filters, windows and bands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from repocompass.activity import (
    Commit,
    activity_band,
    is_bot_commit,
    is_sweep,
    summarise_activity,
)
from repocompass.config import Settings, load_settings

SETTINGS = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": "postgresql://u:p@h/d"})
SNAPSHOT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
AREAS = ["docs", "pkg/cli", "pkg/core", "tests"]
DEPTHS = {"pkg": 2}


def _commit(
    days_ago: float,
    *paths: str,
    name: str = "Ada Lovelace",
    email: str = "ada@example.com",
) -> Commit:
    return Commit(
        sha=f"{days_ago}-{name}",
        committed_at=SNAPSHOT - timedelta(days=days_ago),
        author_name=name,
        author_email=email,
        paths=tuple(paths),
    )


def _by_area(commits: list[Commit]) -> dict[str, tuple[int, int, int, str]]:
    summary = summarise_activity(commits, AREAS, DEPTHS, SETTINGS, SNAPSHOT)
    return {
        a.area: (a.commits_recent, a.commits_window, a.authors_window, a.band)
        for a in summary.areas
    }


# --- bands -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("recent", "window", "band"),
    [(1, 1, "active"), (5, 40, "active"), (0, 3, "steady"), (0, 0, "dormant")],
)
def test_activity_band_uses_only_the_two_windows(recent: int, window: int, band: str) -> None:
    assert activity_band(recent, window) == band


def test_recent_boundary_is_inclusive_and_window_boundary_excludes_older() -> None:
    rows = _by_area(
        [
            _commit(90, "docs/a.md"),  # exactly 90 days: still recent
            _commit(91, "tests/t.py"),  # in the 12 months, not recent
            _commit(366, "pkg/core/x.py"),  # older than the window
        ]
    )
    assert rows["docs"] == (1, 1, 1, "active")
    assert rows["tests"] == (0, 1, 1, "steady")
    assert rows["pkg/core"] == (0, 0, 0, "dormant")


def test_future_dated_commits_are_ignored() -> None:
    rows = _by_area([_commit(-5, "docs/a.md")])
    assert rows["docs"] == (0, 0, 0, "dormant")


# --- what a commit counts towards -------------------------------------------


def test_a_commit_counts_once_per_area_however_many_files() -> None:
    rows = _by_area([_commit(1, "pkg/core/a.py", "pkg/core/b.py", "tests/t.py")])
    assert rows["pkg/core"][1] == 1
    assert rows["tests"][1] == 1
    assert rows["docs"][1] == 0


def test_root_files_excluded_dirs_and_removed_areas_count_for_nothing() -> None:
    summary = summarise_activity(
        [_commit(1, "README.md", "vendor/lib.go", "old_dir/gone.py")],
        AREAS,
        DEPTHS,
        SETTINGS,
        SNAPSHOT,
    )
    assert all(a.commits_window == 0 for a in summary.areas)
    assert summary.counted_commits == 0


def test_distinct_authors_are_counted_by_email_case_insensitively() -> None:
    rows = _by_area(
        [
            _commit(1, "docs/a.md", email="ada@example.com"),
            _commit(2, "docs/b.md", email="ADA@example.com"),
            _commit(3, "docs/c.md", name="Grace Hopper", email="grace@example.com"),
        ]
    )
    assert rows["docs"] == (3, 3, 2, "active")


# --- bots -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "email"),
    [
        ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
        ("Someone", "41898282+github-actions[bot]@users.noreply.github.com"),
        ("renovate", "bot@renovateapp.com"),
        ("", ""),
    ],
)
def test_bot_commits_are_recognised(name: str, email: str) -> None:
    assert is_bot_commit(name, email, SETTINGS)


def test_people_are_not_bots() -> None:
    assert not is_bot_commit("Ada Lovelace", "ada@example.com", SETTINGS)
    assert not is_bot_commit("Ada", "12345+ada@users.noreply.github.com", SETTINGS)
    assert not is_bot_commit("Ada", "", SETTINGS)
    # an empty name with a real email is still a person
    assert not is_bot_commit("", "ada@example.com", SETTINGS)


def test_bot_commits_count_for_nothing() -> None:
    summary = summarise_activity(
        [_commit(1, "docs/a.md", name="dependabot[bot]", email="x@example.com")],
        AREAS,
        DEPTHS,
        SETTINGS,
        SNAPSHOT,
    )
    assert summary.bot_commits == 1
    assert {a.area: a.commits_window for a in summary.areas}["docs"] == 0


# --- sweeps ---------------------------------------------------------------
# A sweep needs both: more than half of all areas, and at least five areas.

SIX_AREAS = ["a", "b", "c", "d", "e", "f"]


def _six_area_commit(days_ago: float, *areas: str) -> Commit:
    return _commit(days_ago, *(f"{area}/file.py" for area in areas))


def test_sweep_is_more_than_the_share_of_all_areas() -> None:
    # ten areas: five touched is exactly half, not more, so it is not a sweep
    assert not is_sweep(5, 10, 0.5, 5)
    assert is_sweep(6, 10, 0.5, 5)
    # eight areas: five touched is more than half and meets the minimum
    assert is_sweep(5, 8, 0.5, 5)


def test_sweep_needs_at_least_the_minimum_number_of_areas() -> None:
    """Pinned on purpose: in small repositories ordinary commits are never sweeps.

    Before the minimum, a 'code + tests' commit in a three-area repository was
    ignored as a sweep. Now a commit must touch at least five areas.
    """
    assert not is_sweep(2, 3, 0.5, 5)
    assert not is_sweep(2, 2, 0.5, 5)
    assert not is_sweep(4, 4, 0.5, 5)  # every area, but only four
    assert not is_sweep(4, 6, 0.5, 5)  # more than half, but only four
    assert is_sweep(5, 5, 0.5, 5)


def test_a_single_area_commit_is_never_a_sweep() -> None:
    """In a one-area repository every commit touches 'all' areas; that is not a sweep."""
    assert not is_sweep(1, 1, 0.5, 5)
    assert not is_sweep(1, 2, 0.5, 5)


def test_sweep_commits_count_for_nothing_and_are_reported() -> None:
    summary = summarise_activity(
        [
            _six_area_commit(1, "a", "b", "c", "d", "e"),  # sweep: 5 of 6
            _six_area_commit(2, "a", "b", "c", "d"),  # not a sweep: only 4
        ],
        SIX_AREAS,
        {},
        SETTINGS,
        SNAPSHOT,
    )
    assert summary.sweep_commits == 1
    assert summary.counted_commits == 1
    assert {a.area: a.commits_window for a in summary.areas} == {
        "a": 1,
        "b": 1,
        "c": 1,
        "d": 1,
        "e": 0,
        "f": 0,
    }


def _settings(**overrides: str) -> Settings:
    return load_settings(
        {"GITHUB_TOKEN": "fake", "DATABASE_URL": "postgresql://u:p@h/d", **overrides}
    )


def test_sweep_share_is_configurable() -> None:
    lenient = _settings(REPOCOMPASS_SWEEP_AREA_SHARE="1.0")
    summary = summarise_activity(
        [_six_area_commit(1, *SIX_AREAS)], SIX_AREAS, {}, lenient, SNAPSHOT
    )
    assert summary.sweep_commits == 0
    assert all(a.commits_window == 1 for a in summary.areas)


def test_sweep_minimum_is_configurable() -> None:
    strict = _settings(REPOCOMPASS_SWEEP_MIN_AREAS="3")
    summary = summarise_activity(
        [_commit(1, "docs/a.md", "pkg/cli/b.py", "pkg/core/c.py")], AREAS, DEPTHS, strict, SNAPSHOT
    )
    assert summary.sweep_commits == 1


def test_every_area_gets_a_row_even_with_no_commits() -> None:
    summary = summarise_activity([], AREAS, DEPTHS, SETTINGS, SNAPSHOT)
    assert [a.area for a in summary.areas] == AREAS
    assert all(a.band == "dormant" for a in summary.areas)
