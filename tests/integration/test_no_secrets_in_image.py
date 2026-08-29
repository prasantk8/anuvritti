"""TASK-1109 - Secrets by Twelve-Factor & Image Scanner (HARDENING 5.3, PRD 44).

Verifies that:
1. Production environment refuses to start without a valid, high-entropy key.
2. Known insecure/test keys trigger InsecureSecretError.
3. Filesystem secret scanner catches embedded keys and .env files.
4. Production repo remains clean of hardcoded credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from scripts.scan_image import scan_directory

from anuvritti.config.secrets_guard import (
    InsecureSecretError,
    validate_production_secrets,
)

ROOT = Path(__file__).resolve().parents[2]


def test_production_refuses_to_start_without_media_key():
    with pytest.raises(InsecureSecretError, match="ANUVRITTI_MEDIA_KEY is required"):
        validate_production_secrets({"ANUVRITTI_ENV": "production"})


def test_production_refuses_insecure_test_keys():
    insecure_keys = ["test-key", "dummy-secret-123", "00000000000000000000000000000000", "changeme"]
    for key in insecure_keys:
        with pytest.raises(InsecureSecretError, match="insecure pattern"):
            validate_production_secrets(
                {
                    "ANUVRITTI_ENV": "production",
                    "ANUVRITTI_MEDIA_KEY": key,
                }
            )


def test_production_accepts_valid_fernet_key():
    valid_key = Fernet.generate_key().decode()
    # Should not raise
    validate_production_secrets(
        {
            "ANUVRITTI_ENV": "production",
            "ANUVRITTI_MEDIA_KEY": valid_key,
        }
    )


def test_scanner_catches_embedded_secrets(tmp_path: Path):
    # 1. Create a dummy file with an RSA private key header
    bad_key_file = tmp_path / "leaked_id_rsa"
    bad_key_file.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    )

    # 2. Create a .env file
    bad_env_file = tmp_path / ".env.local"
    bad_env_file.write_text("SECRET_KEY=12345")

    violations = scan_directory(tmp_path)
    assert len(violations) == 2
    assert any("Private Key Header" in v for v in violations)
    assert any(".env.local" in v for v in violations)


def test_scanner_passes_on_clean_repository():
    violations = scan_directory(ROOT)
    assert violations == [], f"Found unexpected secrets in repository: {violations}"
