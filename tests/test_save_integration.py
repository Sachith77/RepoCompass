"""Integration test for the single-transaction save, against a real Postgres.

Skipped unless TEST_DATABASE_URL is set, because CI has no database. It writes one
repository under a name no real repository can have, and deletes it afterwards.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from repocompass.activity import ActivitySummary, AreaActivity
from repocompass.analysis import AnalysisResult, save_analysis
from repocompass.config import load_settings
from repocompass.db import apply_schema, connect
from repocompass.github import RepoInfo
from repocompass.ingest_git import GitIngestResult
from repocompass.metrics import area_stats, repo_rate, sample_note
from repocompass.prs import new_fetch_state
from repocompass.records import PrRecord
from repocompass.report import load_report

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set")

SLUG = "test-only/__save_integration__"
SNAPSHOT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _result(numbers: list[int], records: list[PrRecord] | None = None) -> AnalysisResult:
    settings = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": DATABASE_URL})
    git = GitIngestResult(
        repo=RepoInfo(SLUG, SLUG, "main"),
        snapshot=SNAPSHOT,
        files_considered=2,
        depths={},
        activity=ActivitySummary(
            areas=(AreaActivity("docs", 1, 1, 1, "active"),),
            commits_in_window=1,
            bot_commits=0,
            sweep_commits=0,
            counted_commits=1,
        ),
        seconds={},
    )
    created = SNAPSHOT - timedelta(days=60)
    records = (
        [
            PrRecord(
                number=n,
                author=f"user{n}",
                association="NONE",
                created_at=created,
                merged_at=created,
                closed_at=created,
                state="MERGED",
                merged=True,
                changed_files=1,
                files_complete=True,
                area_files={"docs": 1},
                first_formal_review_at=None,
                first_human_response_at=None,
                response_times_complete=True,
                reviewers=("grace",),
                is_newcomer=True,
            )
            for n in numbers
        ]
        if records is None
        else records
    )
    rate, n = repo_rate(records, SNAPSHOT, settings)
    fetch = new_fetch_state()
    fetch["month_totals"] = fetch["month_sampled"] = {"2026-09": len(records)}
    return AnalysisResult(
        git=git,
        records=records,
        stats=area_stats(records, ["docs"], SNAPSHOT, settings, rate),
        note=sample_note(fetch),
        repo_rate=rate,
        repo_mature_newcomer_prs=n,
        usage={"requests": 0, "points": 0, "seconds": {}},
    )


def _counts() -> tuple[int, int, int]:
    with connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM prs p WHERE p.repo_id = r.id),"
            " (SELECT count(*) FROM pr_areas a WHERE a.repo_id = r.id),"
            " (SELECT count(*) FROM area_stats s WHERE s.repo_id = r.id)"
            " FROM repos r WHERE r.canonical_slug = %s",
            (SLUG,),
        )
        row = cur.fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def test_a_second_save_replaces_every_row_instead_of_adding() -> None:
    apply_schema(DATABASE_URL)
    settings = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": DATABASE_URL})
    try:
        first = save_analysis(settings, _result([1, 2, 3]))
        assert _counts() == (3, 3, 1)
        second = save_analysis(settings, _result([2, 3]))  # PR 1 left the window
        assert second == first
        assert _counts() == (2, 2, 1)
    finally:
        with connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM repos WHERE canonical_slug = %s", (SLUG,))


def test_a_failing_save_leaves_the_previous_rows_untouched() -> None:
    apply_schema(DATABASE_URL)
    settings = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": DATABASE_URL})
    try:
        save_analysis(settings, _result([1, 2]))
        broken = _result([1, 1])  # a duplicate PR number breaks the primary key mid-save
        with pytest.raises(Exception):  # noqa: B017 - any database error will do
            save_analysis(settings, broken)
        assert _counts() == (2, 2, 1)
    finally:
        with connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM repos WHERE canonical_slug = %s", (SLUG,))


def _pr(
    number: int,
    *,
    days_ago: int = 60,
    state: str = "MERGED",
    newcomer: bool = True,
    complete: bool = True,
    known: bool = True,
    review_h: float | None = None,
    response_h: float | None = None,
) -> PrRecord:
    created = SNAPSHOT - timedelta(days=days_ago)

    def at(h: float | None) -> datetime | None:
        return None if h is None else created + timedelta(hours=h)

    return PrRecord(
        number=number,
        author=f"user{number}",
        association="NONE",
        created_at=created,
        merged_at=created if state == "MERGED" else None,
        closed_at=created if state != "OPEN" else None,
        state=state,
        merged=state == "MERGED",
        changed_files=1,
        files_complete=complete,
        area_files={"docs": 1},
        first_formal_review_at=at(review_h),
        first_human_response_at=at(response_h),
        response_times_complete=known,
        reviewers=(),
        is_newcomer=newcomer,
    )


def test_repo_wide_response_figures_match_the_metrics_rules() -> None:
    """The SQL in report.py must count exactly the PRs metrics.py counts for one area."""
    records = [
        _pr(1, review_h=10, response_h=5),
        _pr(2, state="CLOSED", review_h=30, response_h=30),
        _pr(3),  # never answered
        _pr(4, response_h=24 * 40),  # answered, but after 30 days
        _pr(5, newcomer=False, review_h=1, response_h=1),  # not a newcomer: left out
        _pr(6, complete=False, review_h=2, response_h=2),  # incomplete files: left out
        _pr(7, known=False),  # unknown response times: left out
        _pr(8, state="OPEN", response_h=3),  # in the medians, not in the no-response share
        _pr(9, days_ago=10, response_h=4),  # too young for the no-response share
        _pr(10, response_h=24 * 30),  # answered exactly at 30 days: that counts as a response
    ]
    apply_schema(DATABASE_URL)
    settings = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": DATABASE_URL})
    result = _result([], records)
    try:
        save_analysis(settings, result)
        report = load_report(settings, *SLUG.split("/"))
        assert report is not None
        where = report["where_to_start"]
        (docs,) = result.stats  # every record is in the one area, so it is the whole repo
        assert where["repo_median_hours_first_formal_review"] == pytest.approx(
            docs.median_hours_first_formal_review
        )
        assert where["repo_formal_review_prs"] == docs.formal_review_prs == 2
        assert where["repo_median_hours_first_human_response"] == pytest.approx(
            docs.median_hours_first_human_response
        )
        assert where["repo_human_response_prs"] == docs.human_response_prs == 6
        assert where["repo_no_response_share"] == pytest.approx(docs.no_response_share)
        assert where["repo_no_response_base_prs"] == docs.no_response_base_prs == 5
        assert (
            where["repo_median_hours_first_formal_review"],
            where["repo_no_response_share"],
        ) == (
            pytest.approx(20.0),
            pytest.approx(2 / 5),
        )
    finally:
        with connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM repos WHERE canonical_slug = %s", (SLUG,))
