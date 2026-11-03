"""Configuration loading.

Secrets live only in the environment (loaded from .env). They are never written to
a repr, a log line or an error message: validation failures name the key that is
wrong and never quote its value back.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

__all__ = ["ConfigError", "Settings", "load_env_file", "load_settings"]

PREFIX: Final = "REPOCOMPASS_"
ENV_FILENAME: Final = ".env"

DEFAULT_EXCLUDED_DIRS: Final[tuple[str, ...]] = (
    "vendor",
    "third_party",
    "node_modules",
    "LICENSES",
    "CHANGELOG",
)
DEFAULT_BOT_LOGINS: Final[tuple[str, ...]] = (
    "dependabot",
    "renovate",
    "github-actions",
    "k8s-ci-robot",
    "codecov",
)
ALLOWED_DB_SCHEMES: Final = ("postgresql://", "postgres://")


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid. Never contains a secret."""


@dataclass(frozen=True)
class Settings:
    """Resolved configuration. Secret fields are left out of repr and str."""

    github_token: str = field(repr=False)
    database_url: str = field(repr=False)

    # Metric parameters. Defaults come from docs/BRIEF.md.
    window_days: int = 365
    maturity_days: int = 30
    monthly_sample_cap: int = 250
    min_sample: int = 10
    stale_open_days: int = 90
    author_concentration_threshold: float = 0.30
    formal_review_coverage_threshold: float = 0.50
    area_threshold_share: float = 0.25
    area_max_depth: int = 4
    wilson_z: float = 1.959963985

    # Area activity. "Recent" is the brief's 90-day activity window. A sweep commit
    # (formatting, licence headers, mass renames) touches more than `sweep_area_share`
    # of all areas AND at least `sweep_min_areas` areas. It is ignored, because it says
    # nothing about where work is happening. The minimum keeps ordinary "code + tests"
    # commits in small repositories from counting as sweeps.
    activity_recent_days: int = 90
    sweep_area_share: float = 0.50
    sweep_min_areas: int = 5

    excluded_dirs: tuple[str, ...] = DEFAULT_EXCLUDED_DIRS
    bot_logins: tuple[str, ...] = DEFAULT_BOT_LOGINS

    # Where blobless clones are kept, relative to the working directory.
    clone_dir: str = "data/repos"

    def is_bot_login(self, login: str | None) -> bool:
        """A missing login means a deleted or unknown actor: exclude rather than guess."""
        if not login:
            return True
        lowered = login.strip().lower()
        if lowered.endswith("[bot]"):
            return True
        return lowered in {b.lower() for b in self.bot_logins}


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Parse a .env file into a dict. Missing file is not an error.

    Deliberately minimal: KEY=VALUE per line, '#' comments, optional surrounding
    quotes. No interpolation and no export syntax, so there is nothing surprising
    about how a secret is read.
    """
    target = path or (Path.cwd() / ENV_FILENAME)
    if not target.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in target.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _required(env: Mapping[str, str], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise ConfigError(f"{key} is missing or empty; set it in .env")
    return value


def _int(env: Mapping[str, str], suffix: str, default: int, *, minimum: int = 1) -> int:
    key = PREFIX + suffix
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{key} must be a whole number") from None
    if value < minimum:
        raise ConfigError(f"{key} must be at least {minimum}")
    return value


def _share(env: Mapping[str, str], suffix: str, default: float) -> float:
    key = PREFIX + suffix
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        raise ConfigError(f"{key} must be a number between 0 and 1") from None
    if not 0.0 < value <= 1.0:
        raise ConfigError(f"{key} must be between 0 and 1")
    return value


def _tuple(env: Mapping[str, str], suffix: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = env.get(PREFIX + suffix)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from a mapping, or from .env overlaid by the real environment.

    The process environment wins over .env, so a shell override works as expected.
    """
    if env is None:
        import os

        env = {**load_env_file(), **os.environ}

    github_token = _required(env, "GITHUB_TOKEN")
    database_url = _required(env, "DATABASE_URL")
    if not database_url.startswith(ALLOWED_DB_SCHEMES):
        # deliberately does not echo the value
        raise ConfigError("DATABASE_URL must be a postgresql:// connection string")

    return Settings(
        github_token=github_token,
        database_url=database_url,
        window_days=_int(env, "WINDOW_DAYS", 365),
        maturity_days=_int(env, "MATURITY_DAYS", 30),
        monthly_sample_cap=_int(env, "MONTHLY_SAMPLE_CAP", 250),
        min_sample=_int(env, "MIN_SAMPLE", 10),
        stale_open_days=_int(env, "STALE_OPEN_DAYS", 90),
        author_concentration_threshold=_share(env, "AUTHOR_CONCENTRATION_THRESHOLD", 0.30),
        formal_review_coverage_threshold=_share(env, "FORMAL_REVIEW_COVERAGE_THRESHOLD", 0.50),
        area_threshold_share=_share(env, "AREA_THRESHOLD_SHARE", 0.25),
        area_max_depth=_int(env, "AREA_MAX_DEPTH", 4),
        activity_recent_days=_int(env, "ACTIVITY_RECENT_DAYS", 90),
        sweep_area_share=_share(env, "SWEEP_AREA_SHARE", 0.50),
        sweep_min_areas=_int(env, "SWEEP_MIN_AREAS", 5, minimum=2),
        excluded_dirs=_tuple(env, "EXCLUDED_DIRS", DEFAULT_EXCLUDED_DIRS),
        bot_logins=_tuple(env, "BOT_LOGINS", DEFAULT_BOT_LOGINS),
        clone_dir=(env.get(PREFIX + "CLONE_DIR") or "").strip() or "data/repos",
    )
