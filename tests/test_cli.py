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


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["analyze"], 2),
        (["analyze", "a/b", "c/d"], 2),
        (["resume"], 2),
        (["resume", "abc"], 2),
        (["worker", "--forever"], 2),
        (["serve", "--port"], 2),
        (["serve", "--port", "eighty"], 2),
        (["serve", "--host", "0.0.0.0"], 2),
    ],
)
def test_analyze_and_resume_check_their_arguments(
    args: list[str], code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(args) == code
    assert "usage" in capsys.readouterr().err


def test_analyze_rejects_a_bad_slug_before_creating_a_job(
    fake_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # the fake database cannot be reached, so reaching it would print "database"
    assert main(["analyze", "../not-a-repo"]) == 1
    out = capsys.readouterr()
    assert "owner/repo" in out.err
    assert "could not connect" not in out.err
    _assert_no_secret(out.out + out.err)


def test_worker_without_a_database_fails_cleanly(
    fake_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["worker", "--once"]) == 1
    out = capsys.readouterr()
    assert "worker stopped" in out.err
    _assert_no_secret(out.out + out.err)


def test_resume_failure_prints_no_secret(
    fake_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["resume", "1"]) == 1
    out = capsys.readouterr()
    assert "cannot resume" in out.err
    _assert_no_secret(out.out + out.err)


def test_validate_needs_a_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate"]) == 2
    assert "usage" in capsys.readouterr().err


def test_validate_refuses_to_pool_analyses_with_different_parameters(
    fake_env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import repocompass.validation as validation

    base = {"maturity_days": 30, "min_sample": 10, "wilson_z": 1.96}
    runs = iter([base, {**base, "min_sample": 5}])

    def fake_load(settings: object, owner: str, name: str) -> tuple:
        from datetime import UTC, datetime

        return f"{owner}/{name}", datetime(2026, 11, 3, tzinfo=UTC), next(runs), []

    monkeypatch.setattr(validation, "load_repo", fake_load)
    assert main(["validate", "a/b", "c/d"]) == 1
    assert "different parameters" in capsys.readouterr().err


def test_validate_database_failure_prints_no_secret(
    fake_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", "a/b"]) == 1
    out = capsys.readouterr()
    assert "validation failed" in out.err
    _assert_no_secret(out.out + out.err)
