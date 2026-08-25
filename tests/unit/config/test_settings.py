"""TASK-103 - 12-factor settings. PRD 44: privacy is architecture, so config is tested."""

from __future__ import annotations

import pytest

from anuvritti.config.settings import Environment, Settings, load_settings
from anuvritti.shared.errors import ErrorCode


def _env(**overrides: str) -> dict[str, str]:
    base = {
        "ANUVRITTI_ENV": "development",
        "ANUVRITTI_DB_PATH": "var/test.db",
        "ANUVRITTI_MEDIA_DIR": "var/media",
        "ANUVRITTI_MEDIA_KEY": "b" * 43 + "=",
    }
    base.update(overrides)
    return base


class TestDefaults:
    def test_loads_from_environment_only(self):
        settings = load_settings(_env()).unwrap()
        assert settings.environment is Environment.DEVELOPMENT
        assert settings.db_path.name == "test.db"

    def test_return_engine_defaults_match_the_architecture_doc(self):
        s = load_settings(_env()).unwrap()
        assert s.max_suggestions_per_day == 3
        assert s.snooze_cooldown_days == 30
        assert 0.0 < s.suggestion_threshold < 1.0

    def test_media_limits_have_safe_defaults(self):
        s = load_settings(_env()).unwrap()
        assert s.max_media_bytes == 25 * 1024 * 1024
        assert "image/jpeg" in s.allowed_media_types
        assert "text/html" not in s.allowed_media_types


class TestValidation:
    def test_unknown_environment_is_rejected(self):
        err = load_settings(_env(ANUVRITTI_ENV="staging-ish")).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_non_numeric_integer_setting_is_rejected(self):
        err = load_settings(_env(ANUVRITTI_MAX_SUGGESTIONS_PER_DAY="lots")).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_suggestion_cap_must_be_positive(self):
        assert load_settings(_env(ANUVRITTI_MAX_SUGGESTIONS_PER_DAY="0")).is_err()

    def test_threshold_out_of_range_is_rejected(self):
        assert load_settings(_env(ANUVRITTI_SUGGESTION_THRESHOLD="1.4")).is_err()


class TestProductionSafety:
    def test_production_requires_a_media_encryption_key(self):
        """PRD 44 - encryption at rest is not optional."""
        env = _env(ANUVRITTI_ENV="production")
        del env["ANUVRITTI_MEDIA_KEY"]
        err = load_settings(env).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED
        assert "ANUVRITTI_MEDIA_KEY" in err.message

    def test_production_refuses_to_boot_without_tls(self):
        """PRD 44 - encryption in transit is not optional."""
        env = _env(ANUVRITTI_ENV="production", ANUVRITTI_TLS_REQUIRED="false")
        err = load_settings(env).unwrap_err()
        assert "TLS" in err.message

    def test_development_may_run_without_a_key(self):
        env = _env()
        del env["ANUVRITTI_MEDIA_KEY"]
        assert load_settings(env).unwrap().media_key is None

    def test_production_disables_api_docs(self):
        s = load_settings(_env(ANUVRITTI_ENV="production")).unwrap()
        assert s.expose_api_docs is False


class TestSecretHygiene:
    def test_settings_repr_never_leaks_the_key(self):
        s = load_settings(_env()).unwrap()
        assert "b" * 43 not in repr(s)
        assert "REDACTED" in repr(s)

    def test_settings_are_immutable(self):
        s = load_settings(_env()).unwrap()
        with pytest.raises(AttributeError):
            s.max_suggestions_per_day = 99  # type: ignore[misc]

    def test_env_example_documents_every_setting(self):
        """A setting nobody knows exists is a production incident waiting to happen."""
        from pathlib import Path

        example = Path(__file__).resolve().parents[3] / ".env.example"
        text = example.read_text()
        for key in Settings.documented_keys():
            assert key in text, f"{key} missing from .env.example"


class TestQuietPeriodSetting:
    def test_the_quiet_period_defaults_to_a_week(self):
        """PRD 8.5 - nothing saved this week is "brought back" as if forgotten."""
        assert load_settings(_env()).unwrap().min_days_before_return == 7

    def test_it_can_be_tuned(self):
        settings = load_settings(_env(ANUVRITTI_MIN_DAYS_BEFORE_RETURN="30")).unwrap()
        assert settings.min_days_before_return == 30

    def test_it_may_be_disabled_but_never_negative(self):
        assert load_settings(_env(ANUVRITTI_MIN_DAYS_BEFORE_RETURN="0")).is_ok()
        assert load_settings(_env(ANUVRITTI_MIN_DAYS_BEFORE_RETURN="-1")).is_err()
