"""Tests for the worker loop, with the queue and the analysis replaced by fakes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from repocompass import worker
from repocompass.config import load_settings
from repocompass.github import GitHubError

SETTINGS = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": "postgresql://u:p@h/d"})


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "jobs": [(1, "a/ok", {}), (2, "b/broken", {}), (3, "c/ok", {"git": {}})],
        "finished": [],
    }
    monkeypatch.setattr(worker, "requeue_interrupted", lambda url: 1)
    monkeypatch.setattr(
        worker, "claim_next_job", lambda url: state["jobs"].pop(0) if state["jobs"] else None
    )

    def finish(
        url: str, job_id: int, *, repo_id: int | None = None, error: str | None = None
    ) -> None:
        state["finished"].append((job_id, error))

    monkeypatch.setattr(worker, "finish_job", finish)
    monkeypatch.setattr(
        worker, "requeue_job", lambda url, job_id: state.setdefault("requeued", []).append(job_id)
    )
    monkeypatch.setattr(worker, "save_job_checkpoint", lambda *args: None)

    def analysis(settings, slug, client, *, checkpoint, save_checkpoint) -> SimpleNamespace:
        if slug == "b/broken":
            raise GitHubError("b/broken was not found")
        if slug == "x/bug":
            raise RuntimeError("postgresql://user:sup3r-s3cret@db.example.invalid/x")
        if slug == "x/stop":
            raise KeyboardInterrupt
        state.setdefault("checkpoints", []).append(checkpoint)
        repo = SimpleNamespace(canonical_slug=slug)
        return SimpleNamespace(git=SimpleNamespace(repo=repo), usage={"requests": 1, "points": 1})

    monkeypatch.setattr(worker, "run_analysis", analysis)
    monkeypatch.setattr(worker, "save_analysis", lambda settings, result: 10)
    return state


def test_once_runs_every_queued_job_and_one_failure_does_not_stop_the_rest(
    queue: dict[str, Any],
) -> None:
    lines: list[str] = []
    assert worker.work(SETTINGS, once=True, log=lines.append) == 3
    assert queue["finished"] == [(1, None), (2, "b/broken was not found"), (3, None)]
    assert lines[0] == "requeued 1 job(s) left running by an earlier worker"
    assert any("job 2: failed: b/broken was not found" in line for line in lines)


def test_a_claimed_job_resumes_from_its_checkpoint(queue: dict[str, Any]) -> None:
    worker.work(SETTINGS, once=True, log=lambda line: None)
    assert queue["checkpoints"] == [{}, {"git": {}}]


def test_an_unexpected_error_is_recorded_by_type_only(queue: dict[str, Any]) -> None:
    queue["jobs"] = [(4, "x/bug", {})]
    lines: list[str] = []
    worker.work(SETTINGS, once=True, log=lines.append)
    assert queue["finished"] == [(4, "unexpected RuntimeError")]
    assert not any("sup3r-s3cret" in line for line in lines)


def test_stopping_the_worker_puts_its_job_back_in_the_queue(queue: dict[str, Any]) -> None:
    queue["jobs"] = [(5, "x/stop", {})]
    with pytest.raises(KeyboardInterrupt):
        worker.work(SETTINGS, once=True, log=lambda line: None)
    assert queue["requeued"] == [5]
    assert queue["finished"] == []  # not marked failed


def test_an_idle_worker_picks_up_jobs_abandoned_while_it_was_running(
    queue: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    queue["jobs"] = []
    found = iter([0, 1, 0])  # at start: none; first idle check: one abandoned job

    def requeue(url: str) -> int:
        count = next(found)
        if count:
            queue["jobs"].append((6, "a/ok", {"git": {}}))
        return count

    monkeypatch.setattr(worker, "requeue_interrupted", requeue)

    def stop(seconds: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        worker.work(SETTINGS, sleep=stop, log=lambda line: None)
    assert queue["finished"] == [(6, None)]


def test_an_idle_worker_waits_instead_of_spinning(
    queue: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    queue["jobs"] = []
    monkeypatch.setattr(worker, "requeue_interrupted", lambda url: 0)
    sleeps: list[float] = []

    def stop_after_one_wait(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        worker.work(SETTINGS, sleep=stop_after_one_wait, log=lambda line: None)
    assert sleeps == [worker.IDLE_SECONDS]
