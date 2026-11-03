"""PR ingest: page PRs, sample by month, complete file lists, look up first-timers.

Paging: `repository.pullRequests` newest-first, 50 per page, with the first 100
changed files, 20 reviews and 30 comments inline (Phase 0 measured 1-2 points per
page). A PR with more files gets follow-up requests for the rest.

Sampling (ADR-0004): bot PRs (and other non-user authors) are counted per month and
dropped first, so they never use up the sample. Every human PR in the window is then
counted in its calendar month, and at most `monthly_sample_cap` per month are kept.
Paging is newest-first, so a capped month keeps its newest PRs: not random, and the
report says "sampled".

Each kept PR becomes a small record (records.py), which keeps the checkpoint small
enough to save after every page.

The first-timer lookback that follows this stage is in lookback.py.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from repocompass.config import Settings
from repocompass.github import RATE_LIMIT_FIELDS, GitHubClient, GitHubError
from repocompass.records import created_at, human_login, parse_pr, record_to_json

__all__ = ["fetch_prs", "new_fetch_state"]

PAGE_SIZE = 50
# GitHub lists at most 3,000 files per PR, i.e. 30 pages of 100; the guard sits above that.
MAX_FILE_PAGES = 40

PR_PAGE_QUERY = f"""
query ($owner: String!, $name: String!, $cursor: String) {{
  {RATE_LIMIT_FIELDS}
  repository(owner: $owner, name: $name) {{
    pullRequests(first: {PAGE_SIZE}, after: $cursor,
                 orderBy: {{field: CREATED_AT, direction: DESC}}) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        number createdAt mergedAt closedAt merged state authorAssociation changedFiles
        author {{ login __typename }}
        files(first: 100) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ path }} }}
        reviews(first: 20) {{
          pageInfo {{ hasNextPage }} nodes {{ submittedAt author {{ login __typename }} }}
        }}
        comments(first: 30) {{
          pageInfo {{ hasNextPage }} nodes {{ createdAt author {{ login __typename }} }}
        }}
      }}
    }}
  }}
}}
"""

FILES_PAGE_QUERY = f"""
query ($owner: String!, $name: String!, $number: Int!, $cursor: String) {{
  {RATE_LIMIT_FIELDS}
  repository(owner: $owner, name: $name) {{
    pullRequest(number: $number) {{
      files(first: 100, after: $cursor) {{ pageInfo {{ hasNextPage endCursor }} nodes {{ path }} }}
    }}
  }}
}}
"""


def _all_paths(
    client: GitHubClient, owner: str, name: str, node: dict[str, Any]
) -> tuple[list[str], bool]:
    """Every changed path of one PR, and whether the list is complete.

    Complete means pagination finished AND the list is as long as `changedFiles`:
    GitHub stops listing at 3,000 files with no "next page", so the length check is
    what catches a very large PR.
    """
    files = node.get("files") or {}
    paths = [f["path"] for f in files.get("nodes") or []]
    info = files.get("pageInfo") or {}
    expected = int(node.get("changedFiles") or 0)
    for _ in range(MAX_FILE_PAGES):
        if not info.get("hasNextPage"):
            return paths, len(paths) >= expected
        data = client.query(
            FILES_PAGE_QUERY,
            {"owner": owner, "name": name, "number": node["number"], "cursor": info["endCursor"]},
        )
        page = ((data.get("repository") or {}).get("pullRequest") or {}).get("files")
        if page is None:
            return paths, False
        paths.extend(f["path"] for f in page.get("nodes") or [])
        info = page.get("pageInfo") or {}
    return paths, False


MONTH_COUNTERS = ("month_totals", "month_bots", "month_sampled")


def new_fetch_state() -> dict[str, Any]:
    """Per month: human PRs seen, bot PRs dropped, PRs kept, and the kept date range."""
    state: dict[str, Any] = {"cursor": None, "done": False, "records": []}
    for key in (*MONTH_COUNTERS, "month_first", "month_last"):
        state[key] = {}
    return state


def fetch_prs(
    client: GitHubClient,
    owner: str,
    name: str,
    *,
    settings: Settings,
    window_start: datetime,
    snapshot: datetime,
    depths: dict[str, int],
    areas: set[str],
    state: dict[str, Any] | None,
    save: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Page through the window, keeping up to the monthly cap. Resumable from `state`.

    A page's results are merged into the state only once the whole page succeeded,
    and the state is saved after every page, so a resumed run repeats at most one page.
    """
    state = state or new_fetch_state()
    while not state["done"]:
        data = client.query(
            PR_PAGE_QUERY, {"owner": owner, "name": name, "cursor": state["cursor"]}
        )
        conn = (data.get("repository") or {}).get("pullRequests")
        if conn is None:
            raise GitHubError(f"{owner}/{name} returned no pull requests connection")

        counts = {key: Counter(state[key]) for key in MONTH_COUNTERS}
        first, last = dict(state["month_first"]), dict(state["month_last"])
        kept: list[dict[str, Any]] = []
        seen = {r["number"] for r in state["records"]}
        reached_window_start = False
        for node in conn.get("nodes") or []:
            created = created_at(node)
            if created > snapshot or node["number"] in seen:
                continue  # opened during this run, or already counted on an earlier page
            if created < window_start:
                reached_window_start = True  # newest-first: everything after is older
                break
            month = created.strftime("%Y-%m")
            if human_login(node.get("author"), settings) is None:
                counts["month_bots"][month] += 1  # dropped before the cap
                continue
            counts["month_totals"][month] += 1
            if counts["month_sampled"][month] >= settings.monthly_sample_cap:
                continue
            counts["month_sampled"][month] += 1
            last.setdefault(month, created.isoformat())  # newest-first: first seen is newest
            first[month] = created.isoformat()
            paths, complete = _all_paths(client, owner, name, node)
            record = parse_pr(node, paths, depths, areas, settings, files_complete=complete)
            kept.append(record_to_json(record))

        info = conn.get("pageInfo") or {}
        state = {
            "cursor": info.get("endCursor"),
            "done": reached_window_start or not info.get("hasNextPage"),
            **{key: dict(counter) for key, counter in counts.items()},
            "month_first": first,
            "month_last": last,
            "records": state["records"] + kept,
        }
        save(state)
    return state
