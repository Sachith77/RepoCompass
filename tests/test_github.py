"""Tests for slug parsing and canonical name resolution. No network: a mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from repocompass.github import GitHubError, parse_repo_slug, resolve_repository

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


def _transport(status: int, payload: dict, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def _repo_payload(name: str = "Kludex/starlette", private: bool = False) -> dict:
    return {
        "data": {
            "repository": {
                "nameWithOwner": name,
                "isPrivate": private,
                "defaultBranchRef": {"name": "main"},
            }
        }
    }


def test_resolve_follows_renames_and_keeps_the_requested_slug() -> None:
    seen: list[httpx.Request] = []
    info = resolve_repository(
        TOKEN, "encode", "starlette", transport=_transport(200, _repo_payload(), seen)
    )
    assert info.requested_slug == "encode/starlette"
    assert info.canonical_slug == "Kludex/starlette"
    assert info.default_branch == "main"

    (request,) = seen
    assert request.method == "POST"
    body = json.loads(request.content)
    assert "mutation" not in body["query"].lower()
    assert body["variables"] == {"owner": "encode", "name": "starlette"}


def test_resolve_rejects_private_repositories() -> None:
    with pytest.raises(GitHubError, match="public"):
        resolve_repository(
            TOKEN, "a", "b", transport=_transport(200, _repo_payload(private=True), [])
        )


def test_resolve_reports_a_missing_repository() -> None:
    payload = {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND"}]}
    with pytest.raises(GitHubError, match="not found"):
        resolve_repository(TOKEN, "a", "b", transport=_transport(200, payload, []))


def test_resolve_reports_an_empty_repository() -> None:
    payload = _repo_payload()
    payload["data"]["repository"]["defaultBranchRef"] = None
    with pytest.raises(GitHubError, match="default branch"):
        resolve_repository(TOKEN, "a", "b", transport=_transport(200, payload, []))


@pytest.mark.parametrize("status", [401, 403, 502])
def test_http_errors_never_echo_the_token(status: int) -> None:
    with pytest.raises(GitHubError) as excinfo:
        resolve_repository(TOKEN, "a", "b", transport=_transport(status, {}, []))
    assert TOKEN not in str(excinfo.value)
    assert str(status) in str(excinfo.value)


def test_transport_failure_never_echoes_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(GitHubError) as excinfo:
        resolve_repository(TOKEN, "a", "b", transport=httpx.MockTransport(handler))
    assert TOKEN not in str(excinfo.value)
