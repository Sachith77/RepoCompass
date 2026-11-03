"""Tests for .env parsing."""

from __future__ import annotations

from pathlib import Path

from repocompass.config import load_env_file


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "absent") == {}


def test_parses_keys_comments_and_blank_lines(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "GITHUB_TOKEN=abc123",
                "DATABASE_URL=postgresql://u:p@h/d",
                "  REPOCOMPASS_MIN_SAMPLE = 7  ",
                "NOT_A_PAIR",
            ]
        ),
        encoding="utf-8",
    )
    assert load_env_file(target) == {
        "GITHUB_TOKEN": "abc123",
        "DATABASE_URL": "postgresql://u:p@h/d",
        "REPOCOMPASS_MIN_SAMPLE": "7",
    }


def test_strips_surrounding_quotes(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("GITHUB_TOKEN=\"quoted\"\nDATABASE_URL='single'\n", encoding="utf-8")
    assert load_env_file(target) == {"GITHUB_TOKEN": "quoted", "DATABASE_URL": "single"}


def test_value_containing_equals_is_kept_whole(tmp_path: Path) -> None:
    """Connection strings and tokens can contain '='."""
    target = tmp_path / ".env"
    target.write_text("DATABASE_URL=postgresql://h/d?opts=a=b\n", encoding="utf-8")
    assert load_env_file(target)["DATABASE_URL"] == "postgresql://h/d?opts=a=b"
