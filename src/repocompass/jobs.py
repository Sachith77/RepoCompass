"""The jobs table: where an analysis keeps its stage, progress and checkpoint.

A job is created per analysis. The checkpoint holds everything fetched so far (see
analysis.py), so a failed or interrupted job can be resumed from where it stopped.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from repocompass.db import connect

__all__ = ["create_job", "finish_job", "load_job", "save_job_checkpoint"]

# Error text stored on a job is cut to this length; it never holds secrets because
# every error raised by this package is already scrubbed of tokens and DSNs.
MAX_ERROR_LENGTH = 500


def create_job(database_url: str, requested_slug: str) -> int:
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (requested_slug, state, stage) VALUES (%s, 'running', 'git')"
            " RETURNING id",
            (requested_slug,),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING always yields a row
            raise RuntimeError("jobs insert returned no id")
        return int(row[0])


def load_job(database_url: str, job_id: int) -> tuple[str, dict[str, Any]]:
    """The requested slug and checkpoint of a job, and mark it running again."""
    with connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET state = 'running', attempts = attempts + 1, updated_at = now()"
            " WHERE id = %s RETURNING requested_slug, checkpoint",
            (job_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"job {job_id} does not exist")
    return row[0], row[1]


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
