"""Database access: connect and apply the schema.

Connection strings are treated as secrets. psycopg errors can quote the DSN, so
every failure here is re-raised as DatabaseError with the DSN stripped out.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover
    from psycopg import Connection

__all__ = ["DatabaseError", "apply_schema", "connect", "schema_sql", "schema_table_names"]

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class DatabaseError(RuntimeError):
    """A database failure with any connection string removed from the message."""


def schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def schema_table_names() -> tuple[str, ...]:
    """Table names declared in schema.sql, in declaration order."""
    names: list[str] = []
    for line in schema_sql().splitlines():
        stripped = line.strip()
        prefix = "CREATE TABLE IF NOT EXISTS "
        if stripped.startswith(prefix):
            name = stripped[len(prefix) :].split("(")[0].strip()
            if name:
                names.append(name)
    return tuple(names)


MIN_SCRUB_LENGTH = 4


def _scrub(message: str, dsn: str) -> str:
    """Remove the DSN and each of its parts from an error message.

    psycopg reports connection failures by quoting the host, port and user rather
    than the whole DSN, so replacing the DSN string alone is not enough. Each
    component is removed separately. A password is removed whatever its length;
    other parts only when long enough that removing them cannot mangle unrelated
    text.
    """
    if not dsn:
        return message

    cleaned = message.replace(dsn, "<redacted>")
    parsed = urlsplit(dsn)
    parts = [parsed.password, parsed.username, parsed.hostname, parsed.path.lstrip("/")]

    for part in sorted({p for p in parts if p}, key=len, reverse=True):
        if len(part) >= MIN_SCRUB_LENGTH:
            cleaned = cleaned.replace(part, "<redacted>")

    # a short password still has to go, even at the cost of a messier message
    if parsed.password:
        cleaned = cleaned.replace(parsed.password, "<redacted>")
    return cleaned


@contextmanager
def connect(database_url: str) -> Iterator[Connection]:
    """Open a connection, scrubbing the DSN out of any failure."""
    import psycopg

    try:
        conn = psycopg.connect(database_url)
    except Exception as exc:  # re-raised below with the DSN scrubbed out
        raise DatabaseError(f"could not connect: {_scrub(str(exc), database_url)}") from None
    try:
        yield conn
    except Exception as exc:  # re-raised below with the DSN scrubbed out
        conn.rollback()
        raise DatabaseError(_scrub(str(exc), database_url)) from None
    else:
        conn.commit()
    finally:
        conn.close()


def apply_schema(database_url: str) -> tuple[str, ...]:
    """Apply schema.sql idempotently. Returns the tables that exist afterwards."""
    sql = schema_sql()
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                  FROM information_schema.tables
                 WHERE table_schema = current_schema()
                   AND table_type = 'BASE TABLE'
                 ORDER BY table_name
                """
            )
            return tuple(row[0] for row in cur.fetchall())
