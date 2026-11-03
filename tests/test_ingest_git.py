"""Tests for the stage-2 pipeline, with git and GitHub replaced by fixed fakes.

No network, no clone and no database: `save=False` skips the write, and the SQL
statements are checked against schema.sql separately.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from repocompass import ingest_git as stage
from repocompass.activity import Commit
from repocompass.config import Settings, load_settings
from repocompass.db import schema_sql
from repocompass.github import RepoInfo

TREE = ["README.md", "docs/a.md", "src/x.py", "tests/t.py", "web/app.js", "vendor/lib.go"]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        {
            "GITHUB_TOKEN": "fake",
            "DATABASE_URL": "postgresql://u:p@h/d",
            "REPOCOMPASS_CLONE_DIR": str(tmp_path),
        }
    )


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    seen: dict[str, object] = {}

    def resolve(token: str, owner: str, name: str) -> RepoInfo:
        seen["resolve"] = (owner, name)
        return RepoInfo("old-owner/thing", "new-owner/thing", "main")

    def clone(url: str, dest: Path) -> None:
        seen["clone"] = (url, dest)

    def files(dest: Path, rev: str) -> list[str]:
        seen["files_rev"] = rev
        return TREE

    def commits(dest: Path, rev: str, since: datetime) -> list[Commit]:
        when = since + timedelta(days=300)  # 65 days before the snapshot: recent
        return [
            Commit("a", when, "Ada", "ada@example.com", ("src/x.py", "tests/t.py")),
            Commit("b", when, "Ada", "ada@example.com", ("README.md",)),
            Commit("c", when, "Grace", "grace@example.com", ("vendor/lib.go",)),
        ]

    monkeypatch.setattr(stage, "resolve_repository", resolve)
    monkeypatch.setattr(stage, "clone_or_update", clone)
    monkeypatch.setattr(stage, "list_files", files)
    monkeypatch.setattr(stage, "read_commits", commits)
    return seen


def test_pipeline_uses_the_canonical_name_and_remote_branch(
    settings: Settings, calls: dict[str, object]
) -> None:
    result = stage.ingest_git(settings, "https://github.com/old-owner/thing", save=False)

    assert calls["resolve"] == ("old-owner", "thing")
    url, dest = calls["clone"]
    assert url == "https://github.com/new-owner/thing.git"
    assert Path(dest).name == "new-owner__thing"
    assert calls["files_rev"] == "origin/main"
    assert result.repo.canonical_slug == "new-owner/thing"


def test_pipeline_drops_excluded_dirs_and_counts_activity(
    settings: Settings, calls: dict[str, object]
) -> None:
    result = stage.ingest_git(settings, "old-owner/thing", save=False)

    assert result.files_considered == 5  # vendor/lib.go dropped
    assert result.depths == {}
    rows = {a.area: (a.commits_window, a.band) for a in result.activity.areas}
    assert rows == {
        "docs": (0, "dormant"),
        "src": (1, "active"),
        "tests": (1, "active"),
        "web": (0, "dormant"),
    }
    # the root-only and vendor-only commits are in the window but count toward no area
    assert result.activity.commits_in_window == 3
    assert result.activity.counted_commits == 1


def _insert_columns(sql: str) -> list[str]:
    match = re.search(r"INSERT INTO \w+ \(([^)]*)\)", sql)
    assert match, sql
    return [c.strip() for c in match.group(1).split(",")]


@pytest.mark.parametrize("sql", [stage.UPSERT_REPO, stage.INSERT_AREA])
def test_every_written_column_exists_in_the_schema(sql: str) -> None:
    schema = schema_sql()
    for column in _insert_columns(sql):
        assert re.search(rf"^\s+{column}\s", schema, re.MULTILINE), column
