"""12-factor configuration.

Every setting comes from the environment. Nothing is read from a file in the repository, and
no default is ever a secret. PRD 44 makes privacy an architectural concern, so the settings
loader refuses to start a production process that cannot honour it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Final

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


DEFAULT_ALLOWED_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "audio/mpeg",
        "audio/mp4",
        "audio/aac",
        "audio/wav",
        "audio/webm",
    }
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable, fully-resolved runtime configuration."""

    environment: Environment
    db_path: Path
    media_dir: Path
    media_key: str | None
    log_level: str
    tls_required: bool
    expose_api_docs: bool
    max_media_bytes: int
    allowed_media_types: frozenset[str]
    max_suggestions_per_day: int
    snooze_cooldown_days: int
    suggestion_threshold: float
    maturation_horizon_days: int
    min_days_before_return: int
    documented: bool = field(default=True, repr=False)

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    def __repr__(self) -> str:
        """Never let a key reach a log line, a crash report or a screenshot."""
        shown = ", ".join(
            f"{f.name}={'REDACTED' if f.name == 'media_key' else getattr(self, f.name)!r}"
            for f in fields(self)
            if f.repr
        )
        return f"Settings({shown})"

    @staticmethod
    def documented_keys() -> tuple[str, ...]:
        return (
            "ANUVRITTI_ENV",
            "ANUVRITTI_DB_PATH",
            "ANUVRITTI_MEDIA_DIR",
            "ANUVRITTI_MEDIA_KEY",
            "ANUVRITTI_LOG_LEVEL",
            "ANUVRITTI_TLS_REQUIRED",
            "ANUVRITTI_MAX_MEDIA_BYTES",
            "ANUVRITTI_MAX_SUGGESTIONS_PER_DAY",
            "ANUVRITTI_SNOOZE_COOLDOWN_DAYS",
            "ANUVRITTI_SUGGESTION_THRESHOLD",
            "ANUVRITTI_MATURATION_HORIZON_DAYS",
            "ANUVRITTI_MIN_DAYS_BEFORE_RETURN",
        )


def _invalid(message: str, **details: object) -> Err[DomainError]:
    return Err(DomainError(ErrorCode.VALIDATION_FAILED, message, details))


def _read_int(env: dict[str, str], key: str, default: int, minimum: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise _SettingsError(f"{key} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise _SettingsError(f"{key} must be >= {minimum}, got {value}")
    return value


def _read_float(env: dict[str, str], key: str, default: float, lo: float, hi: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise _SettingsError(f"{key} must be a number, got {raw!r}") from exc
    if not lo <= value <= hi:
        raise _SettingsError(f"{key} must be between {lo} and {hi}, got {value}")
    return value


def _read_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise _SettingsError(f"{key} must be a boolean, got {raw!r}")


class _SettingsError(Exception):
    """Internal control flow only - converted to an `Err` before crossing the boundary."""


def load_settings(env: dict[str, str]) -> Result[Settings, DomainError]:
    """Build settings from an environment mapping. Never touches `os.environ` implicitly."""
    raw_env = env.get("ANUVRITTI_ENV", Environment.DEVELOPMENT.value).strip().lower()
    try:
        environment = Environment(raw_env)
    except ValueError:
        return _invalid(
            f"ANUVRITTI_ENV must be one of {[e.value for e in Environment]}, got {raw_env!r}",
            provided=raw_env,
        )

    try:
        max_media_bytes = _read_int(env, "ANUVRITTI_MAX_MEDIA_BYTES", 25 * 1024 * 1024, 1)
        max_suggestions = _read_int(env, "ANUVRITTI_MAX_SUGGESTIONS_PER_DAY", 3, 1)
        cooldown_days = _read_int(env, "ANUVRITTI_SNOOZE_COOLDOWN_DAYS", 30, 1)
        horizon_days = _read_int(env, "ANUVRITTI_MATURATION_HORIZON_DAYS", 180, 1)
        min_days_before_return = _read_int(env, "ANUVRITTI_MIN_DAYS_BEFORE_RETURN", 7, 0)
        threshold = _read_float(env, "ANUVRITTI_SUGGESTION_THRESHOLD", 0.45, 0.0, 1.0)
        tls_required = _read_bool(env, "ANUVRITTI_TLS_REQUIRED", True)
    except _SettingsError as exc:
        return _invalid(str(exc))

    media_key = env.get("ANUVRITTI_MEDIA_KEY") or None
    is_production = environment is Environment.PRODUCTION

    if is_production and media_key is None:
        return _invalid(
            "ANUVRITTI_MEDIA_KEY is required in production - PRD 44 requires "
            "encryption at rest for family media"
        )
    if is_production and not tls_required:
        return _invalid(
            "TLS cannot be disabled in production - PRD 44 requires encryption in transit"
        )

    return Ok(
        Settings(
            environment=environment,
            db_path=Path(env.get("ANUVRITTI_DB_PATH", "var/anuvritti.db")),
            media_dir=Path(env.get("ANUVRITTI_MEDIA_DIR", "var/media")),
            media_key=media_key,
            log_level=env.get("ANUVRITTI_LOG_LEVEL", "INFO").upper(),
            tls_required=tls_required,
            expose_api_docs=not is_production,
            max_media_bytes=max_media_bytes,
            allowed_media_types=DEFAULT_ALLOWED_MEDIA_TYPES,
            max_suggestions_per_day=max_suggestions,
            snooze_cooldown_days=cooldown_days,
            suggestion_threshold=threshold,
            maturation_horizon_days=horizon_days,
            min_days_before_return=min_days_before_return,
        )
    )
