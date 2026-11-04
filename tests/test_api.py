"""Tests for the HTTP API, with its data functions replaced by fakes. No database, no network."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from repocompass import api
from repocompass.config import load_settings
from repocompass.db import DatabaseError

SECRET_URL = "postgresql://user:sup3r-s3cret@db.example.invalid/x"
SETTINGS = load_settings({"GITHUB_TOKEN": "fake-token", "DATABASE_URL": SECRET_URL})


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"enqueued": [], "known": {"a/b": "a/b"}}

    def load_report(settings: object, owner: str, name: str) -> dict[str, Any] | None:
        canonical = seen["known"].get(f"{owner}/{name}".lower())
        return None if canonical is None else {"repo": {"canonical_slug": canonical}}

    def enqueue(url: str, slug: str) -> tuple[int, str]:
        seen["enqueued"].append(slug)
        return 7, "queued"

    monkeypatch.setattr(api, "load_report", load_report)
    monkeypatch.setattr(api, "enqueue_job", enqueue)
    monkeypatch.setattr(api, "list_repos", lambda settings: [{"canonical_slug": "a/b"}])
    return seen


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.create_app(SETTINGS))


@pytest.mark.parametrize(
    "url", ["not a url", "https://gitlab.com/a/b", "https://github.com/a", "../etc/passwd"]
)
def test_analyze_rejects_anything_but_a_github_repository(
    client: TestClient, calls: dict[str, Any], url: str
) -> None:
    response = client.post("/analyze", json={"repo_url": url})
    assert response.status_code == 422
    assert calls["enqueued"] == []


def test_analyze_returns_the_stored_report_when_there_is_one(
    client: TestClient, calls: dict[str, Any]
) -> None:
    calls["known"]["encode/starlette"] = "Kludex/starlette"
    response = client.post("/analyze", json={"repo_url": "https://github.com/encode/starlette"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "cached",
        "report_url": "/repos/Kludex/starlette/report",
        "report": {"repo": {"canonical_slug": "Kludex/starlette"}},
    }
    assert calls["enqueued"] == []


def test_analyze_queues_a_job_otherwise(client: TestClient, calls: dict[str, Any]) -> None:
    response = client.post("/analyze", json={"repo_url": "https://github.com/optuna/optuna"})
    assert response.status_code == 202
    assert response.json() == {
        "status": "queued",
        "requested_slug": "optuna/optuna",
        "job_id": 7,
        "job_url": "/jobs/7",
    }
    assert calls["enqueued"] == ["optuna/optuna"]


def test_repos_lists_analysed_repositories(client: TestClient, calls: dict[str, Any]) -> None:
    assert client.get("/repos").json() == {"repos": [{"canonical_slug": "a/b"}]}


def test_report_is_404_until_a_repository_is_analysed(
    client: TestClient, calls: dict[str, Any]
) -> None:
    assert client.get("/repos/a/b/report").status_code == 200
    assert client.get("/repos/a/c/report").status_code == 404
    assert client.get("/repos/-bad/name/report").status_code == 404


def _job(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": 3,
        "requested_slug": "encode/starlette",
        "state": "running",
        "stage": "prs",
        "progress": 40,
        "attempts": 1,
        "last_error": None,
        "created_at": None,
        "updated_at": None,
        "canonical_slug": None,
        "checkpoint_slug": "Kludex/starlette",
        "areas_preview": [
            {
                "area": "docs",
                "commits_recent": 2,
                "commits_window": 9,
                "authors_window": 3,
                "band": "active",
            }
        ],
    }
    return {**base, **overrides}


def test_a_running_job_shows_the_areas_map_from_its_checkpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "get_job", lambda url, job_id: _job())
    body = client.get("/jobs/3").json()
    assert body["progress"] == 40
    assert body["report_url"] is None
    assert body["areas_map"] == [
        {
            "area": "docs",
            "commits_90d": 2,
            "commits_12mo": 9,
            "commit_authors_12mo": 3,
            "activity_band": "active",
        }
    ]


def test_a_finished_job_links_its_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    done = _job(state="done", canonical_slug="Kludex/starlette")
    monkeypatch.setattr(api, "get_job", lambda url, job_id: done)
    body = client.get("/jobs/3").json()
    assert body["report_url"] == "/repos/Kludex/starlette/report"
    assert body["areas_map"] is None


def test_an_unknown_job_is_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "get_job", lambda url, job_id: None)
    assert client.get("/jobs/99").status_code == 404
    assert client.get("/jobs/not-a-number").status_code == 422


def test_an_outdated_stored_report_is_409_and_post_analyses_it_again(
    client: TestClient, calls: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from repocompass.report import OutdatedReport

    def outdated(settings: object, owner: str, name: str) -> None:
        raise OutdatedReport("the stored analysis of a/b has no parameters; analyse it again")

    monkeypatch.setattr(api, "load_report", outdated)
    response = client.get("/repos/a/b/report")
    assert response.status_code == 409
    assert "analyse it again" in response.json()["detail"]
    assert client.post("/analyze", json={"repo_url": "a/b"}).status_code == 202
    assert calls["enqueued"] == ["a/b"]


def test_the_api_module_imports_nothing_that_talks_to_github() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(api))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported & {"GitHubClient", "resolve_repository", "run_analysis", "run_job"} == set()
    assert "repocompass.worker" not in modules
    assert "repocompass.analysis" not in modules
    assert "httpx" not in modules


def test_the_api_never_calls_github(
    client: TestClient, calls: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import repocompass.github as github

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("the API must not talk to GitHub")

    monkeypatch.setattr(github, "GitHubClient", no_network)
    monkeypatch.setattr(github, "resolve_repository", no_network)
    monkeypatch.setattr(api, "get_job", lambda url, job_id: _job())
    assert client.post("/analyze", json={"repo_url": "a/new"}).status_code == 202
    assert client.post("/analyze", json={"repo_url": "a/b"}).status_code == 200
    assert client.get("/repos").status_code == 200
    assert client.get("/repos/a/b/report").status_code == 200
    assert client.get("/jobs/3").status_code == 200


def test_a_database_failure_is_503_and_leaks_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(settings: object) -> list[dict[str, Any]]:
        raise DatabaseError("could not connect: <redacted>")

    monkeypatch.setattr(api, "list_repos", down)
    response = client.get("/repos")
    assert response.status_code == 503
    assert "sup3r-s3cret" not in response.text
    assert "db.example.invalid" not in response.text


def test_cors_allows_only_the_local_web_origin(client: TestClient, calls: dict[str, Any]) -> None:
    allowed = client.get("/repos", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = client.get("/repos", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    preflight = client.options(
        "/analyze",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
