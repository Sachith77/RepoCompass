"""The worker: claim queued jobs one at a time and run each to the end (ADR-0005).

All network work happens here; the API only reads Postgres and queues jobs. The
`analyze` command uses the same `run_job`, so a job behaves identically whether the
worker or a developer at the command line runs it.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import Any

from repocompass.analysis import AnalysisResult, run_analysis, save_analysis
from repocompass.config import Settings
from repocompass.db import DatabaseError
from repocompass.gitclone import GitError
from repocompass.github import GitHubClient, GitHubError
from repocompass.jobs import (
    claim_next_job,
    finish_job,
    requeue_interrupted,
    requeue_job,
    save_job_checkpoint,
)

__all__ = ["EXPECTED_ERRORS", "JobFailed", "run_job", "work"]

# Failures reported as a message; their text never holds a secret.
EXPECTED_ERRORS = (GitHubError, GitError, DatabaseError)
IDLE_SECONDS = 2.0


class JobFailed(RuntimeError):
    """A job ended with an expected error, already recorded on the job row."""


def _fail(settings: Settings, job_id: int, error: str) -> None:
    # if the database is down too, the original failure is still what gets reported
    with contextlib.suppress(DatabaseError):
        finish_job(settings.database_url, job_id, error=error)


def run_job(
    settings: Settings, job_id: int, slug: str, checkpoint: dict[str, Any]
) -> AnalysisResult:
    """Run one job, resuming from its checkpoint, and record how it ended.

    Ctrl+C is left to the caller: the worker puts the job back in the queue, the
    `analyze` command marks it failed and prints how to resume it.
    """

    def save(stage: str, progress: int, state: dict[str, Any]) -> None:
        save_job_checkpoint(settings.database_url, job_id, stage, progress, state)

    try:
        with GitHubClient(settings.github_token) as client:
            result = run_analysis(
                settings, slug, client, checkpoint=checkpoint, save_checkpoint=save
            )
        repo_id = save_analysis(settings, result)
    except EXPECTED_ERRORS as exc:
        _fail(settings, job_id, str(exc))
        raise JobFailed(str(exc)) from None
    # Ctrl+C is not an Exception, so it passes through to the caller untouched
    except Exception as exc:  # an unexpected bug: record only its type, never its text
        _fail(settings, job_id, f"unexpected {type(exc).__name__}")
        raise
    finish_job(settings.database_url, job_id, repo_id=repo_id)
    return result


def work(
    settings: Settings,
    *,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> int:
    """Claim and run jobs until stopped (or, with `once`, until the queue is empty).

    Returns how many jobs were processed. One failing job never stops the worker.
    """
    requeued = requeue_interrupted(settings.database_url)
    if requeued:
        log(f"requeued {requeued} job(s) left running by an earlier worker")
    processed = 0
    while True:
        claimed = claim_next_job(settings.database_url)
        if claimed is None:
            if once:
                return processed
            # a job whose process died while this worker was already up is picked up here
            if requeue_interrupted(settings.database_url):
                continue
            sleep(IDLE_SECONDS)
            continue
        job_id, slug, checkpoint = claimed
        log(f"job {job_id}: {slug} started")
        start = time.perf_counter()
        try:
            result = run_job(settings, job_id, slug, checkpoint)
        except KeyboardInterrupt:
            requeue_job(settings.database_url, job_id)  # the next start resumes it
            log(f"job {job_id}: stopped; back in the queue")
            raise
        except JobFailed as exc:
            log(f"job {job_id}: failed: {exc}")
        except Exception as exc:  # already recorded on the job; keep serving the queue
            log(f"job {job_id}: failed unexpectedly ({type(exc).__name__})")
        else:
            usage = result.usage
            log(
                f"job {job_id}: {result.git.repo.canonical_slug} done in "
                f"{time.perf_counter() - start:.1f} s; "
                f"{usage['requests']} requests, {usage['points']} points"
            )
        processed += 1
