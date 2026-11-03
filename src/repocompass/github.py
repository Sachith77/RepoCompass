"""Read-only GitHub access: parse a repository slug and resolve its canonical name.

The canonical name must be resolved before anything else. `repository(owner, name)`
follows renames, but GitHub search is keyed on the current name, so a renamed
repository (encode/starlette is now Kludex/starlette) would otherwise look empty.

Queries only. The token is sent in a header and never appears in an error message.
Retry and rate-limit tracking for long paginated runs belong to the PR ingest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

__all__ = ["GitHubError", "RepoInfo", "parse_repo_slug", "resolve_repository"]

ENDPOINT = "https://api.github.com/graphql"
TIMEOUT_SECONDS = 30.0

# GitHub's own limits: owners are letters, digits and inner dashes (max 39);
# repository names are letters, digits, '.', '_' and '-' (max 100).
SLUG_RE = re.compile(r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<name>[A-Za-z0-9._-]{1,100})")
URL_PREFIXES = ("https://github.com/", "http://github.com/", "github.com/")

RESOLVE_QUERY = """
query ($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    isPrivate
    defaultBranchRef { name }
  }
}
"""


class GitHubError(RuntimeError):
    """A GitHub failure, with no token in the message."""


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


def resolve_repository(
    token: str,
    owner: str,
    name: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> RepoInfo:
    """Look up the canonical name and default branch of a public repository."""
    headers = {"Authorization": f"bearer {token}", "User-Agent": "repocompass"}
    body = {"query": RESOLVE_QUERY, "variables": {"owner": owner, "name": name}}
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT_SECONDS, headers=headers) as client:
            response = client.post(ENDPOINT, json=body)
    except httpx.HTTPError as exc:
        # the exception type is enough to diagnose; its text is not repeated
        raise GitHubError(f"could not reach GitHub ({type(exc).__name__})") from None

    if response.status_code == 401:
        raise GitHubError("GitHub rejected GITHUB_TOKEN (HTTP 401)")
    if response.status_code != 200:
        raise GitHubError(f"GitHub returned HTTP {response.status_code}")

    repo = (response.json().get("data") or {}).get("repository")
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
