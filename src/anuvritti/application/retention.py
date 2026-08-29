"""Retention Policies as Code (HARDENING 5.6, PRD 44, PRD 45, TASK-1108).

Retention Rules:
1. Sovereign Family Archive (NEVER EXPIRES): Active sparks, moments, audio, and photos
   are kept permanently until explicitly unlinked by a parent.
2. Ephemeral Upload Spools (TTL: 24 Hours): Incomplete upload chunks and abandoned
   upload sessions older than 24 hours are purged.
3. Soft-Deleted Records (Grace Period: 30 Days): Soft-deleted items are unlinked
   from SQLite and deleted from disk after 30 days.
4. Expired Auth Tokens & Pairing Requests (TTL: 15 Minutes): Unclaimed pairing tokens
   and expired tickets are pruned.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionSummary:
    purged_upload_spools: int
    purged_soft_deleted_records: int
    purged_auth_tokens: int
    reclaimed_bytes: int
    executed_at: datetime
    purged_render_artifacts: int = 0


class RetentionEngine:
    """Enforces automated data lifecycle and retention policies."""

    def __init__(
        self,
        db: Any,
        media_root: Path,
        upload_spool_dir: Path,
        render_artifacts_dir: Path | None = None,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._media_root = media_root
        self._upload_spool_dir = upload_spool_dir
        self._render_artifacts_dir = render_artifacts_dir
        self._now = now_fn

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        res = self._db.execute(sql, params)
        if hasattr(res, "fetchall"):
            return list(res.fetchall())
        if hasattr(res, "rows"):
            return list(res.rows)
        return list(res)

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
        try:
            sql = (
                "SELECT code_fingerprint FROM pairing_request "
                "WHERE expires_at < ? OR (claimed_at IS NOT NULL AND created_at < ?)"
            )
            rows = self._query(sql, (cutoff_iso, cutoff_iso))
            for row in rows:
                fp = row[0] if isinstance(row, tuple) else row["code_fingerprint"]
                self._db.execute("DELETE FROM pairing_request WHERE code_fingerprint = ?", (fp,))
            return len(rows)
        except Exception as exc:
            logger.debug("prune_expired_auth_tokens skipped: %s", exc)
            return 0

    def prune_soft_deleted_records(self, grace_days: int = 30) -> tuple[int, int]:
        """Permanently purge records marked deleted beyond the 30-day grace window."""
        cutoff_iso = (self._now() - timedelta(days=grace_days)).isoformat()
        purged_count = 0
        reclaimed_bytes = 0

        try:
            sql = (
                "SELECT id, source_media_id, why_voice_media_id FROM spark "
                "WHERE visibility = 'DELETED' AND updated_at < ?"
            )
            rows = self._query(sql, (cutoff_iso,))
            for row in rows:
                spark_id = row[0] if isinstance(row, tuple) else row["id"]
                src_med = row[1] if isinstance(row, tuple) else row["source_media_id"]
                why_med = row[2] if isinstance(row, tuple) else row["why_voice_media_id"]

                for med_id in (src_med, why_med):
                    if med_id:
                        m_rows = self._query(
                            "SELECT storage_key FROM media WHERE id = ?",
                            (med_id,),
                        )
                        if m_rows:
                            m_row = m_rows[0]
                            key = m_row[0] if isinstance(m_row, tuple) else m_row["storage_key"]
                            p = self._media_root / key
                            if p.exists():
                                reclaimed_bytes += p.stat().st_size
                                p.unlink(missing_ok=True)
                            self._db.execute("DELETE FROM media WHERE id = ?", (med_id,))

                self._db.execute("DELETE FROM spark WHERE id = ?", (spark_id,))
                purged_count += 1
        except Exception as exc:
            logger.debug("prune_soft_deleted_records skipped: %s", exc)

        return purged_count, reclaimed_bytes

    def prune_expired_render_artifacts(self, max_age_hours: int = 48) -> tuple[int, int]:
        """Prune expired render host intermediate frames, export archives and mp4s (TASK-1207).

        Constitutional invariant: Rendered films and frames expire from the render host on a clock,
        and NEVER from the family's own sovereign archive (media_root).
        """
        if self._render_artifacts_dir is None or not self._render_artifacts_dir.exists():
            return 0, 0

        cutoff = self._now() - timedelta(hours=max_age_hours)
        purged_files = 0
        reclaimed_bytes = 0

        for path in self._render_artifacts_dir.rglob("*"):
            if path.is_file():
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    size = path.stat().st_size
                    path.unlink(missing_ok=True)
                    purged_files += 1
                    reclaimed_bytes += size

        return purged_files, reclaimed_bytes

    def run_retention_cycle(
        self,
        spool_max_age_hours: int = 24,
        deleted_grace_days: int = 30,
        auth_max_age_minutes: int = 15,
        render_max_age_hours: int = 48,
    ) -> RetentionSummary:
        """Execute a full retention cycle."""
        spool_files, spool_bytes = self.prune_ephemeral_upload_spools(spool_max_age_hours)
        auth_purged = self.prune_expired_auth_tokens(auth_max_age_minutes)
        deleted_purged, deleted_bytes = self.prune_soft_deleted_records(deleted_grace_days)
        render_purged, render_bytes = self.prune_expired_render_artifacts(render_max_age_hours)

        return RetentionSummary(
            purged_upload_spools=spool_files,
            purged_soft_deleted_records=deleted_purged,
            purged_auth_tokens=auth_purged,
            purged_render_artifacts=render_purged,
            reclaimed_bytes=spool_bytes + deleted_bytes + render_bytes,
            executed_at=self._now(),
        )
