"""Tests for configuration loading, defaults and secret handling."""

from __future__ import annotations

import dataclasses

import pytest

from repocompass.config import ConfigError, Settings, load_settings

ENV = {
    "GITHUB_TOKEN": "token-value-must-not-leak",
    "DATABASE_URL": "postgresql://user:password-must-not-leak@host/db",
}


def test_loads_required_values() -> None:
    settings = load_settings(ENV)
    assert settings.github_token == ENV["GITHUB_TOKEN"]
    assert settings.database_url == ENV["DATABASE_URL"]


def test_missing_github_token_is_an_error() -> None:
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        load_settings({"DATABASE_URL": ENV["DATABASE_URL"]})


def test_missing_database_url_is_an_error() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_settings({"GITHUB_TOKEN": ENV["GITHUB_TOKEN"]})


def test_blank_value_is_treated_as_missing() -> None:
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        load_settings({"GITHUB_TOKEN": "   ", "DATABASE_URL": ENV["DATABASE_URL"]})


@pytest.mark.parametrize("render", [repr, str])
def test_secrets_never_appear_in_repr_or_str(render) -> None:
    settings = load_settings(ENV)
    rendered = render(settings)
    assert "token-value-must-not-leak" not in rendered
    assert "password-must-not-leak" not in rendered
    assert "github_token" not in rendered
    assert "database_url" not in rendered


def test_error_message_never_echoes_a_secret() -> None:
    """A malformed URL must not be quoted back into the exception text."""
    with pytest.raises(ConfigError) as excinfo:
        load_settings(
            {"GITHUB_TOKEN": ENV["GITHUB_TOKEN"], "DATABASE_URL": "nonsense://x:secret@h/d"}
        )
    assert "secret" not in str(excinfo.value)


def test_rejects_non_postgres_database_url() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_settings({"GITHUB_TOKEN": ENV["GITHUB_TOKEN"], "DATABASE_URL": "mysql://h/d"})


def test_metric_defaults_match_the_brief() -> None:
    s = load_settings(ENV)
    assert s.window_days == 365
    assert s.maturity_days == 30
    assert s.monthly_sample_cap == 250
    assert s.min_sample == 10
    assert s.stale_open_days == 90
    assert s.no_response_days == 30
    assert s.author_concentration_threshold == pytest.approx(0.30)
    assert s.formal_review_coverage_threshold == pytest.approx(0.50)
    assert s.area_threshold_share == pytest.approx(0.25)
    assert s.area_max_depth == 4
    assert s.wilson_z == pytest.approx(1.959963985, rel=1e-9)
    assert s.activity_recent_days == 90
    assert s.sweep_area_share == pytest.approx(0.50)
    assert s.sweep_min_areas == 5
    assert s.clone_dir == "data/repos"
    assert s.web_origins == ("http://localhost:3000", "http://127.0.0.1:3000")


def test_no_response_window_longer_than_maturity_is_rejected() -> None:
    with pytest.raises(ConfigError, match="NO_RESPONSE_DAYS"):
        load_settings({**ENV, "REPOCOMPASS_NO_RESPONSE_DAYS": "60"})


def test_web_origins_can_be_set_but_never_to_a_wildcard() -> None:
    s = load_settings({**ENV, "REPOCOMPASS_WEB_ORIGINS": "http://localhost:4000"})
    assert s.web_origins == ("http://localhost:4000",)
    with pytest.raises(ConfigError, match="WEB_ORIGINS"):
        load_settings({**ENV, "REPOCOMPASS_WEB_ORIGINS": "*"})


def test_sweep_minimum_below_two_is_rejected() -> None:
    """A minimum of one would make single-area commits sweeps in a one-area repository."""
    with pytest.raises(ConfigError, match="SWEEP_MIN_AREAS"):
        load_settings({**ENV, "REPOCOMPASS_SWEEP_MIN_AREAS": "1"})


def test_excluded_dirs_and_bots_have_sensible_defaults() -> None:
    s = load_settings(ENV)
    assert "vendor" in s.excluded_dirs
    assert "third_party" in s.excluded_dirs
    assert "node_modules" in s.excluded_dirs
    assert "dependabot" in s.bot_logins
    assert "renovate" in s.bot_logins


def test_numeric_overrides_are_parsed() -> None:
    s = load_settings(
        {**ENV, "REPOCOMPASS_MONTHLY_SAMPLE_CAP": "100", "REPOCOMPASS_MIN_SAMPLE": "5"}
    )
    assert s.monthly_sample_cap == 100
    assert s.min_sample == 5


def test_list_overrides_are_parsed_and_trimmed() -> None:
    s = load_settings({**ENV, "REPOCOMPASS_EXCLUDED_DIRS": "vendor, build ,dist"})
    assert s.excluded_dirs == ("vendor", "build", "dist")


def test_bad_numeric_override_is_rejected() -> None:
    with pytest.raises(ConfigError, match="REPOCOMPASS_MIN_SAMPLE"):
        load_settings({**ENV, "REPOCOMPASS_MIN_SAMPLE": "ten"})


def test_out_of_range_share_is_rejected() -> None:
    with pytest.raises(ConfigError, match="AUTHOR_CONCENTRATION"):
        load_settings({**ENV, "REPOCOMPASS_AUTHOR_CONCENTRATION_THRESHOLD": "1.5"})


def test_settings_are_frozen() -> None:
    s = load_settings(ENV)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.min_sample = 99  # type: ignore[misc]


def test_is_bot_matches_suffix_and_list_case_insensitively() -> None:
    s = load_settings(ENV)
    assert s.is_bot_login("dependabot[bot]")
    assert s.is_bot_login("Dependabot")
    assert s.is_bot_login("RENOVATE")
    assert not s.is_bot_login("kludex")


def test_unknown_author_counts_as_bot() -> None:
    """A deleted account has no login; exclude it rather than guess."""
    assert load_settings(ENV).is_bot_login(None) is True


def test_settings_type() -> None:
    assert isinstance(load_settings(ENV), Settings)
