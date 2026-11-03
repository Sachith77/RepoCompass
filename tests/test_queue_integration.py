"""Integration tests for the jobs queue against a real Postgres.

Skipped unless TEST_DATABASE_URL is set. Each test uses its own made-up slugs and
removes its jobs afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from repocompass.db import apply_schema, connect
from repocompass.jobs import (
    CLAIM_SQL,
    RESUME_WITHIN_HOURS,
    STALE_RUNNING_MINUTES,
    claim_next_job,
    enqueue_job,
    finish_job,
    get_job,
    load_job,
    requeue_interrupted,
    requeue_job,
    save_job_checkpoint,
)

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set")
PREFIX = "test-only-queue/"


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    apply_schema(DATABASE_URL)

    def wipe() -> None:
        with connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE requested_slug LIKE %s", (PREFIX + "%",))

    wipe()
    # these tests claim and requeue jobs, so they must never touch someone else's work
    with connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM jobs WHERE state IN ('queued', 'running')")
        row = cur.fetchone()
    if row and row[0]:
        pytest.skip("the database has queued or running jobs; run against an idle database")
    yield
    wipe()


def test_enqueue_never_creates_a_second_job_for_the_same_repository() -> None:
    first, state = enqueue_job(DATABASE_URL, PREFIX + "a")
    again, again_state = enqueue_job(DATABASE_URL, (PREFIX + "A").upper())
    assert (again, again_state) == (first, "queued")
    assert state == "queued"


def test_a_failed_job_is_queued_again_and_keeps_its_checkpoint() -> None:
    job_id, _ = enqueue_job(DATABASE_URL, PREFIX + "b")
    claimed = claim_next_job(DATABASE_URL)
    assert claimed is not None and claimed[0] == job_id
    save_job_checkpoint(DATABASE_URL, job_id, "prs", 40, {"git": {"done": True}})
    finish_job(DATABASE_URL, job_id, error="rate limit")

    again, state = enqueue_job(DATABASE_URL, PREFIX + "b")
    assert (again, state) == (job_id, "queued")
    claimed = claim_next_job(DATABASE_URL)
    assert claimed == (job_id, PREFIX + "b", {"git": {"done": True}})


def test_claims_take_the_oldest_job_and_skip_one_another_holds() -> None:
    older, _ = enqueue_job(DATABASE_URL, PREFIX + "c1")
    newer, _ = enqueue_job(DATABASE_URL, PREFIX + "c2")
    # another worker is in the middle of claiming the older job and has not committed yet
    with connect(DATABASE_URL) as other, other.cursor() as cur:
        cur.execute("SELECT id FROM jobs WHERE id = %s FOR UPDATE SKIP LOCKED", (older,))
        claimed = claim_next_job(DATABASE_URL)
        assert claimed is not None and claimed[0] == newer
    released = claim_next_job(DATABASE_URL)  # the older one, once released
    assert released is not None and released[0] == older
    assert claim_next_job(DATABASE_URL) is None
    assert "SKIP LOCKED" in CLAIM_SQL


def test_jobs_left_running_go_back_to_the_queue_and_progress_shows_the_areas_map() -> None:
    job_id, _ = enqueue_job(DATABASE_URL, PREFIX + "d")
    claim_next_job(DATABASE_URL)
    areas = [{"area": "docs", "commits_recent": 1, "commits_window": 2, "authors_window": 1}]
    checkpoint = {"git": {"repo": {"canonical_slug": "X/d"}, "activity": {"areas": areas}}}
    save_job_checkpoint(DATABASE_URL, job_id, "prs", 30, checkpoint)

    job = get_job(DATABASE_URL, job_id)
    assert job is not None
    assert (job["state"], job["progress"], job["checkpoint_slug"]) == ("running", 30, "X/d")
    assert job["areas_preview"] == areas

    # still checkpointing: another process is working on it, so it is left alone
    assert requeue_interrupted(DATABASE_URL) == 0
    _age(job_id, minutes=STALE_RUNNING_MINUTES + 1)
    assert requeue_interrupted(DATABASE_URL) == 1
    job = get_job(DATABASE_URL, job_id)
    assert job is not None and job["state"] == "queued"


def test_resume_refuses_a_job_that_is_running_or_done() -> None:
    job_id, _ = enqueue_job(DATABASE_URL, PREFIX + "e")
    claim_next_job(DATABASE_URL)
    with pytest.raises(LookupError, match="running"):
        load_job(DATABASE_URL, job_id)
    finish_job(DATABASE_URL, job_id, error="boom")
    assert load_job(DATABASE_URL, job_id) == (PREFIX + "e", {})
    finish_job(DATABASE_URL, job_id, repo_id=None)
    with pytest.raises(LookupError, match="done"):
        load_job(DATABASE_URL, job_id)


def test_a_failed_job_with_old_data_is_not_resumed_a_new_job_starts() -> None:
    from datetime import UTC, datetime, timedelta

    job_id, _ = enqueue_job(DATABASE_URL, PREFIX + "f")
    claim_next_job(DATABASE_URL)
    old = (datetime.now(UTC) - timedelta(hours=RESUME_WITHIN_HOURS + 1)).isoformat()
    save_job_checkpoint(DATABASE_URL, job_id, "prs", 40, {"git": {"snapshot": old}})
    finish_job(DATABASE_URL, job_id, error="rate limit")  # failed just now, but data is old
    again, state = enqueue_job(DATABASE_URL, PREFIX + "f")
    assert state == "queued"
    assert again != job_id


def test_requeue_job_leaves_a_finished_job_alone() -> None:
    job_id, _ = enqueue_job(DATABASE_URL, PREFIX + "g")
    claim_next_job(DATABASE_URL)
    finish_job(DATABASE_URL, job_id, repo_id=None)
    requeue_job(DATABASE_URL, job_id)
    job = get_job(DATABASE_URL, job_id)
    assert job is not None and job["state"] == "done"


def _age(job_id: int, *, minutes: int) -> None:
    with connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET updated_at = now() - make_interval(mins => %s) WHERE id = %s",
            (minutes, job_id),
        )
