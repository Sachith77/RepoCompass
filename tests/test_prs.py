"""Tests for PR ingest: parsing, monthly sampling, files pagination, checkpoints, lookback.

A scripted fake client stands in for GitHub, so no network is used.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from repocompass.config import Settings, load_settings
from repocompass.github import GitHubError
from repocompass.lookback import lookback_earliest_merged
from repocompass.prs import fetch_prs
from repocompass.records import (
    human_login,
    parse_pr,
    pr_areas,
    record_from_json,
    record_to_json,
)

SETTINGS = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": "postgresql://u:p@h/d"})
SNAPSHOT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
WINDOW_START = SNAPSHOT - timedelta(days=365)
AREAS = {"docs", "pkg/core", "tests"}
DEPTHS = {"pkg": 2}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _actor(login: str | None, kind: str = "User") -> dict[str, Any] | None:
    return None if login is None else {"login": login, "__typename": kind}


def _node(
    number: int,
    created: datetime,
    *,
    author: str | None = "ada",
    paths: tuple[str, ...] = ("docs/a.md",),
    more_files: bool = False,
    merged: bool = False,
    state: str = "OPEN",
    reviews: list[tuple[str, datetime]] = (),  # type: ignore[assignment]
    comments: list[tuple[str, datetime]] = (),  # type: ignore[assignment]
    more_reviews: bool = False,
    more_comments: bool = False,
    changed_files: int | None = None,
    author_kind: str = "User",
) -> dict[str, Any]:
    return {
        "number": number,
        "createdAt": _iso(created),
        "mergedAt": _iso(created + timedelta(days=1)) if merged else None,
        "closedAt": _iso(created + timedelta(days=1)) if state != "OPEN" else None,
        "merged": merged,
        "state": state,
        "authorAssociation": "NONE",
        "author": _actor(author, author_kind),
        "changedFiles": len(paths) if changed_files is None else changed_files,
        "files": {
            "pageInfo": {"hasNextPage": more_files, "endCursor": "f1" if more_files else None},
            "nodes": [{"path": p} for p in paths],
        },
        "reviews": {
            "pageInfo": {"hasNextPage": more_reviews},
            "nodes": [{"submittedAt": _iso(t), "author": _actor(who)} for who, t in reviews],
        },
        "comments": {
            "pageInfo": {"hasNextPage": more_comments},
            "nodes": [{"createdAt": _iso(t), "author": _actor(who)} for who, t in comments],
        },
    }


# --- actors and parsing -------------------------------------------------------


def test_human_login_excludes_bots_deleted_accounts_and_non_users() -> None:
    assert human_login(_actor("ada"), SETTINGS) == "ada"
    assert human_login(_actor("dependabot[bot]"), SETTINGS) is None
    assert human_login(_actor("renovate"), SETTINGS) is None
    assert human_login(_actor("some-app", "Bot"), SETTINGS) is None
    assert human_login(_actor("imported", "Mannequin"), SETTINGS) is None
    assert human_login(None, SETTINGS) is None


def test_parse_counts_files_per_current_area_only() -> None:
    created = SNAPSHOT - timedelta(days=40)
    paths = ("docs/a.md", "docs/b.md", "pkg/core/x.py", "README.md", "vendor/v.go", "gone/y.py")
    record = parse_pr(_node(1, created, paths=paths), list(paths), DEPTHS, AREAS, SETTINGS)
    assert record.area_files == {"docs": 2, "pkg/core": 1}
    assert pr_areas(record.area_files) == ["docs"]


def test_area_ties_count_for_each_tied_area() -> None:
    assert pr_areas({"docs": 2, "tests": 2, "pkg/core": 1}) == ["docs", "tests"]
    assert pr_areas({}) == []


def test_response_times_ignore_the_author_and_bots() -> None:
    created = SNAPSHOT - timedelta(days=40)
    node = _node(
        1,
        created,
        reviews=[
            ("ada", created + timedelta(hours=1)),  # the author: ignored
            ("grace", created + timedelta(hours=5)),
            ("linus", created + timedelta(hours=9)),
        ],
        comments=[
            ("codecov[bot]", created + timedelta(minutes=1)),  # a bot: ignored
            ("grace", created + timedelta(hours=3)),
        ],
    )
    record = parse_pr(node, ["docs/a.md"], DEPTHS, AREAS, SETTINGS)
    assert record.first_formal_review_at == created + timedelta(hours=5)
    assert record.first_human_response_at == created + timedelta(hours=3)
    assert record.response_times_complete is True
    assert record.reviewers == ("grace", "linus")


def test_response_times_are_unknown_when_the_slice_was_cut_short_without_a_human() -> None:
    created = SNAPSHOT - timedelta(days=40)
    bots_only = [("k8s-ci-robot", created + timedelta(minutes=1))]
    node = _node(1, created, comments=bots_only, more_comments=True)
    record = parse_pr(node, ["docs/a.md"], DEPTHS, AREAS, SETTINGS)
    assert record.response_times_complete is False
    assert record.first_human_response_at is None


def test_a_human_seen_in_a_cut_short_slice_is_still_known() -> None:
    created = SNAPSHOT - timedelta(days=40)
    node = _node(1, created, comments=[("grace", created + timedelta(hours=2))], more_comments=True)
    record = parse_pr(node, ["docs/a.md"], DEPTHS, AREAS, SETTINGS)
    assert record.response_times_complete is True
    assert record.first_human_response_at == created + timedelta(hours=2)


def test_record_survives_a_json_round_trip() -> None:
    created = SNAPSHOT - timedelta(days=40)
    node = _node(7, created, merged=True, state="MERGED", reviews=[("grace", created)])
    record = parse_pr(node, ["docs/a.md"], DEPTHS, AREAS, SETTINGS)
    assert record_from_json(record_to_json(record)) == record


# --- paging and monthly sampling ----------------------------------------------


class FakeClient:
    """Plays back PR pages; answers file-page and lookback queries from tables."""

    def __init__(
        self,
        pages: list[list[dict[str, Any]]],
        extra_files: dict[int, list[list[str]]] | None = None,
        earliest: dict[str, str | None] | None = None,
    ) -> None:
        self.pages = pages
        self.extra_files = extra_files or {}
        self.earliest = earliest or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_on_call: int | None = None

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        variables = variables or {}
        self.calls.append((query, variables))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise ConnectionError("dropped")
        if "pullRequests(" in query:
            index = int(variables["cursor"] or 0)
            more = index + 1 < len(self.pages)
            return {
                "repository": {
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": more, "endCursor": str(index + 1)},
                        "nodes": self.pages[index],
                    }
                }
            }
        if "pullRequest(" in query:
            pages = self.extra_files[variables["number"]]
            index = int(variables["cursor"][1:])  # "f1" -> page 1
            more = index < len(pages)
            files = {
                "pageInfo": {"hasNextPage": more, "endCursor": f"f{index + 1}"},
                "nodes": [{"path": p} for p in pages[index - 1]],
            }
            return {"repository": {"pullRequest": {"files": files}}}
        out: dict[str, Any] = {}
        for key, q in variables.items():
            login = q.split("author:")[1].split()[0]
            created = self.earliest.get(login)
            out["a" + key[1:]] = {"nodes": [{"createdAt": created}] if created else []}
        return out


def _fetch(
    client: FakeClient,
    state: dict[str, Any] | None = None,
    saves: list[dict[str, Any]] | None = None,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    store = saves if saves is not None else []
    return fetch_prs(
        client,  # type: ignore[arg-type]
        "o",
        "r",
        settings=settings,
        window_start=WINDOW_START,
        snapshot=SNAPSHOT,
        depths=DEPTHS,
        areas=AREAS,
        state=state,
        save=lambda s: store.append(s),
    )


def _small_cap() -> Settings:
    return load_settings(
        {
            "GITHUB_TOKEN": "fake",
            "DATABASE_URL": "postgresql://u:p@h/d",
            "REPOCOMPASS_MONTHLY_SAMPLE_CAP": "2",
        }
    )


def test_paging_stops_at_the_window_and_skips_prs_after_the_snapshot() -> None:
    pages = [
        [
            _node(9, SNAPSHOT + timedelta(minutes=5)),  # opened during the run
            _node(8, SNAPSHOT - timedelta(days=10)),
        ],
        [_node(7, SNAPSHOT - timedelta(days=300)), _node(6, SNAPSHOT - timedelta(days=400))],
        [_node(5, SNAPSHOT - timedelta(days=500))],  # never requested
    ]
    client = FakeClient(pages)
    state = _fetch(client)
    assert [r["number"] for r in state["records"]] == [8, 7]
    assert state["done"] is True
    assert len(client.calls) == 2


def test_bot_prs_are_dropped_before_the_cap_and_counted_separately() -> None:
    month = datetime(2026, 9, 20, tzinfo=UTC)
    nodes = [
        _node(1, month, author="dependabot[bot]"),
        _node(2, month - timedelta(days=1)),
        _node(3, month - timedelta(days=2), author="some-app", author_kind="Bot"),
        _node(4, month - timedelta(days=3)),
        _node(5, month - timedelta(days=4)),
    ]
    state = _fetch(FakeClient([nodes]), settings=_small_cap())
    assert [r["number"] for r in state["records"]] == [2, 4]  # bots never took a slot
    assert state["month_bots"] == {"2026-09": 2}
    assert state["month_totals"] == {"2026-09": 3}
    assert state["month_sampled"] == {"2026-09": 2}


def test_each_month_records_the_dates_its_sample_covers() -> None:
    newest, oldest = datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 5, tzinfo=UTC)
    state = _fetch(FakeClient([[_node(2, newest), _node(1, oldest)]]))
    assert state["month_last"] == {"2026-09": newest.isoformat()}
    assert state["month_first"] == {"2026-09": oldest.isoformat()}


def test_each_month_keeps_at_most_the_cap_and_counts_every_pr() -> None:
    month = datetime(2026, 9, 20, tzinfo=UTC)
    pages = [[_node(n, month - timedelta(days=n)) for n in (1, 2, 3)]]
    pages[0].append(_node(40, datetime(2026, 8, 10, tzinfo=UTC)))
    state = _fetch(FakeClient(pages), settings=_small_cap())
    assert [r["number"] for r in state["records"]] == [1, 2, 40]  # the newest two of September
    assert state["month_totals"] == {"2026-09": 3, "2026-08": 1}
    assert state["month_sampled"] == {"2026-09": 2, "2026-08": 1}


def test_file_lists_over_100_are_paginated_in_full() -> None:
    created = SNAPSHOT - timedelta(days=40)
    node = _node(1, created, paths=("docs/a.md",), more_files=True, changed_files=4)
    client = FakeClient(
        [[node]], extra_files={1: [["tests/t1.py", "tests/t2.py"], ["tests/t3.py"]]}
    )
    (record,) = _fetch(client)["records"]
    assert record["files_complete"] is True
    assert record["area_files"] == {"docs": 1, "tests": 3}


def test_a_list_shorter_than_changed_files_is_incomplete() -> None:
    # GitHub stops at 3,000 files with no next page; only the count reveals it
    node = _node(1, SNAPSHOT - timedelta(days=40), paths=("docs/a.md",), changed_files=3500)
    (record,) = _fetch(FakeClient([[node]]))["records"]
    assert record["files_complete"] is False


def test_a_follow_up_page_without_a_files_connection_is_incomplete() -> None:
    class Missing(FakeClient):
        def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            if "pullRequest(" in query and "pullRequests(" not in query:
                return {"repository": {"pullRequest": None}}
            return super().query(query, variables)

    node = _node(1, SNAPSHOT - timedelta(days=40), more_files=True)
    (record,) = _fetch(Missing([[node]]))["records"]
    assert record["files_complete"] is False


def test_a_file_list_that_cannot_be_completed_is_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    import repocompass.prs as prs

    monkeypatch.setattr(prs, "MAX_FILE_PAGES", 1)
    created = SNAPSHOT - timedelta(days=40)
    node = _node(1, created, more_files=True)
    client = FakeClient([[node]], extra_files={1: [["tests/a.py"], ["tests/b.py"]]})
    (record,) = _fetch(client)["records"]
    assert record["files_complete"] is False


def test_a_checkpoint_is_saved_after_every_page_and_resumes_where_it_stopped() -> None:
    pages = [
        [_node(3, SNAPSHOT - timedelta(days=10))],
        [_node(2, SNAPSHOT - timedelta(days=20))],
        [_node(1, SNAPSHOT - timedelta(days=30))],
    ]
    client = FakeClient(pages)
    client.fail_on_call = 2
    saves: list[dict[str, Any]] = []
    with pytest.raises(ConnectionError):
        _fetch(client, saves=saves)
    assert len(saves) == 1
    checkpoint = saves[-1]
    assert [r["number"] for r in checkpoint["records"]] == [3]

    resumed = FakeClient(pages)
    state = _fetch(resumed, state=checkpoint)
    assert [r["number"] for r in state["records"]] == [3, 2, 1]
    assert len(resumed.calls) == 2  # page 1 was not fetched again


# --- first-timer lookback -------------------------------------------------------


def test_lookback_batches_twenty_authors_per_request_and_checkpoints() -> None:
    logins = [f"user{i}" for i in range(45)]
    client = FakeClient([], earliest={"user0": "2024-01-01T00:00:00Z"})
    saves: list[dict[str, str | None]] = []
    earliest = lookback_earliest_merged(
        client,  # type: ignore[arg-type]
        "o/r",
        logins,
        {},
        save=lambda e: saves.append(dict(e)),
    )
    assert len(client.calls) == 3
    assert len(saves) == 3
    assert earliest["user0"] == "2024-01-01T00:00:00Z"
    assert earliest["user1"] is None
    first_query, first_vars = client.calls[0]
    assert len(first_vars) == 20
    assert first_vars["q0"] == "repo:o/r is:pr is:merged author:user0 sort:created-asc"
    assert "mutation" not in first_query.lower()


def test_a_missing_lookback_answer_is_an_error_not_a_newcomer() -> None:
    class Missing(FakeClient):
        def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            return {"a0": None}

    with pytest.raises(GitHubError, match="ada"):
        lookback_earliest_merged(Missing([]), "o/r", ["ada"], {}, save=lambda e: None)  # type: ignore[arg-type]


def test_lookback_skips_authors_already_in_the_checkpoint() -> None:
    client = FakeClient([])
    done = {"ada": None}
    lookback_earliest_merged(client, "o/r", ["ada"], done, save=lambda e: None)  # type: ignore[arg-type]
    assert client.calls == []
