"""Read-only GitHub access: slugs, one GraphQL client, and the canonical-name lookup.

The canonical name must be resolved before anything else. `repository(owner, name)`
follows renames, but GitHub search is keyed on the current name, so a renamed
repository (encode/starlette is now Kludex/starlette) would otherwise look empty.

The client sends queries only. The token goes in a header and never appears in an
error message. Long paginated runs get dropped connections, so every transport
error (httpx.TransportError covers connect, read, timeout and "server disconnected")
is retried with exponential backoff, as are 502/503/504 and secondary rate limits.
Each query asks for `rateLimit`, and the client stops cleanly before the hourly
budget runs out instead of failing halfway through a page.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

__all__ = [
    "RATE_LIMIT_FIELDS",
    "GitHubClient",
    "GitHubError",
    "RateLimitLow",
    "RepoInfo",
    "parse_repo_slug",
    "resolve_repository",
]

ENDPOINT = "https://api.github.com/graphql"
TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 5
# A safety margin of points kept unused, so a run stops before the budget is gone.
# A chosen margin, not a measured value: one PR page costs 1-2 points.
RATE_LIMIT_RESERVE = 100
RETRY_STATUSES = {502, 503, 504}
RATE_LIMIT_FIELDS = "rateLimit { cost remaining resetAt }"

# GitHub's own limits: owners are letters, digits and inner dashes (max 39);
# repository names are letters, digits, '.', '_' and '-' (max 100).
SLUG_RE = re.compile(r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<name>[A-Za-z0-9._-]{1,100})")
URL_PREFIXES = ("https://github.com/", "http://github.com/", "github.com/")

RESOLVE_QUERY = f"""
query ($owner: String!, $name: String!) {{
  {RATE_LIMIT_FIELDS}
  repository(owner: $owner, name: $name) {{
    nameWithOwner
    isPrivate
    defaultBranchRef {{ name }}
  }}
}}
"""


class GitHubError(RuntimeError):
    """A GitHub failure, with no token in the message."""


class RateLimitLow(GitHubError):
    """The hourly point budget is nearly used up; resume after it resets."""


class _Retry(Exception):
    """Internal: this attempt failed in a way worth trying again."""

    def __init__(self, reason: str, wait: float = 0.0) -> None:
        super().__init__(reason)
        self.wait = wait  # seconds GitHub asked us to wait, if it said


@dataclass(frozen=True)
class RepoInfo:
    requested_slug: str
    canonical_slug: str
    default_branch: str


def parse_repo_slug(text: str) -> tuple[str, str]:
    """Accept `owner/repo` or a github.com URL to it; reject everything else."""
    slug = text.strip()
    for prefix in URL_PREFIXES:
        if slug.lower().startswith(prefix):
            slug = slug[len(prefix) :]
            break
    slug = slug.removesuffix("/").removesuffix(".git")
    match = SLUG_RE.fullmatch(slug)
    if not match or match["name"] in {".", ".."}:
        raise GitHubError("expected owner/repo or https://github.com/owner/repo")
    return match["owner"], match["name"]


def _is_secondary_limit(response: httpx.Response) -> bool:
    if response.status_code not in (403, 429):
        return False
    return "retry-after" in response.headers or "secondary rate limit" in response.text.lower()


def _retry_after(response: httpx.Response) -> float:
    value = response.headers.get("retry-after", "")
    return float(value) if value.isdigit() else 0.0


class GitHubClient:
    """One GraphQL client per analysis. Counts requests and points as it goes."""

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        headers = {"Authorization": f"bearer {token}", "User-Agent": "repocompass"}
        self._http = httpx.Client(transport=transport, timeout=TIMEOUT_SECONDS, headers=headers)
        self._sleep = sleep
        self.requests = 0
        self.points = 0
        self.remaining: int | None = None
        self.reset_at: str | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        allow_not_found: bool = False,
    ) -> dict[str, Any]:
        """Run one query and return its `data`. Retries transient failures.

        Any GraphQL error fails the query, because a partial answer would be counted
        as if it were complete. Only a caller that handles a missing object itself
        (the repository lookup) passes `allow_not_found=True`.
        """
        if "mutation" in query.lower():
            raise GitHubError("the client is read-only; mutations are not allowed")
        if self.remaining is not None and self.remaining < RATE_LIMIT_RESERVE:
            raise RateLimitLow(
                f"only {self.remaining} API points left; the limit resets at {self.reset_at}"
            )
        body = {"query": query, "variables": variables or {}}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._attempt(body, allow_not_found)
            except _Retry as reason:
                if attempt == MAX_ATTEMPTS:
                    raise GitHubError(f"GitHub failed {MAX_ATTEMPTS} times: {reason}") from None
                self._sleep(max(2**attempt, reason.wait))
        raise AssertionError("unreachable")  # pragma: no cover

    def _attempt(self, body: dict[str, Any], allow_not_found: bool) -> dict[str, Any]:
        try:
            response = self._http.post(ENDPOINT, json=body)
        except httpx.TransportError as exc:
            # the exception type is enough to diagnose; its text is not repeated
            raise _Retry(type(exc).__name__) from None

        status = response.status_code
        if status in RETRY_STATUSES or _is_secondary_limit(response):
            raise _Retry(f"HTTP {status}", _retry_after(response))
        if status == 401:
            raise GitHubError("GitHub rejected GITHUB_TOKEN (HTTP 401)")
        if status != 200:
            raise GitHubError(f"GitHub returned HTTP {status}")

        try:
            payload = response.json()
        except ValueError:  # a proxy error page instead of JSON
            raise _Retry("response was not JSON") from None
        data = payload.get("data")
        errors = payload.get("errors") or []
        if errors and not data:
            text = "; ".join(str(e.get("message", "?")) for e in errors)
            if any(word in text.lower() for word in ("timeout", "something went wrong")):
                raise _Retry("GraphQL timeout")
        self.requests += 1
        rate = (data or {}).get("rateLimit") or {}
        if rate:
            self.points += int(rate.get("cost") or 0)
            self.remaining = int(rate.get("remaining") or 0)
            self.reset_at = rate.get("resetAt")
        if errors:
            if allow_not_found and all(e.get("type") == "NOT_FOUND" for e in errors):
                return data or {}
            text = "; ".join(str(e.get("message", "?")) for e in errors)
            raise GitHubError(f"GitHub query failed: {text}")
        return data or {}


def resolve_repository(client: GitHubClient, owner: str, name: str) -> RepoInfo:
    """Look up the canonical name and default branch of a public repository."""
    data = client.query(RESOLVE_QUERY, {"owner": owner, "name": name}, allow_not_found=True)
    repo = data.get("repository")
    if repo is None:
        raise GitHubError(f"{owner}/{name} was not found")
    if repo.get("isPrivate"):
        raise GitHubError("only public repositories are supported")
    branch = (repo.get("defaultBranchRef") or {}).get("name")
    if not branch:
        raise GitHubError(f"{owner}/{name} has no default branch (is it empty?)")
    return RepoInfo(
        requested_slug=f"{owner}/{name}",
        canonical_slug=repo["nameWithOwner"],
        default_branch=branch,
    )
