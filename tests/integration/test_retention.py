"""TASK-1108 - Retention as Code (HARDENING 5.6, PRD 44, PRD 45).

Verifies that:
1. Active family archive memories never expire (Rule 1).
2. Ephemeral upload spools (>24h) are pruned (Rule 2).
3. Soft-deleted records (>30 days) are unlinked from SQLite and purged from disk (Rule 3).
4. Expired pairing requests and tokens (>15m) are pruned (Rule 4).
5. Functions reliably with GuardedConnection and real migrated schema.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.application.retention import RetentionEngine


def test_active_memories_never_expire(tmp_path: Path):
    conn = connect(str(tmp_path / "retention_active.db"))
    migrate(conn)

    # Seed family and an active memory from 5 years ago
    conn.execute("INSERT INTO family VALUES ('fam-1', 'Our family', '2020-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO member VALUES ('mem-1', 'fam-1', 'Papa', 'PARENT')")

    old_active_date = (datetime.now(UTC) - timedelta(days=1825)).isoformat()
    conn.execute(
        """
        INSERT INTO spark (
            id, family_id, owner_id, title, source_kind, intent_value, intent_source,
            intent_confidence, intent_overridden, category_value, category_source,
            category_confidence, category_overridden, status, visibility, created_at, updated_at
        ) VALUES (
            'spk-active-1', 'fam-1', 'mem-1', 'Leo said dada', 'TEXT', 'CAPTURE', 'INFERRED',
            1.0, 0, 'MILESTONE', 'INFERRED', 1.0, 0, 'ACTIVE', 'ACTIVE', ?, ?
        )
        """,
        (old_active_date, old_active_date),
    )

    engine = RetentionEngine(conn, tmp_path / "media", tmp_path / "spool")
    summary = engine.run_retention_cycle()

    assert summary.purged_soft_deleted_records == 0

    # Ensure active memory is still present in database
    row = conn.execute("SELECT id, title FROM spark WHERE id = 'spk-active-1'").fetchone()
    assert row is not None
    assert row["title"] == "Leo said dada"


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

    conn = connect(str(tmp_path / "retention_spool.db"))
    migrate(conn)

    engine = RetentionEngine(conn, tmp_path / "media", spool_dir)
    purged_count, reclaimed_bytes = engine.prune_ephemeral_upload_spools(max_age_hours=24)

    assert purged_count == 1
    assert reclaimed_bytes == 1024
    assert not old_file.exists()
    assert fresh_file.exists()


def test_soft_deleted_records_purged_after_grace_period(tmp_path: Path):
    conn = connect(str(tmp_path / "retention_del.db"))
    migrate(conn)

    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True)
    stored_media = media_dir / "fam-1/ab/abcd123"
    stored_media.parent.mkdir(parents=True)
    stored_media.write_bytes(b"Encrypted media bytes to be deleted" * 10)

    conn.execute("INSERT INTO family VALUES ('fam-1', 'Our family', '2020-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO member VALUES ('mem-1', 'fam-1', 'Papa', 'PARENT')")
    conn.execute(
        """
        INSERT INTO media VALUES (
            'med-deleted', 'fam-1', 'PHOTO', 'image/jpeg', 350, 'abcd123',
            'fam-1/ab/abcd123', 1, '2025-01-01T00:00:00+00:00'
        )
        """
    )

    # Deleted 40 days ago (> 30 days) -> Should be purged
    old_del_date = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    conn.execute(
        """
        INSERT INTO spark (
            id, family_id, owner_id, title, source_kind, source_media_id,
            intent_value, intent_source, intent_confidence, intent_overridden,
            category_value, category_source, category_confidence, category_overridden,
            status, visibility, created_at, updated_at
        ) VALUES (
            'spk-old-del', 'fam-1', 'mem-1', 'Deleted memory', 'PHOTO', 'med-deleted',
            'CAPTURE', 'INFERRED', 1.0, 0, 'MILESTONE', 'INFERRED', 1.0, 0,
            'ACTIVE', 'DELETED', ?, ?
        )
        """,
        (old_del_date, old_del_date),
    )

    # Deleted 5 days ago (< 30 days) -> In grace period, must NOT be purged
    fresh_del_date = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    conn.execute(
        """
        INSERT INTO spark (
            id, family_id, owner_id, title, source_kind,
            intent_value, intent_source, intent_confidence, intent_overridden,
            category_value, category_source, category_confidence, category_overridden,
            status, visibility, created_at, updated_at
        ) VALUES (
            'spk-fresh-del', 'fam-1', 'mem-1', 'Recent deleted memory', 'TEXT',
            'CAPTURE', 'INFERRED', 1.0, 0, 'MILESTONE', 'INFERRED', 1.0, 0,
            'ACTIVE', 'DELETED', ?, ?
        )
        """,
        (fresh_del_date, fresh_del_date),
    )

    engine = RetentionEngine(conn, media_dir, tmp_path / "spool")
    purged_count, reclaimed_bytes = engine.prune_soft_deleted_records(grace_days=30)

    assert purged_count == 1
    assert reclaimed_bytes > 0
    assert not stored_media.exists()

    # Assert old spark removed
    assert conn.execute("SELECT id FROM spark WHERE id = 'spk-old-del'").fetchone() is None
    # Assert fresh spark still in grace period
    assert conn.execute("SELECT id FROM spark WHERE id = 'spk-fresh-del'").fetchone() is not None


def test_expired_auth_tokens_purged(tmp_path: Path):
    conn = connect(str(tmp_path / "retention_auth.db"))
    migrate(conn)

    conn.execute("INSERT INTO family VALUES ('fam-1', 'Our family', '2020-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO member VALUES ('mem-1', 'fam-1', 'Papa', 'PARENT')")

    # Expired 30 mins ago
    old_time = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    conn.execute(
        "INSERT INTO pairing_request VALUES ('fp-old-expired', 'fam-1', 'mem-1', ?, ?, NULL)",
        (old_time, old_time),
    )

    # Active code expiring in 10 mins
    future_time = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    conn.execute(
        "INSERT INTO pairing_request VALUES ('fp-active', 'fam-1', 'mem-1', ?, ?, NULL)",
        (old_time, future_time),
    )

    engine = RetentionEngine(conn, tmp_path / "media", tmp_path / "spool")
    purged = engine.prune_expired_auth_tokens(max_age_minutes=15)

    assert purged == 1
    q_old = "SELECT code_fingerprint FROM pairing_request WHERE code_fingerprint = 'fp-old-expired'"
    assert conn.execute(q_old).fetchone() is None
    q_active = "SELECT code_fingerprint FROM pairing_request WHERE code_fingerprint = 'fp-active'"
    assert conn.execute(q_active).fetchone() is not None
