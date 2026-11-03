"""First-timer lookback (ADR-0002): each author's earliest merged PR in the repository.

One `search` per distinct human author, over all repository history rather than the
window, with twenty searches batched into one request through GraphQL aliases
(Phase 0: optuna/optuna went from 148 requests to 8). The search must use the
canonical name, because search is keyed on a repository's current name.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from repocompass.github import RATE_LIMIT_FIELDS, GitHubClient, GitHubError

__all__ = ["lookback_earliest_merged"]

LOOKBACK_BATCH = 20


def _lookback_query(logins: list[str], canonical: str) -> tuple[str, dict[str, str]]:
    """One request carrying several author searches, using GraphQL aliases."""
    declarations = ", ".join(f"$q{i}: String!" for i in range(len(logins)))
    fields = "\n".join(
        f"  a{i}: search(query: $q{i}, type: ISSUE, first: 1) "
        "{ nodes { ... on PullRequest { createdAt } } }"
        for i in range(len(logins))
    )
    query = f"query ({declarations}) {{\n  {RATE_LIMIT_FIELDS}\n{fields}\n}}"
    variables = {
        f"q{i}": f"repo:{canonical} is:pr is:merged author:{login} sort:created-asc"
        for i, login in enumerate(logins)
    }
    return query, variables


def lookback_earliest_merged(
    client: GitHubClient,
    canonical: str,
    logins: Iterable[str],
    earliest: dict[str, str | None],
    *,
    save: Callable[[dict[str, str | None]], None],
) -> dict[str, str | None]:
    """Each author's earliest merged PR creation time (ISO text), or None if none merged.

    Covers all repository history, not just the window. Authors already in `earliest`
    (from a checkpoint) are skipped, and the result is saved after every request.
    """
    pending = sorted(set(logins) - set(earliest))
    for start in range(0, len(pending), LOOKBACK_BATCH):
        batch = pending[start : start + LOOKBACK_BATCH]
        query, variables = _lookback_query(batch, canonical)
        data = client.query(query, variables)
        for i, login in enumerate(batch):
            result = data.get(f"a{i}")
            if result is None:
                # a missing answer must not be read as "never merged", i.e. a newcomer
                raise GitHubError(f"the lookback for {login} returned no result")
            nodes = result.get("nodes") or []
            earliest[login] = nodes[0].get("createdAt") if nodes else None
        save(earliest)
    return earliest
