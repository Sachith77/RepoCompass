"""The jobs table: the queue, and where an analysis keeps its stage, progress and checkpoint.

ADR-0005: one worker claims queued jobs with `FOR UPDATE SKIP LOCKED`, so even if a
second worker were started, two workers could never take the same job. The
checkpoint holds everything fetched so far (see analysis.py), so a failed or
interrupted job is resumed rather than restarted.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from repocompass.db import connect

__all__ = [
    "claim_next_job",
    "create_job",
    "enqueue_job",
    "finish_job",
    "get_job",
    "load_job",
    "requeue_interrupted",
    "requeue_job",
    "save_job_checkpoint",
]

# Error text stored on a job is cut to this length; it never holds secrets because
# every error raised by this package is already scrubbed of tokens and DSNs.
MAX_ERROR_LENGTH = 500
# A running job saves a checkpoint after every PR page and lookback request, which
# takes seconds; even a request retried with GitHub's Retry-After waits only minutes.
# A job with no checkpoint for this long was left behind by a process that died.
STALE_RUNNING_MINUTES = 10
# A failed job is resumed from its checkpoint only if its data (the snapshot taken in
# the git stage) is this recent; older data would bring back a stale report.
RESUME_WITHIN_HOURS = 24

CLAIM_SQL = """
UPDATE jobs SET state = 'running', attempts = attempts + 1, last_error = NULL, updated_at = now()
 WHERE id = (SELECT id FROM jobs WHERE state = 'queued'
              ORDER BY created_at, id
              FOR UPDATE SKIP LOCKED
              LIMIT 1)
RETURNING id, requested_slug, checkpoint
"""


def create_job(database_url: str, requested_slug: str) -> int:
    """A job the caller runs at once (the `analyze` command), so it starts as running."""
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (requested_slug, state, stage, attempts)"
            " VALUES (%s, 'running', 'git', 1) RETURNING id",
            (requested_slug,),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING always yields a row
            raise RuntimeError("jobs insert returned no id")
        return int(row[0])


def enqueue_job(database_url: str, requested_slug: str) -> tuple[int, str]:
    """Queue an analysis for the worker, never twice for the same requested name.

    A queued or running job for the same requested name is returned as it is; a failed
    job whose snapshot is within RESUME_WITHIN_HOURS is queued again with its checkpoint;
    otherwise a new job is created. An advisory lock on the name makes two
    simultaneous requests agree on one job (a hash collision only makes one request
    wait for an unrelated one; it cannot merge two jobs).
    """
    key = requested_slug.lower()
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))
        cur.execute(
            "SELECT id, state, coalesce((checkpoint #>> '{git,snapshot}')::timestamptz, now())"
            " > now() - make_interval(hours => %s) FROM jobs"
            " WHERE lower(requested_slug) = %s AND state IN ('queued', 'running', 'failed')"
            " ORDER BY created_at DESC LIMIT 1",
            (RESUME_WITHIN_HOURS, key),
        )
        row = cur.fetchone()
        if row is not None and row[1] in ("queued", "running"):
            return int(row[0]), row[1]
        if row is not None and row[2]:  # failed, data still recent: resume it
            cur.execute(
                "UPDATE jobs SET state = 'queued', updated_at = now() WHERE id = %s", (row[0],)
            )
            return int(row[0]), "queued"
        cur.execute("INSERT INTO jobs (requested_slug) VALUES (%s) RETURNING id", (requested_slug,))
        new = cur.fetchone()
        if new is None:  # pragma: no cover - RETURNING always yields a row
            raise RuntimeError("jobs insert returned no id")
        return int(new[0]), "queued"


def claim_next_job(database_url: str) -> tuple[int, str, dict[str, Any]] | None:
    """Take the oldest queued job, or None when the queue is empty."""
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(CLAIM_SQL)
        row = cur.fetchone()
    return None if row is None else (int(row[0]), row[1], row[2])


def requeue_interrupted(database_url: str) -> int:
    """At worker start: jobs left 'running' by a process that died go back in the queue.

    Only jobs with no checkpoint for STALE_RUNNING_MINUTES count as abandoned, so a
    job that `analyze` is running at the command line right now is left alone.
    """
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET state = 'queued', updated_at = now() WHERE state = 'running'"
            " AND updated_at < now() - make_interval(mins => %s)",
            (STALE_RUNNING_MINUTES,),
        )
        return cur.rowcount


def requeue_job(database_url: str, job_id: int) -> None:
    """Put a job the worker was stopped in the middle of back in the queue.

    Only while it is still running: a job that finished just before the stop stays done.
    """
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET state = 'queued', updated_at = now()"
            " WHERE id = %s AND state = 'running'",
            (job_id,),
        )


def load_job(database_url: str, job_id: int) -> tuple[str, dict[str, Any]]:
    """Take a queued or failed job to run here: its requested slug and checkpoint.

    A running or finished job is refused, so a job can never run twice at once.
    """
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET state = 'running', attempts = attempts + 1, updated_at = now()"
            " WHERE id = %s AND state IN ('queued', 'failed') RETURNING requested_slug, checkpoint",
            (job_id,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT state FROM jobs WHERE id = %s", (job_id,))
            found = cur.fetchone()
    if row is not None:
        return row[0], row[1]
    if found is None:
        raise LookupError(f"job {job_id} does not exist")
    raise LookupError(f"job {job_id} is {found[0]}; only queued or failed jobs can be resumed")


def get_job(database_url: str, job_id: int) -> dict[str, Any] | None:
    """A job's progress, plus the areas map from its checkpoint once the git stage is done.

    Only the activity part of the checkpoint is read, not the whole (possibly large)
    blob, so polling stays cheap.
    """
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT j.id, j.requested_slug, j.state, j.stage, j.progress, j.attempts,"
            " j.last_error, j.created_at, j.updated_at, r.canonical_slug,"
            " j.checkpoint #> '{git,activity,areas}', j.checkpoint #>> '{git,repo,canonical_slug}'"
            " FROM jobs j LEFT JOIN repos r ON r.id = j.repo_id WHERE j.id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    keys = (
        "id", "requested_slug", "state", "stage", "progress", "attempts", "last_error",
        "created_at", "updated_at", "canonical_slug", "areas_preview", "checkpoint_slug",
    )  # fmt: skip
    return dict(zip(keys, row, strict=True))


def save_job_checkpoint(
    database_url: str, job_id: int, stage: str, progress: int, checkpoint: dict[str, Any]
) -> None:
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET stage = %s, progress = %s, checkpoint = %s, updated_at = now()"
            " WHERE id = %s",
            (stage, progress, Jsonb(checkpoint), job_id),
        )


def finish_job(
    database_url: str, job_id: int, *, repo_id: int | None = None, error: str | None = None
) -> None:
    """Mark a job done (with its repo) or failed (with a short error)."""
    with connect(database_url) as conn, conn.cursor() as cur:
        if error is None:
            cur.execute(
                "UPDATE jobs SET state = 'done', stage = 'done', progress = 100, repo_id = %s,"
                " last_error = NULL, updated_at = now() WHERE id = %s",
                (repo_id, job_id),
            )
        else:
            cur.execute(
                "UPDATE jobs SET state = 'failed', last_error = %s, updated_at = now()"
                " WHERE id = %s",
                (error[:MAX_ERROR_LENGTH], job_id),
            )
