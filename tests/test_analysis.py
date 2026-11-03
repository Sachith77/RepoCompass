"""Tests for one analysis: stage order, checkpoints and resuming. No network, no database."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from repocompass import analysis
from repocompass.activity import ActivitySummary, AreaActivity
from repocompass.config import load_settings
from repocompass.db import schema_sql
from repocompass.github import RepoInfo
from repocompass.ingest_git import GitIngestResult

SETTINGS = load_settings({"GITHUB_TOKEN": "fake", "DATABASE_URL": "postgresql://u:p@h/d"})
SNAPSHOT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

GIT = GitIngestResult(
    repo=RepoInfo("old/thing", "new/thing", "main"),
    snapshot=SNAPSHOT,
    files_considered=10,
    depths={},
    activity=ActivitySummary(
        areas=(AreaActivity("docs", 1, 2, 1, "active"), AreaActivity("tests", 0, 0, 0, "dormant")),
        commits_in_window=2,
        bot_commits=0,
        sweep_commits=0,
        counted_commits=2,
    ),
    seconds={"resolve": 0.1},
)


def _node(number: int, author: str, days_ago: int, merged: bool) -> dict[str, Any]:
    created = SNAPSHOT - timedelta(days=days_ago)
    when = (created + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "number": number,
        "createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mergedAt": when if merged else None,
        "closedAt": when,
        "merged": merged,
        "state": "MERGED" if merged else "CLOSED",
        "authorAssociation": "NONE",
        "author": {"login": author, "__typename": "User"},
        "changedFiles": 1,
        "files": {"pageInfo": {"hasNextPage": False}, "nodes": [{"path": "docs/a.md"}]},
        "reviews": {"nodes": []},
        "comments": {"nodes": []},
    }


class FakeClient:
    """Two PR pages, then lookback answers: ada first merged on PR 1's date."""

    def __init__(self) -> None:
        self.pages = [
            [_node(3, "ada", 40, True), _node(2, "bob", 50, False)],
            [_node(1, "ada", 60, True)],
        ]
        self.queries: list[str] = []
        self.requests = 0
        self.points = 0

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        variables = variables or {}
        self.queries.append("search" if "search(" in query else "page")
        self.requests += 1
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
        first = (SNAPSHOT - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = {}
        for key, q in variables.items():
            login = q.split("author:")[1].split()[0]
            out["a" + key[1:]] = {"nodes": [{"createdAt": first}] if login == "ada" else []}
        return out


@pytest.fixture(autouse=True)
def fake_git_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis, "git_stage", lambda settings, client, text: GIT)


def _run(client: FakeClient, checkpoint: dict[str, Any] | None, saves: list) -> Any:
    def save(stage: str, progress: int, state: dict[str, Any]) -> None:
        # what reaches the jobs table must be plain JSON
        saves.append((stage, progress, json.loads(json.dumps(state))))

    return analysis.run_analysis(
        SETTINGS,
        "old/thing",
        client,  # type: ignore[arg-type]
        checkpoint=checkpoint,
        save_checkpoint=save,
    )


def test_a_full_run_checkpoints_every_step_and_computes_metrics() -> None:
    saves: list = []
    result = _run(FakeClient(), None, saves)

    assert [s[0] for s in saves] == ["prs", "prs", "prs", "lookback"]
    assert [s[1] for s in saves][-1] == 95
    assert {r.number: r.is_newcomer for r in result.records} == {3: False, 2: True, 1: True}
    # mature newcomer PRs: #2 (closed) and #1 (merged) -> rate 0.5
    assert result.repo_rate == pytest.approx(0.5)
    assert result.repo_mature_newcomer_prs == 2
    assert result.note.total_prs == 3
    assert result.note.is_sampled is False
    docs = {s.area: s for s in result.stats}["docs"]
    assert docs.mature_newcomer_prs == 2
    assert docs.top_contributors == [{"login": "ada", "count": 2}]


def test_a_resumed_run_skips_finished_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    saves: list = []
    _run(FakeClient(), None, saves)
    after_pages = saves[2][2]  # the checkpoint once every PR page was saved

    def no_git(*args: object) -> None:
        raise AssertionError("the git stage must not run again")

    monkeypatch.setattr(analysis, "git_stage", no_git)
    client = FakeClient()
    result = _run(client, after_pages, [])
    assert client.queries == ["search"]  # no PR page fetched again
    assert len(result.records) == 3


def test_resuming_after_the_whole_lookback_makes_no_requests() -> None:
    saves: list = []
    first = _run(FakeClient(), None, saves)
    client = FakeClient()
    again = _run(client, saves[-1][2], [])
    assert client.queries == []
    assert again.stats == first.stats


def _insert_columns(sql: str) -> list[str]:
    match = re.search(r"INSERT INTO \w+ \(([^)]*)\)", sql)
    assert match, sql
    return [c.strip() for c in match.group(1).split(",")]


@pytest.mark.parametrize(
    "sql",
    [analysis.UPSERT_REPO, analysis.INSERT_PR, analysis.INSERT_PR_AREA, analysis.INSERT_AREA],
)
def test_every_written_column_exists_in_the_schema(sql: str) -> None:
    columns = _insert_columns(sql)
    assert sql.count("%s") == len(columns)
    schema = schema_sql()
    for column in columns:
        assert re.search(rf"^\s+{column}\s", schema, re.MULTILINE), column


def test_usage_totals_carry_over_when_a_job_is_resumed() -> None:
    saves: list = []
    first = _run(FakeClient(), None, saves)
    assert first.usage["requests"] == 3  # two PR pages and one lookback request
    resumed = _run(FakeClient(), saves[2][2], [])  # after the PR pages: one lookback left
    assert resumed.usage["requests"] == 3
    assert set(resumed.usage["seconds"]) == {"git_stage", "pr_pages", "lookback"}
