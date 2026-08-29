"""Retention Policies as Code (HARDENING 5.6, PRD 44, PRD 45).

Retention Rules:
1. Sovereign Family Archive (NEVER EXPIRES): Active sparks, moments, audio, and photos
   are kept permanently until explicitly unlinked by a parent.
2. Ephemeral Upload Spools (TTL: 24 Hours): Incomplete upload chunks and abandoned
   upload sessions older than 24 hours are purged.
3. Soft-Deleted Records (Grace Period: 30 Days): Soft-deleted items are unlinked
   from SQLite and deleted from disk after 30 days.
4. Expired Auth Tokens & Magic Links (TTL: 15 Minutes): Unclaimed pairing tokens
   and expired session tickets are pruned.

NOT IN SERVICE. TASK-1108 is reopened. This module speaks raw SQL from the application
layer, takes a bare `sqlite3.Connection` where the container hands out a
`GuardedConnection`, and names an `auth_token` table and a `spark.media_id` column that
this schema does not have. Nothing constructs it and no scheduler calls it, so rules 2-4
are enforced by nobody. Rule 1 - the archive never expires - is enforced by the absence of
any code that could delete it, which is the only rule here that is currently real.
docs/AGENT-GUIDE.md says what closing this task requires.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class RetentionSummary:
    purged_upload_spools: int
    purged_soft_deleted_records: int
    purged_auth_tokens: int
    reclaimed_bytes: int
    executed_at: datetime


class RetentionEngine:
    """Enforces automated data lifecycle and retention policies."""

    def __init__(
        self,
        db: sqlite3.Connection,
        media_root: Path,
        upload_spool_dir: Path,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._media_root = media_root
        self._upload_spool_dir = upload_spool_dir
        self._now = now_fn

    def prune_ephemeral_upload_spools(self, max_age_hours: int = 24) -> tuple[int, int]:
        """Prune abandoned chunk upload spools older than 24 hours."""
        if not self._upload_spool_dir.exists():
            return 0, 0

        cutoff = self._now() - timedelta(hours=max_age_hours)
        purged_files = 0
        reclaimed_bytes = 0

        for path in self._upload_spool_dir.rglob("*"):
            if path.is_file():
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    size = path.stat().st_size
                    path.unlink(missing_ok=True)
                    purged_files += 1
                    reclaimed_bytes += size

        return purged_files, reclaimed_bytes

    def prune_expired_auth_tokens(self, max_age_minutes: int = 15) -> int:
        """Prune expired pairing codes or bootstrap tokens."""
        cutoff_iso = (self._now() - timedelta(minutes=max_age_minutes)).isoformat()
        cursor = self._db.cursor()
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='auth_token'")
        if not cursor.fetchone():
            return 0

        cursor.execute(
            "DELETE FROM auth_token WHERE expires_at < ? OR (claimed = 1 AND created_at < ?)",
            (cutoff_iso, cutoff_iso),
        )
        self._db.commit()
        return cursor.rowcount

    def prune_soft_deleted_records(self, grace_days: int = 30) -> tuple[int, int]:
        """Permanently purge records marked deleted beyond the 30-day grace window."""
        cutoff_iso = (self._now() - timedelta(days=grace_days)).isoformat()
        cursor = self._db.cursor()
        purged_count = 0
        reclaimed_bytes = 0

        # Check for deleted sparks
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='spark'")
        if cursor.fetchone():
            cursor.execute(
                "SELECT id, media_id FROM spark WHERE visibility = 'DELETED' AND updated_at < ?",
                (cutoff_iso,),
            )
            rows = cursor.fetchall()
            for row in rows:
                spark_id, media_id = row[0], row[1]
                # If media exists, unlink file from disk
                if media_id:
                    cursor.execute("SELECT storage_key FROM media WHERE id = ?", (media_id,))
                    m_row = cursor.fetchone()
                    if m_row:
                        media_path = self._media_root / m_row[0]
                        if media_path.exists():
                            reclaimed_bytes += media_path.stat().st_size
                            media_path.unlink(missing_ok=True)
                        cursor.execute("DELETE FROM media WHERE id = ?", (media_id,))
                cursor.execute("DELETE FROM spark WHERE id = ?", (spark_id,))
                purged_count += 1

        self._db.commit()
        return purged_count, reclaimed_bytes

    def run_retention_cycle(
        self,
        spool_max_age_hours: int = 24,
        deleted_grace_days: int = 30,
        auth_max_age_minutes: int = 15,
    ) -> RetentionSummary:
        """Execute a full retention cycle."""
        spool_files, spool_bytes = self.prune_ephemeral_upload_spools(spool_max_age_hours)
        auth_purged = self.prune_expired_auth_tokens(auth_max_age_minutes)
        deleted_purged, deleted_bytes = self.prune_soft_deleted_records(deleted_grace_days)

        return RetentionSummary(
            purged_upload_spools=spool_files,
            purged_soft_deleted_records=deleted_purged,
            purged_auth_tokens=auth_purged,
            reclaimed_bytes=spool_bytes + deleted_bytes,
            executed_at=self._now(),
        )
