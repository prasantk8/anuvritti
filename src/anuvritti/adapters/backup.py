"""Backup and disaster recovery adapter (PRD 44, HARDENING 5.4).

Anuvritti archives consist of one SQLite database plus one content-addressed encrypted
media directory. This adapter implements consistent snapshots via `sqlite3 .backup`,
media synchronization, cryptographic manifest hashing, and scratch-restore verification.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """Cryptographic manifest of an Anuvritti backup snapshot."""

    version: str
    created_at: str
    db_sha256: str
    db_bytes: int
    media_count: int
    media_total_bytes: int
    media_hashes: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RestoreReport:
    """Report summarizing the outcome of an archive restoration."""

    restored_at: str
    db_path: str
    db_bytes: int
    media_files_restored: int
    media_total_bytes: int
    integrity_verified: bool


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def create_backup(
    db_path: Path,
    media_dir: Path,
    dest_dir: Path,
    *,
    timestamp: datetime | None = None,
) -> Result[BackupManifest, DomainError]:
    """Create a consistent online backup of the SQLite database and media files.

    Uses SQLite's online backup API (equivalent to `sqlite3 .backup`) to ensure
    consistent snapshots even during active WAL transactions.
    """
    if not db_path.exists():
        return Err(
            DomainError(ErrorCode.BACKUP_INCOMPLETE, f"database file {db_path} does not exist")
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    target_db = dest_dir / "anuvritti.db"
    target_media = dest_dir / "media"

    # 1. Consistent online SQLite backup
    try:
        source_conn = sqlite3.connect(str(db_path))
        dest_conn = sqlite3.connect(str(target_db))
        with dest_conn:
            source_conn.backup(dest_conn)
        dest_conn.close()
        source_conn.close()
    except sqlite3.Error as exc:
        return Err(DomainError(ErrorCode.CONFLICT, f"SQLite backup failed: {exc}"))

    db_sha = _sha256_file(target_db)
    db_bytes = target_db.stat().st_size

    # 2. Synchronize media directory
    media_hashes: dict[str, str] = {}
    media_total_bytes = 0
    media_count = 0

    if media_dir.exists():
        target_media.mkdir(parents=True, exist_ok=True)
        for src_file in media_dir.rglob("*"):
            if src_file.is_file():
                rel_path = src_file.relative_to(media_dir).as_posix()
                dst_file = target_media / rel_path
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)

                file_sha = _sha256_file(dst_file)
                file_bytes = dst_file.stat().st_size
                media_hashes[rel_path] = file_sha
                media_total_bytes += file_bytes
                media_count += 1

    # 3. Create manifest
    now = timestamp or datetime.now(UTC)
    manifest = BackupManifest(
        version="1.0",
        created_at=now.isoformat(),
        db_sha256=db_sha,
        db_bytes=db_bytes,
        media_count=media_count,
        media_total_bytes=media_total_bytes,
        media_hashes=media_hashes,
    )

    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n")

    return Ok(manifest)


def verify_backup(backup_dir: Path) -> Result[BackupManifest, DomainError]:
    """Verify that a backup directory matches its manifest and is uncorrupted."""
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        return Err(DomainError(ErrorCode.VALIDATION_FAILED, f"manifest missing in {backup_dir}"))

    try:
        data = json.loads(manifest_path.read_text())
        manifest = BackupManifest(
            version=data["version"],
            created_at=data["created_at"],
            db_sha256=data["db_sha256"],
            db_bytes=data["db_bytes"],
            media_count=data["media_count"],
            media_total_bytes=data["media_total_bytes"],
            media_hashes=data["media_hashes"],
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return Err(DomainError(ErrorCode.VALIDATION_FAILED, f"invalid manifest format: {exc}"))

    target_db = backup_dir / "anuvritti.db"
    if not target_db.exists():
        return Err(DomainError(ErrorCode.BACKUP_INCOMPLETE, "database file missing in backup"))

    if _sha256_file(target_db) != manifest.db_sha256:
        return Err(DomainError(ErrorCode.CONFLICT, "database checksum mismatch"))

    target_media = backup_dir / "media"
    for rel_path, expected_hash in manifest.media_hashes.items():
        media_file = target_media / rel_path
        if not media_file.exists():
            return Err(DomainError(ErrorCode.BACKUP_INCOMPLETE, f"media file missing: {rel_path}"))
        if _sha256_file(media_file) != expected_hash:
            return Err(DomainError(ErrorCode.CONFLICT, f"media file checksum mismatch: {rel_path}"))

    return Ok(manifest)


def restore_backup(
    backup_dir: Path,
    target_db_path: Path,
    target_media_dir: Path,
    *,
    verify: bool = True,
) -> Result[RestoreReport, DomainError]:
    """Restore an Anuvritti archive from a verified backup directory.

    Validates database and media hashes against the manifest, restores files
    into target locations, and executes SQLite PRAGMA quick_check.
    """
    if verify:
        verification = verify_backup(backup_dir)
        if verification.is_err():
            return Err(verification.unwrap_err())

    backup_db = backup_dir / "anuvritti.db"
    if not backup_db.exists():
        return Err(
            DomainError(ErrorCode.BACKUP_INCOMPLETE, f"no anuvritti.db found in {backup_dir}")
        )

    # Prepare target directories
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    target_media_dir.mkdir(parents=True, exist_ok=True)

    # Restore SQLite database
    shutil.copy2(backup_db, target_db_path)

    # Quick SQLite sanity check
    try:
        conn = sqlite3.connect(str(target_db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA quick_check;")
        check_result = cursor.fetchone()
        conn.close()
        if not check_result or check_result[0] != "ok":
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    f"restored database integrity check failed: {check_result}",
                )
            )
    except sqlite3.Error as exc:
        return Err(DomainError(ErrorCode.CONFLICT, f"restored database verification failed: {exc}"))

    # Restore media files
    backup_media = backup_dir / "media"
    media_files_restored = 0
    media_total_bytes = 0

    if backup_media.exists():
        for src_file in backup_media.rglob("*"):
            if src_file.is_file():
                rel_path = src_file.relative_to(backup_media).as_posix()
                dst_file = target_media_dir / rel_path
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                media_files_restored += 1
                media_total_bytes += dst_file.stat().st_size

    report = RestoreReport(
        restored_at=datetime.now(UTC).isoformat(),
        db_path=str(target_db_path),
        db_bytes=target_db_path.stat().st_size,
        media_files_restored=media_files_restored,
        media_total_bytes=media_total_bytes,
        integrity_verified=True,
    )
    return Ok(report)
