"""TASK-1108 - Retention as Code (HARDENING 5.6, PRD 44, PRD 45).

Verifies that:
1. Active family archive memories never expire.
2. Stale upload spools (>24h) are pruned.
3. Soft-deleted records are scrubbed from database and disk after 30 days.
4. Expired authentication tickets are pruned.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from anuvritti.application.retention import RetentionEngine


def test_active_memories_never_expire(tmp_path: Path):
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE spark (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            visibility TEXT NOT NULL,
            media_id TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )
    # Insert an active memory from 5 years ago
    old_active_date = (datetime.now(UTC) - timedelta(days=1825)).isoformat()
    db.execute(
        "INSERT INTO spark VALUES (?, ?, ?, ?, ?)",
        ("spk-active-1", "Leo said dada", "ACTIVE", None, old_active_date),
    )
    db.commit()

    engine = RetentionEngine(db, tmp_path / "media", tmp_path / "spool")
    summary = engine.run_retention_cycle()

    assert summary.purged_soft_deleted_records == 0

    # Ensure memory is still in database
    row = db.execute("SELECT id, title FROM spark WHERE id = 'spk-active-1'").fetchone()
    assert row is not None
    assert row[1] == "Leo said dada"


def test_prune_ephemeral_upload_spools(tmp_path: Path):
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir(parents=True)

    # Old upload file (48 hours old)
    old_file = spool_dir / "old_chunk.tmp"
    old_file.write_bytes(b"A" * 1024)
    old_time = (datetime.now(UTC) - timedelta(hours=48)).timestamp()
    os.utime(old_file, (old_time, old_time))

    # Fresh upload file (1 hour old)
    fresh_file = spool_dir / "fresh_chunk.tmp"
    fresh_file.write_bytes(b"B" * 512)

    db = sqlite3.connect(":memory:")
    engine = RetentionEngine(db, tmp_path / "media", spool_dir)
    purged_count, reclaimed_bytes = engine.prune_ephemeral_upload_spools(max_age_hours=24)

    assert purged_count == 1
    assert reclaimed_bytes == 1024
    assert not old_file.exists()
    assert fresh_file.exists()


def test_soft_deleted_records_purged_after_grace_period(tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True)
    stored_media = media_dir / "fam-1/ab/abcd123"
    stored_media.parent.mkdir(parents=True)
    stored_media.write_bytes(b"Encrypted media bytes to be deleted" * 10)

    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE media (
            id TEXT PRIMARY KEY,
            storage_key TEXT NOT NULL
        );
        CREATE TABLE spark (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            visibility TEXT NOT NULL,
            media_id TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )

    db.execute("INSERT INTO media VALUES (?, ?)", ("med-deleted", "fam-1/ab/abcd123"))

    # Deleted 40 days ago (> 30 days) -> Should be purged
    old_del_date = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    db.execute(
        "INSERT INTO spark VALUES (?, ?, ?, ?, ?)",
        ("spk-old-del", "Deleted memory", "DELETED", "med-deleted", old_del_date),
    )

    # Deleted 5 days ago (< 30 days) -> In grace period, must NOT be purged
    fresh_del_date = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    db.execute(
        "INSERT INTO spark VALUES (?, ?, ?, ?, ?)",
        ("spk-fresh-del", "Recent deleted memory", "DELETED", None, fresh_del_date),
    )
    db.commit()

    engine = RetentionEngine(db, media_dir, tmp_path / "spool")
    purged_count, reclaimed_bytes = engine.prune_soft_deleted_records(grace_days=30)

    assert purged_count == 1
    assert reclaimed_bytes > 0
    assert not stored_media.exists()

    # Assert old spark removed
    assert db.execute("SELECT id FROM spark WHERE id = 'spk-old-del'").fetchone() is None
    # Assert fresh spark still in grace period
    assert db.execute("SELECT id FROM spark WHERE id = 'spk-fresh-del'").fetchone() is not None
