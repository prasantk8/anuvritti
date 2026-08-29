"""TASK-1109 - Secrets by Twelve-Factor & Image Layer Scanner (HARDENING 5.3, PRD 44).

Verifies that:
1. Production environment refuses to start without a valid, high-entropy key.
2. Known insecure/test keys trigger InsecureSecretError.
3. Filesystem and tar layer secret scanners catch embedded keys, Fernet secrets, and .env files.
4. Production repo remains clean of hardcoded credentials.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from scripts.scan_image import scan_directory, scan_docker_tar

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

    # 3. Create a hardcoded Fernet key file
    dummy_fernet = Fernet.generate_key().decode()
    bad_fernet_file = tmp_path / "config.py"
    bad_fernet_file.write_text(f"ANUVRITTI_MEDIA_KEY = '{dummy_fernet}'")

    violations = scan_directory(tmp_path)
    assert len(violations) >= 3
    assert any("Private Key Header" in v for v in violations)
    assert any(".env.local" in v for v in violations)
    assert any("Fernet Media Encryption Key" in v for v in violations)


def test_tar_layer_scanner_catches_secrets_in_layers(tmp_path: Path):
    # Construct a mock docker image tar with an inner layer.tar containing a leaked key
    tar_path = tmp_path / "mock_image.tar"

    # Inner layer
    layer_bytes = io.BytesIO()
    with tarfile.open(fileobj=layer_bytes, mode="w") as inner:
        secret_data = (
            b"-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        )
        ti = tarfile.TarInfo(name="app/leaked.pem")
        ti.size = len(secret_data)
        inner.addfile(ti, io.BytesIO(secret_data))

    layer_bytes.seek(0)
    layer_tar_content = layer_bytes.read()

    # Outer image tar
    with tarfile.open(tar_path, mode="w") as outer:
        ti = tarfile.TarInfo(name="abc123/layer.tar")
        ti.size = len(layer_tar_content)
        outer.addfile(ti, io.BytesIO(layer_tar_content))

    violations = scan_docker_tar(tar_path)
    assert len(violations) >= 1
    assert any("Private Key Header" in v for v in violations)


def test_scanner_passes_on_clean_repository():
    violations = scan_directory(ROOT)
    assert violations == [], f"Found unexpected secrets in repository: {violations}"
