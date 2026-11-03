"""Tests for the report shape, built from rows shaped like the stored tables."""

from __future__ import annotations

from typing import Any

from repocompass.metrics import ABOVE, BELOW, NO_CLEAR_DIFFERENCE, NOT_ENOUGH_DATA
from repocompass.report import (
    FORMAL_REVIEW,
    HEADING,
    HUMAN_RESPONSE,
    OutdatedReport,
    build_report,
    lead_response_measure,
)

REPO = {
    "requested_slug": "encode/starlette",
    "canonical_slug": "Kludex/starlette",
    "default_branch": "main",
    "snapshot_at": "2026-11-03T12:00:00+00:00",
    "repo_merge_rate": 0.227,
    "repo_mature_newcomer_prs": 207,
    "window_start": "2025-11-03T12:00:00+00:00",
    "window_end": "2026-11-03T12:00:00+00:00",
    "total_prs_in_window": 511,
    "bot_prs_in_window": 50,
    "sampled_prs": 511,
    "is_sampled": False,
    "sample_first_created": "2025-11-05T00:00:00+00:00",
    "sample_last_created": "2026-11-03T00:00:00+00:00",
    "prs_per_month": {},
    "area_depths": {"depths": {}},
    "excluded_dirs": ["vendor"],
    "sweep_commits_excluded": 0,
    # the parameters the analysis ran with; the report must use these, not today's settings
    "parameters": {
        "monthly_sample_cap": 250,
        "author_concentration_threshold": 0.3,
        "formal_review_coverage_threshold": 0.5,
        "maturity_days": 30,
    },
}


def _area(name: str, band: str, n: int = 20) -> dict[str, Any]:
    return {
        "area": name,
        "band": band,
        "merge_rate": 0.5,
        "mature_newcomer_prs": n,
        "merged_prs": n // 2,
        "wilson_low": 0.3,
        "wilson_high": 0.7,
        "distinct_newcomer_authors": n,
        "top_author_pr_share": 0.1,
        "author_concentration_flag": False,
        "stale_open_newcomer_prs": 0,
        "median_hours_first_formal_review": 10.0,
        "formal_review_prs": 5,
        "median_hours_first_human_response": 5.0,
        "human_response_prs": 8,
        "no_response_share": 0.4,
        "no_response_base_prs": n,
        "commits_90d": 3,
        "commits_12mo": 30,
        "commit_authors_12mo": 4,
        "activity_band": "active",
        "top_contributors": [{"login": "ada", "count": 2}],
        "top_reviewers": [],
    }


AREAS = [
    _area("tests", BELOW),
    _area("docs", ABOVE),
    _area("src", NO_CLEAR_DIFFERENCE),
    _area("api", NO_CLEAR_DIFFERENCE),
    _area("scripts", NOT_ENOUGH_DATA, n=3),
]


def _report(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "repo": REPO,
        "areas": sorted(AREAS, key=lambda a: a["area"]),
        "examples": {"docs": [12, 9]},
        "pr_counts": (60, 100, 2, 1),
    }
    args.update(overrides)
    return build_report(**args)


def test_where_to_start_comes_first_with_the_required_heading() -> None:
    report = _report()
    assert list(report) == ["repo", "where_to_start", "areas_map", "sample", "method"]
    assert report["where_to_start"]["heading"] == HEADING


def test_bands_are_grouped_above_then_no_difference_then_below_and_alphabetical_inside() -> None:
    bands = _report()["where_to_start"]["bands"]
    assert [b["band"] for b in bands] == [ABOVE, NO_CLEAR_DIFFERENCE, BELOW]
    assert [a["area"] for a in bands[1]["areas"]] == ["api", "src"]


def test_small_areas_are_listed_separately_as_not_enough_data() -> None:
    where = _report()["where_to_start"]
    assert where["not_enough_data"] == [{"area": "scripts", "mature_newcomer_prs": 3}]
    banded = [a["area"] for b in where["bands"] for a in b["areas"]]
    assert "scripts" not in banded


def test_example_prs_link_to_github_under_the_canonical_name() -> None:
    docs = _report()["where_to_start"]["bands"][0]["areas"][0]
    assert docs["example_merged_newcomer_prs"] == [
        {"number": 12, "url": "https://github.com/Kludex/starlette/pull/12"},
        {"number": 9, "url": "https://github.com/Kludex/starlette/pull/9"},
    ]


def test_every_area_is_on_the_areas_map_with_counts_only() -> None:
    areas_map = _report()["areas_map"]
    assert [a["area"] for a in areas_map] == ["api", "docs", "scripts", "src", "tests"]
    assert areas_map[1]["top_contributors"] == [{"login": "ada", "count": 2}]
    assert all("hours" not in key for entry in areas_map for key in entry)  # no per-person speed


def test_the_sample_note_says_when_months_were_capped_and_what_it_covers() -> None:
    note = _report()["sample"]["note"]
    assert note.startswith("Every human-authored PR")
    assert "2025-11-05T00:00:00+00:00 to 2026-11-03T00:00:00+00:00" in note
    capped = _report(repo={**REPO, "is_sampled": True})["sample"]["note"]
    assert capped.startswith("Sampled:")
    assert "250" in capped
    assert "2025-11-05T00:00:00+00:00" in capped


def test_the_sample_says_how_many_prs_were_left_out_and_why() -> None:
    sample = _report()["sample"]
    assert (sample["prs_with_incomplete_files"], sample["prs_with_unknown_response_times"]) == (
        2,
        1,
    )
    assert "2 PRs whose changed files could not all be fetched" in sample["note"]


def test_the_report_uses_the_parameters_the_analysis_ran_with() -> None:
    repo = {
        **REPO,
        "is_sampled": True,
        "parameters": {**REPO["parameters"], "monthly_sample_cap": 100},
    }
    report = _report(repo=repo)
    assert "more than 100 human PRs" in report["sample"]["note"]
    assert report["method"]["parameters"]["monthly_sample_cap"] == 100


def test_a_flagged_area_says_one_contributor_dominates() -> None:
    flagged = {**_area("docs", ABOVE), "author_concentration_flag": True}
    report = _report(areas=[flagged])
    entry = report["where_to_start"]["bands"][0]["areas"][0]
    assert entry["concentration_note"].startswith("The sample is dominated by one contributor")
    assert "30%" in entry["concentration_note"]
    assert _report()["where_to_start"]["bands"][0]["areas"][0]["concentration_note"] is None


def test_lead_response_measure_falls_back_when_formal_review_coverage_is_low() -> None:
    assert lead_response_measure(60, 100, 0.5) == FORMAL_REVIEW
    assert lead_response_measure(50, 100, 0.5) == FORMAL_REVIEW
    assert lead_response_measure(17, 100, 0.5) == HUMAN_RESPONSE
    assert lead_response_measure(0, 0, 0.5) == FORMAL_REVIEW
    low = _report(pr_counts=(17, 100, 0, 0))["where_to_start"]
    assert low["lead_response_measure"] == HUMAN_RESPONSE
    assert low["formal_review_coverage"] == 0.17


def test_a_stored_analysis_without_parameters_fails_clearly() -> None:
    import pytest

    with pytest.raises(OutdatedReport, match="analyse it again"):
        _report(repo={**REPO, "parameters": {}})


def test_nobody_is_called_a_maintainer_or_owner() -> None:
    text = str(_report()).lower()
    assert "maintainer" not in text
    assert "owner" not in text
