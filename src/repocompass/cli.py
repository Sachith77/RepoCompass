"""Command line entry point.

Usage:
    python -m repocompass init-db      apply the schema
    python -m repocompass check        report configuration without printing secrets
"""

from __future__ import annotations

import sys

from repocompass.config import ConfigError, Settings, load_settings
from repocompass.db import DatabaseError, apply_schema, schema_table_names


def _load() -> Settings:
    try:
        return load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def cmd_check() -> int:
    """Confirm configuration resolves. Prints no secret values."""
    settings = _load()
    print("configuration loaded")
    print(f"  window_days                     {settings.window_days}")
    print(f"  maturity_days                   {settings.maturity_days}")
    print(f"  monthly_sample_cap              {settings.monthly_sample_cap}")
    print(f"  min_sample                      {settings.min_sample}")
    print(f"  stale_open_days                 {settings.stale_open_days}")
    print(f"  author_concentration_threshold  {settings.author_concentration_threshold}")
    print(f"  excluded_dirs                   {', '.join(settings.excluded_dirs)}")
    print(f"  schema tables                   {', '.join(schema_table_names())}")
    return 0


def cmd_init_db() -> int:
    settings = _load()
    try:
        tables = apply_schema(settings.database_url)
    except DatabaseError as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 1
    print(f"schema applied; tables present: {', '.join(tables)}")
    return 0


COMMANDS = {"check": cmd_check, "init-db": cmd_init_db}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print(f"usage: python -m repocompass {{{'|'.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    return COMMANDS[args[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
