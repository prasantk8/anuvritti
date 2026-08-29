#!/usr/bin/env python3
"""Automated Restore Rehearsal Drill (HARDENING 5.4, PRD 8.6).

A backup nobody has restored is merely a rumour.
This script restores a snapshot into an isolated scratch environment,
proves SQLite PRAGMA integrity, and verifies that every encrypted media
file can be decrypted and matches its catalogue SHA-256 hash.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class RestoreDrillResult:
    success: bool
    database_integrity: bool
    total_sparks: int
    verified_media_count: int
    corrupted_media_count: int
    duration_seconds: float
    error_message: str | None = None


def run_restore_drill(
    db_backup_path: Path,
    media_backup_dir: Path,
    encryption_key: str | None = None,
) -> RestoreDrillResult:
    start_time = time.perf_counter()
    scratch_dir = Path(tempfile.mkdtemp(prefix="anuvritti_restore_drill_"))

    try:
        # 1. Restore database into scratch
        scratch_db_path = scratch_dir / "restored.db"
        if not db_backup_path.exists():
            return RestoreDrillResult(
                success=False,
                database_integrity=False,
                total_sparks=0,
                verified_media_count=0,
                corrupted_media_count=0,
                duration_seconds=time.perf_counter() - start_time,
                error_message=f"Database backup file not found: {db_backup_path}",
            )

        shutil.copy2(db_backup_path, scratch_db_path)

        # 2. Verify database integrity
        db = sqlite3.connect(scratch_db_path)
        db.row_factory = sqlite3.Row

        integrity_res = db.execute("PRAGMA integrity_check;").fetchone()
        db_ok = integrity_res and integrity_res[0] == "ok"

        fk_res = db.execute("PRAGMA foreign_key_check;").fetchall()
        fk_ok = len(fk_res) == 0

        if not (db_ok and fk_ok):
            return RestoreDrillResult(
                success=False,
                database_integrity=False,
                total_sparks=0,
                verified_media_count=0,
                corrupted_media_count=0,
                duration_seconds=time.perf_counter() - start_time,
                error_message="SQLite database failed integrity or foreign key check",
            )

        # Check total sparks
        sparks_count = 0
        has_spark_tbl = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='spark'"
        ).fetchone()
        if has_spark_tbl:
            sparks_count = db.execute("SELECT COUNT(*) FROM spark").fetchone()[0]

        # 3. Verify media objects and decryption
        fernet = Fernet(encryption_key.encode()) if encryption_key else None
        verified_media = 0
        corrupted_media = 0

        has_media_tbl = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='media'"
        ).fetchone()

        if has_media_tbl:
            media_rows = db.execute(
                "SELECT id, storage_key, content_hash, encrypted FROM media"
            ).fetchall()

            for row in media_rows:
                storage_key = row["storage_key"]
                expected_hash = row["content_hash"]
                is_encrypted = bool(row["encrypted"])

                media_file = media_backup_dir / storage_key
                if not media_file.exists():
                    corrupted_media += 1
                    continue

                raw_bytes = media_file.read_bytes()
                try:
                    content = fernet.decrypt(raw_bytes) if (is_encrypted and fernet) else raw_bytes
                except Exception:
                    corrupted_media += 1
                    continue

                actual_hash = hashlib.sha256(content).hexdigest()
                if actual_hash == expected_hash:
                    verified_media += 1
                else:
                    corrupted_media += 1

        db.close()
        duration = time.perf_counter() - start_time
        success = corrupted_media == 0

        return RestoreDrillResult(
            success=success,
            database_integrity=True,
            total_sparks=sparks_count,
            verified_media_count=verified_media,
            corrupted_media_count=corrupted_media,
            duration_seconds=round(duration, 3),
        )

    finally:
        # 4. Clean up scratch environment
        shutil.rmtree(scratch_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run restore rehearsal drill")
    parser.add_argument("--db", type=Path, required=True, help="Path to database backup")
    parser.add_argument("--media", type=Path, required=True, help="Path to media directory")
    parser.add_argument("--key", type=str, help="Media encryption key")
    args = parser.parse_args()

    result = run_restore_drill(args.db, args.media, args.key)
    if not result.success:
        print(f"RESTORE DRILL FAILED: {result.error_message}", file=sys.stderr)
        sys.exit(1)

    print(
        "RESTORE DRILL SUCCESS: Database integrity OK. Verified "
        f"{result.verified_media_count} media objects in {result.duration_seconds}s."
    )


if __name__ == "__main__":
    main()
