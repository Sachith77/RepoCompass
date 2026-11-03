"""Tests for the command line: exit codes, and that no secret is ever printed."""

from __future__ import annotations

from pathlib import Path

import pytest

from repocompass.cli import main

FAKE_TOKEN = "fake-token-must-not-leak"
FAKE_PASSWORD = "fake-password-must-not-leak"
# .invalid never resolves, so init-db fails fast without touching a real server
FAKE_URL = f"postgresql://fakeuser:{FAKE_PASSWORD}@db-host-must-not-leak.invalid:5432/fakedb"


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run in an empty directory so the project's real .env is never read."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)


def _assert_no_secret(text: str) -> None:
    for secret in (FAKE_TOKEN, FAKE_PASSWORD, "fakeuser", "db-host-must-not-leak.invalid"):
        assert secret not in text


def test_unknown_command_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["nonsense"]) == 2
    assert "usage" in capsys.readouterr().err


def test_check_prints_no_secret(fake_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check"]) == 0
    out = capsys.readouterr()
    assert "configuration loaded" in out.out
    _assert_no_secret(out.out + out.err)


def test_init_db_failure_prints_no_secret(
    fake_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init-db"]) == 1
    out = capsys.readouterr()
    assert "database error" in out.err
    _assert_no_secret(out.out + out.err)


def test_ingest_git_needs_exactly_one_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ingest-git"]) == 2
    assert "usage" in capsys.readouterr().err


def test_ingest_git_rejects_a_bad_slug_before_any_network_call(
    fake_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ingest-git", "../not-a-repo"]) == 1
    out = capsys.readouterr()
    assert "owner/repo" in out.err
    _assert_no_secret(out.out + out.err)


def test_missing_config_exits_with_code_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        main(["check"])
    assert excinfo.value.code == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err
