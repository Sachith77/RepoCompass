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

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set")

SLUG = "test-only/__save_integration__"
SNAPSHOT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _result(numbers: list[int]) -> AnalysisResult:
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
    records = [
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
