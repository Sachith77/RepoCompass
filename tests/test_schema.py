"""Tests for the schema file and the secret-scrubbing database helpers.

These run without a live database. Applying the schema against real Postgres is a
separate check, run manually, because CI has no database.
"""

from __future__ import annotations

import pytest

from repocompass.db import DatabaseError, connect, schema_sql, schema_table_names

EXPECTED_TABLES = ("repos", "prs", "pr_areas", "area_stats", "jobs")


def test_schema_declares_exactly_the_five_tables() -> None:
    assert schema_table_names() == EXPECTED_TABLES


def test_schema_is_idempotent_by_construction() -> None:
    """Every create statement must tolerate being run twice."""
    sql = schema_sql()
    for keyword in ("CREATE TABLE", "CREATE INDEX"):
        for line in sql.splitlines():
            if line.strip().startswith(keyword):
                assert "IF NOT EXISTS" in line, line


def _declared_column_names() -> set[str]:
    """Column names declared in schema.sql, ignoring comments and constraints."""
    names: set[str] = set()
    for raw in schema_sql().splitlines():
        line = raw.split("--", 1)[0].strip()
        if not line or line.startswith(("CREATE", "PRIMARY KEY", "CONSTRAINT", "FOREIGN KEY", ")")):
            continue
        first = line.split()[0].strip(",").lower()
        if first.isidentifier():
            names.add(first)
    return names


def test_schema_stores_no_file_contents() -> None:
    """The brief forbids storing file contents; only paths and counts are allowed."""
    columns = _declared_column_names()
    assert columns, "no columns parsed from schema.sql"
    for banned in ("blob", "patch", "diff", "file_content", "body", "content", "text_body"):
        assert banned not in columns


@pytest.mark.parametrize(
    "column",
    [
        "distinct_newcomer_authors",
        "top_author_pr_share",
        "author_concentration_flag",
        "stale_open_newcomer_prs",
    ],
)
def test_area_stats_has_the_sample_quality_columns(column: str) -> None:
    assert column in schema_sql()


@pytest.mark.parametrize(
    "column",
    ["total_prs_in_window", "sampled_prs", "prs_per_month", "is_sampled", "canonical_slug"],
)
def test_repos_records_the_sampling_and_canonical_slug(column: str) -> None:
    assert column in schema_sql()


@pytest.mark.parametrize(
    "column", ["first_formal_review_at", "first_human_response_at", "files_complete", "is_newcomer"]
)
def test_prs_stores_both_response_times_and_completeness(column: str) -> None:
    assert column in schema_sql()


def test_jobs_can_checkpoint_and_record_failure() -> None:
    sql = schema_sql()
    for column in ("checkpoint", "attempts", "last_error", "stage"):
        assert column in sql


def test_pr_areas_allows_a_pr_in_several_areas() -> None:
    """Ties count for each tied area, so the key must include the area."""
    assert "PRIMARY KEY (repo_id, pr_number, area)" in schema_sql()


DSN = "postgresql://someuser:sup3r-s3cret@ep-private-12345.example.invalid:5432/maindb"


def test_connect_failure_does_not_leak_the_dsn() -> None:
    with pytest.raises(DatabaseError) as excinfo, connect(DSN):
        pass  # pragma: no cover - connection is expected to fail
    message = str(excinfo.value)
    assert DSN not in message
    # psycopg quotes the host and user, not the whole DSN, so each part must go
    for part in ("sup3r-s3cret", "someuser", "ep-private-12345.example.invalid", "maindb"):
        assert part not in message, f"{part} leaked into: {message}"


def _column_line(name: str) -> str:
    for raw in schema_sql().splitlines():
        if raw.strip().startswith(name + " "):
            return raw
    raise AssertionError(f"column {name} not found")


def test_files_complete_has_no_default() -> None:
    """A default of true would let a forgetful ingest count a truncated PR as complete."""
    line = _column_line("files_complete")
    assert "NOT NULL" in line
    assert "DEFAULT" not in line


@pytest.mark.parametrize(
    "column",
    [
        "commits_90d",
        "commits_12mo",
        "commit_authors_12mo",
        "activity_band",
        "top_contributors",
        "top_reviewers",
        "sweep_commits_excluded",
    ],
)
def test_schema_stores_area_activity_and_people_counts(column: str) -> None:
    assert column in _declared_column_names()


def test_pr_state_is_limited_to_github_values() -> None:
    assert "CHECK (state IN ('OPEN', 'CLOSED', 'MERGED'))" in schema_sql()
