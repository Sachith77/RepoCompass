"""Tests for slug parsing, the GraphQL client and name resolution. No network: a mock transport."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from repocompass.github import (
    GitHubClient,
    GitHubError,
    RateLimitLow,
    parse_repo_slug,
    resolve_repository,
)

TOKEN = "fake-token-must-not-leak"


@pytest.mark.parametrize(
    "text",
    [
        "Kludex/starlette",
        "https://github.com/Kludex/starlette",
        "https://github.com/Kludex/starlette/",
        "https://github.com/Kludex/starlette.git",
        "github.com/Kludex/starlette",
        "  Kludex/starlette  ",
    ],
)
def test_parse_accepts_slugs_and_github_urls(text: str) -> None:
    assert parse_repo_slug(text) == ("Kludex", "starlette")


def test_parse_keeps_dots_and_dashes_in_names() -> None:
    assert parse_repo_slug("pydantic/pydantic-settings") == ("pydantic", "pydantic-settings")
    assert parse_repo_slug("org/.github") == ("org", ".github")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "starlette",
        "a/b/c",
        "https://gitlab.com/a/b",
        "owner/..",
        "../etc",
        "own er/repo",
        "-owner/repo",
        "owner/re;po",
    ],
)
def test_parse_rejects_anything_else(text: str) -> None:
    with pytest.raises(GitHubError):
        parse_repo_slug(text)


# --- the client -------------------------------------------------------------


def _client(
    responses: list[httpx.Response | Exception],
    seen: list[httpx.Request] | None = None,
    sleeps: list[float] | None = None,
) -> GitHubClient:
    """A client whose transport plays back `responses` in order."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    record: Callable[[float], None] = sleeps.append if sleeps is not None else lambda _s: None
    return GitHubClient(TOKEN, transport=httpx.MockTransport(handler), sleep=record)


def _ok(data: dict, remaining: int = 4000, cost: int = 1) -> httpx.Response:
    rate = {"cost": cost, "remaining": remaining, "resetAt": "2026-11-03T12:00:00Z"}
    return httpx.Response(200, json={"data": {**data, "rateLimit": rate}})


def test_query_sends_the_token_in_a_header_and_tracks_points() -> None:
    seen: list[httpx.Request] = []
    client = _client([_ok({"x": 1}, cost=2), _ok({"x": 2}, cost=3)], seen)
    assert client.query("query { x }")["x"] == 1
    client.query("query { x }")
    assert client.requests == 2
    assert client.points == 5
    assert client.remaining == 4000
    assert seen[0].headers["Authorization"] == f"bearer {TOKEN}"
    assert TOKEN not in seen[0].content.decode()


def test_query_refuses_mutations() -> None:
    with pytest.raises(GitHubError, match="read-only"):
        _client([]).query("mutation { addStar }")


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("server disconnected"),
        httpx.ReadTimeout("slow"),
        httpx.Response(502),
        httpx.Response(503),
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"}),
        httpx.Response(200, json={"errors": [{"message": "Something went wrong (timeout)"}]}),
    ],
)
def test_transient_failures_are_retried_with_backoff(failure: httpx.Response | Exception) -> None:
    sleeps: list[float] = []
    client = _client([failure, failure, _ok({"x": 1})], sleeps=sleeps)
    assert client.query("query { x }")["x"] == 1
    assert sleeps == [2, 4]


def test_retries_give_up_after_the_last_attempt_without_the_token() -> None:
    client = _client([httpx.ConnectError("refused")] * 5)
    with pytest.raises(GitHubError) as excinfo:
        client.query("query { x }")
    assert "ConnectError" in str(excinfo.value)
    assert TOKEN not in str(excinfo.value)


@pytest.mark.parametrize("status", [401, 404])
def test_permanent_http_errors_are_not_retried(status: int) -> None:
    sleeps: list[float] = []
    with pytest.raises(GitHubError, match=str(status)):
        _client([httpx.Response(status)], sleeps=sleeps).query("query { x }")
    assert sleeps == []


def test_graphql_errors_fail_loudly() -> None:
    payload = {"data": {"x": None}, "errors": [{"message": "Field 'y' doesn't exist"}]}
    with pytest.raises(GitHubError, match="doesn't exist"):
        _client([httpx.Response(200, json=payload)]).query("query { x }")


def test_not_found_fails_unless_the_caller_allows_it() -> None:
    payload = {"data": {"x": None}, "errors": [{"type": "NOT_FOUND", "message": "gone"}]}
    with pytest.raises(GitHubError, match="gone"):
        _client([httpx.Response(200, json=payload)]).query("query { x }")
    allowed = _client([httpx.Response(200, json=payload)])
    assert allowed.query("query { x }", allow_not_found=True) == {"x": None}


def test_a_non_json_response_is_retried() -> None:
    sleeps: list[float] = []
    client = _client(
        [httpx.Response(200, text="<html>bad gateway</html>"), _ok({"x": 1})], sleeps=sleeps
    )
    assert client.query("query { x }")["x"] == 1
    assert sleeps == [2]


def test_retry_after_is_respected_when_longer_than_the_backoff() -> None:
    sleeps: list[float] = []
    limited = httpx.Response(403, headers={"Retry-After": "60"}, json={"message": "slow down"})
    client = _client([limited, _ok({"x": 1})], sleeps=sleeps)
    client.query("query { x }")
    assert sleeps == [60]


def test_stops_before_the_rate_limit_runs_out() -> None:
    client = _client([_ok({"x": 1}, remaining=50)])
    client.query("query { x }")
    with pytest.raises(RateLimitLow, match="resets at 2026-11-03T12:00:00Z"):
        client.query("query { x }")


# --- resolving the canonical name -----------------------------------------


def _repo_payload(name: str = "Kludex/starlette", private: bool = False) -> dict:
    return {
        "repository": {
            "nameWithOwner": name,
            "isPrivate": private,
            "defaultBranchRef": {"name": "main"},
        }
    }


def test_resolve_follows_renames_and_keeps_the_requested_slug() -> None:
    seen: list[httpx.Request] = []
    info = resolve_repository(_client([_ok(_repo_payload())], seen), "encode", "starlette")
    assert info.requested_slug == "encode/starlette"
    assert info.canonical_slug == "Kludex/starlette"
    assert info.default_branch == "main"

    (request,) = seen
    body = json.loads(request.content)
    assert "mutation" not in body["query"].lower()
    assert body["variables"] == {"owner": "encode", "name": "starlette"}


def test_resolve_rejects_private_repositories() -> None:
    with pytest.raises(GitHubError, match="public"):
        resolve_repository(_client([_ok(_repo_payload(private=True))]), "a", "b")


def test_resolve_reports_a_missing_repository() -> None:
    payload = {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "x"}]}
    with pytest.raises(GitHubError, match="not found"):
        resolve_repository(_client([httpx.Response(200, json=payload)]), "a", "b")


def test_resolve_reports_an_empty_repository() -> None:
    payload = _repo_payload()
    payload["repository"]["defaultBranchRef"] = None
    with pytest.raises(GitHubError, match="default branch"):
        resolve_repository(_client([_ok(payload)]), "a", "b")


@pytest.mark.parametrize("status", [401, 403, 502])
def test_http_errors_never_echo_the_token(status: int) -> None:
    with pytest.raises(GitHubError) as excinfo:
        resolve_repository(_client([httpx.Response(status, json={})] * 5), "a", "b")
    assert TOKEN not in str(excinfo.value)
    assert str(status) in str(excinfo.value)
