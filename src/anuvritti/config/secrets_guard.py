"""Twelve-Factor Secrets Guard & Production Key Validator (HARDENING 5.3, PRD 44).

Rules:
1. Twelve-Factor Secrets: Configuration and keys must come strictly from the environment.
2. Insecure Test Key Prohibition: Production refuses to start if any secret looks like
   a default, placeholder, or test credential.
3. Cryptographic Validation: Production encryption keys must be valid base64-encoded
   32-byte Fernet keys.
"""

from __future__ import annotations

import base64
import os

INSECURE_TEST_KEY_PATTERNS = [
    "test",
    "dummy",
    "secret",
    "changeme",
    "default",
    "example",
    "000000",
    "123456",
    "password",
    "admin",
    "dev-key",
]


class InsecureSecretError(RuntimeError):
    """Raised when an insecure placeholder secret is used in production."""


def validate_production_secrets(env: dict[str, str] | None = None) -> None:
    """Validate that production environment uses real, high-entropy secrets."""
    environ = env if env is not None else os.environ

    app_env = environ.get("ANUVRITTI_ENV", "development").lower()
    if app_env != "production":
        return

    # In production, ANUVRITTI_MEDIA_KEY is required
    media_key = environ.get("ANUVRITTI_MEDIA_KEY", "").strip()
    if not media_key:
        raise InsecureSecretError("ANUVRITTI_MEDIA_KEY is required in production (PRD 44)")

    # Check for insecure test key patterns
    media_key_lower = media_key.lower()
    for pattern in INSECURE_TEST_KEY_PATTERNS:
        if pattern in media_key_lower:
            raise InsecureSecretError(
                f"ANUVRITTI_MEDIA_KEY contains insecure pattern '{pattern}' in production"
            )

    # Validate first key (or primary key if comma-separated) is valid Fernet 32-byte base64
    primary_key = media_key.split(",")[0].strip()
    try:
        raw_bytes = base64.urlsafe_b64decode(primary_key)
        if len(raw_bytes) != 32:
            raise InsecureSecretError(
                "ANUVRITTI_MEDIA_KEY must be a base64-encoded 32-byte key "
                f"(got {len(raw_bytes)} bytes)"
            )
    except Exception as exc:
        raise InsecureSecretError(
            f"ANUVRITTI_MEDIA_KEY is not a valid base64-encoded encryption key: {exc}"
        ) from exc
