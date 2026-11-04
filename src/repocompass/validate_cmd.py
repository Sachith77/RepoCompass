"""The `validate` command: cutoff validation over stored analyses (the method is in validation.py).

    python -m repocompass validate [--months 12|24] OWNER/REPO [OWNER/REPO ...]

Two modes, each fixed before running:
- 12 (default): 12-month analyses, cutoff 182 days before the snapshot; results/validation/
- 24: 24-month analyses (made with REPOCOMPASS_WINDOW_DAYS=730), cutoff 365 days before the
  snapshot, so bands come from months -24 to -12 and are tested on months -12 to 0;
  results/validation/window24/
Every stored analysis must have been made with the mode's window, or the command refuses.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from repocompass import validation
from repocompass.config import ConfigError, load_settings
from repocompass.db import DatabaseError
from repocompass.github import GitHubError, parse_repo_slug
from repocompass.validation_report import RESAMPLES, SEED, write_results

__all__ = ["MODES", "cmd_validate"]

USAGE = "usage: python -m repocompass validate [--months 12|24] OWNER/REPO [OWNER/REPO ...]"


@dataclass(frozen=True)
class Mode:
    window_days: int  # the analysis window the stored analyses must have used
    cutoff_days: int  # how far before each snapshot the cutoff is
    out_dir: str  # relative to the project folder


MODES = {
    12: Mode(window_days=365, cutoff_days=182, out_dir="results/validation"),
    24: Mode(window_days=730, cutoff_days=365, out_dir="results/validation/window24"),
}


def _parse(args: list[str]) -> tuple[int, list[str]] | None:
    """Options come first; anything else that looks like an option is a usage error."""
    months, repos = 12, args
    if args[:1] == ["--months"]:
        if len(args) < 2 or not args[1].isdigit() or int(args[1]) not in MODES:
            return None
        months, repos = int(args[1]), args[2:]
    if not repos or any(r.startswith("-") for r in repos):
        return None
    return months, repos


def cmd_validate(args: list[str]) -> int:
    parsed = _parse(args)
    if parsed is None:
        print(USAGE, file=sys.stderr)
        return 2
    months, repos = parsed
    mode = MODES[months]
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    checks, params = [], None
    try:
        for text in repos:
            owner, name = parse_repo_slug(text)
            slug, snapshot, repo_params, prs, capped = validation.load_repo(settings, owner, name)
            if repo_params.get("window_days") != mode.window_days:
                print(
                    f"{slug} was analysed with a {repo_params.get('window_days')}-day window; "
                    f"--months {months} needs {mode.window_days} days",
                    file=sys.stderr,
                )
                return 1
            if params is not None and repo_params != params:
                print("cannot pool analyses made with different parameters", file=sys.stderr)
                return 1
            params = repo_params
            cutoff = snapshot - timedelta(days=mode.cutoff_days)
            checks.append(validation.check_repo(slug, prs, snapshot, cutoff, repo_params, capped))
    # load_repo's "not analysed" LookupError arrives as a DatabaseError from db.connect
    except (GitHubError, DatabaseError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if params is None:  # pragma: no cover - at least one repository was loaded
        return 1
    pooled = validation.pool(checks, resamples=RESAMPLES, seed=SEED)
    flags = "" if months == 12 else f" --months {months}"
    command = f"python -m repocompass validate{flags} {' '.join(repos)}"
    summary = write_results(checks, pooled, params, mode.cutoff_days, Path(mode.out_dir), command)
    print(summary.read_text(encoding="utf-8"))
    return 0
