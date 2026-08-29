"""TASK-1111 - Scheduled Restore Drill (HARDENING 5.4, PRD 8.6).

Verifies that:
1. Automated restore drill proves SQLite integrity in a scratch environment.
2. Every encrypted media file is decrypted and verified against its SHA-256 hash.
3. Corrupted backups or missing media are detected and flagged.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from scripts.restore_drill import run_restore_drill


def create_sample_backup(base_dir: Path) -> tuple[Path, Path, str]:
    db_path = base_dir / "anuvritti_backup.db"
    media_dir = base_dir / "media_backup"
    media_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode()
    fernet = Fernet(key.encode())

    # Create and populate database
    db = sqlite3.connect(db_path)
    db.executescript(
        """
        CREATE TABLE spark (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL
        );
        CREATE TABLE media (
            id TEXT PRIMARY KEY,
            storage_key TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            encrypted INTEGER NOT NULL
        );
        """
    )

    db.execute("INSERT INTO spark VALUES ('spk-1', 'First steps')")

    # Create 2 media files
    photo1_content = b"\xff\xd8\xff\xe0 photo one content"
    photo1_hash = hashlib.sha256(photo1_content).hexdigest()
    photo1_key = "fam-1/ab/photo1.jpg"
    p1_path = media_dir / photo1_key
    p1_path.parent.mkdir(parents=True, exist_ok=True)
    p1_path.write_bytes(fernet.encrypt(photo1_content))

    photo2_content = b"\xff\xd8\xff\xe0 photo two content"
    photo2_hash = hashlib.sha256(photo2_content).hexdigest()
    photo2_key = "fam-1/cd/photo2.jpg"
    p2_path = media_dir / photo2_key
    p2_path.parent.mkdir(parents=True, exist_ok=True)
    p2_path.write_bytes(fernet.encrypt(photo2_content))

    db.execute("INSERT INTO media VALUES ('med-1', ?, ?, 1)", (photo1_key, photo1_hash))
    db.execute("INSERT INTO media VALUES ('med-2', ?, ?, 1)", (photo2_key, photo2_hash))
    db.commit()
    db.close()

    return db_path, media_dir, key


def test_restore_drill_succeeds_on_valid_backup(tmp_path: Path):
    db_path, media_dir, key = create_sample_backup(tmp_path)

    result = run_restore_drill(db_path, media_dir, key)

    assert result.success is True
    assert result.database_integrity is True
    assert result.total_sparks == 1
    assert result.verified_media_count == 2
    assert result.corrupted_media_count == 0
    assert result.duration_seconds >= 0.0


def test_restore_drill_detects_corrupted_media(tmp_path: Path):
    db_path, media_dir, key = create_sample_backup(tmp_path)

    # Tamper with photo2
    p2_file = media_dir / "fam-1/cd/photo2.jpg"
    p2_file.write_bytes(b"corrupted bytes")

    result = run_restore_drill(db_path, media_dir, key)

    assert result.success is False
    assert result.verified_media_count == 1
    assert result.corrupted_media_count == 1


def test_restore_drill_fails_on_missing_database_file(tmp_path: Path):
    missing_db = tmp_path / "nonexistent.db"
    result = run_restore_drill(missing_db, tmp_path / "media")

    assert result.success is False
    assert result.database_integrity is False
    assert "not found" in (result.error_message or "")
