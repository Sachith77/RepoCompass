"""Tests for reading git output. The parser is tested on fixed text; no repository needed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from repocompass.gitclone import GitError, clone_path, log_args, parse_log

RS, US = "\x1e", "\x1f"


def _record(sha: str, when: str, name: str, email: str, *paths: str) -> str:
    return f"{RS}{sha}{US}{when}{US}{name}{US}{email}\n\n" + "\n".join(paths) + "\n"


def test_parse_log_reads_header_and_paths() -> None:
    text = _record(
        "abc", "2026-10-01T09:30:00+02:00", "Ada", "ada@example.com", "docs/a.md", "src/b.py"
    ) + _record("def", "2026-09-01T00:00:00+00:00", "Grace", "grace@example.com", "README.md")
    first, second = parse_log(text)

    assert first.sha == "abc"
    assert first.committed_at == datetime(2026, 10, 1, 9, 30, tzinfo=timezone(timedelta(hours=2)))
    assert first.author_name == "Ada"
    assert first.author_email == "ada@example.com"
    assert first.paths == ("docs/a.md", "src/b.py")
    assert second.paths == ("README.md",)
    assert second.committed_at.tzinfo is not None


def test_parse_log_handles_commits_without_paths_and_odd_file_names() -> None:
    text = _record("e1", "2026-10-01T00:00:00Z", "A", "a@x", "") + _record(
        "e2", "2026-10-02T00:00:00Z", "B", "b@x", "docs/naïve file.md"
    )
    empty, odd = parse_log(text)
    assert empty.paths == ()
    assert odd.paths == ("docs/naïve file.md",)
    assert odd.committed_at == datetime(2026, 10, 2, tzinfo=UTC)


def test_parse_log_of_nothing_is_empty() -> None:
    assert parse_log("") == []


def test_malformed_header_is_an_error_not_a_guess() -> None:
    with pytest.raises(GitError):
        parse_log(f"{RS}only-a-sha\n\nfile.txt\n")


def test_log_args_exclude_merges_and_bound_the_window() -> None:
    since = datetime(2025, 11, 3, tzinfo=UTC)
    args = log_args("origin/main", since)
    assert "--no-merges" in args
    assert "--name-only" in args
    # rename detection would download file contents into a blobless clone
    assert "--no-renames" in args
    assert f"--since={since.isoformat()}" in args
    assert "origin/main" in args


def test_clone_path_is_one_directory_per_repository() -> None:
    assert clone_path(Path("data/repos"), "Kludex/starlette") == Path(
        "data/repos/Kludex__starlette"
    )
