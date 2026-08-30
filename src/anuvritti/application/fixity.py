"""TASK-1311: Decades-Long Fixity Verification & Bit-Rot Repair (PRD 8.6, HARDENING 5.4).

Provides:
1. Scheduled bit-level audit across family media vaults.
2. Anomaly detection (corrupted bits, missing blobs).
3. Cryptographically enforced repair from backup replicas.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from anuvritti.application.ports import MediaStore
from anuvritti.shared.clock import Clock, SystemClock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId
from anuvritti.shared.result import Err, Ok, Result


class FixityStatus(StrEnum):
    """The integrity state of a stored media file."""

    VERIFIED = "VERIFIED"
    CORRUPTED = "CORRUPTED"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class FixityAnomaly:
    """A detected bit-rot or file disappearance incident."""

    media_id: MediaId
    family_id: FamilyId
    status: FixityStatus
    expected_hash: str
    actual_hash: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_id": str(self.media_id),
            "family_id": str(self.family_id),
            "status": self.status.value,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class FixityReport:
    """The complete result of a scheduled fixity scan."""

    family_id: FamilyId
    scanned_at: datetime
    scanned_count: int
    verified_count: int
    corrupted_count: int
    missing_count: int
    anomalies: tuple[FixityAnomaly, ...]

    @property
    def is_clean(self) -> bool:
        return len(self.anomalies) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": str(self.family_id),
            "scanned_at": self.scanned_at.isoformat(),
            "scanned_count": self.scanned_count,
            "verified_count": self.verified_count,
            "corrupted_count": self.corrupted_count,
            "missing_count": self.missing_count,
            "is_clean": self.is_clean,
            "anomalies": [a.to_dict() for a in self.anomalies],
        }


class FixityEngine:
    """Audits and repairs media custody over decades."""

    def __init__(self, media: MediaStore, *, clock: Clock | None = None) -> None:
        self._media = media
        self._clock = clock or SystemClock()

    def audit_family(self, family_id: FamilyId) -> Result[FixityReport, DomainError]:
        """Scans every media file for a family, re-hashing content against recorded fixity."""
        now = self._clock.now()
        list_res = self._media.list_for_family(family_id)
        if list_res.is_err():
            return Err(list_res.unwrap_err())
        media_list = list_res.unwrap()

        verified = 0
        corrupted = 0
        missing = 0
        anomalies: list[FixityAnomaly] = []

        for obj in media_list:
            content_res = self._media.get(obj.id)
            if content_res.is_err():
                err = content_res.unwrap_err()
                if err.code == ErrorCode.MEDIA_NOT_FOUND:
                    missing += 1
                    anomalies.append(
                        FixityAnomaly(
                            media_id=obj.id,
                            family_id=family_id,
                            status=FixityStatus.MISSING,
                            expected_hash=obj.content_hash,
                            actual_hash=None,
                            detail="media file not found on storage disk",
                        )
                    )
                else:
                    # Hash mismatch or decryption corruption
                    corrupted += 1
                    anomalies.append(
                        FixityAnomaly(
                            media_id=obj.id,
                            family_id=family_id,
                            status=FixityStatus.CORRUPTED,
                            expected_hash=obj.content_hash,
                            actual_hash=None,
                            detail=f"integrity read failure: {err.message}",
                        )
                    )
            else:
                raw_bytes = content_res.unwrap()
                actual_sha = hashlib.sha256(raw_bytes).hexdigest()
                if actual_sha == obj.content_hash:
                    verified += 1
                else:
                    corrupted += 1
                    anomalies.append(
                        FixityAnomaly(
                            media_id=obj.id,
                            family_id=family_id,
                            status=FixityStatus.CORRUPTED,
                            expected_hash=obj.content_hash,
                            actual_hash=actual_sha,
                            detail=(
                                f"bit-rot detected: hash mismatch "
                                f"{actual_sha} != {obj.content_hash}"
                            ),
                        )
                    )

        return Ok(
            FixityReport(
                family_id=family_id,
                scanned_at=now,
                scanned_count=len(media_list),
                verified_count=verified,
                corrupted_count=corrupted,
                missing_count=missing,
                anomalies=tuple(anomalies),
            )
        )

    def repair_media(
        self,
        family_id: FamilyId,
        media_id: MediaId,
        *,
        backup_bytes: bytes,
    ) -> Result[bool, DomainError]:
        """Repairs a corrupted or missing media blob from a verified backup source."""
        desc_res = self._media.describe(media_id)
        if desc_res.is_err():
            return Err(desc_res.unwrap_err())
        obj = desc_res.unwrap()

        if obj.family_id != family_id:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "media does not belong to family",
                )
            )

        # 1. Guard: Backup bytes must match the recorded canonical hash
        backup_sha = hashlib.sha256(backup_bytes).hexdigest()
        if backup_sha != obj.content_hash:
            msg = (
                f"repair rejected: backup bytes hash ({backup_sha}) does not match "
                f"recorded fixity ({obj.content_hash})"
            )
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    msg,
                    {"expected_hash": obj.content_hash, "backup_hash": backup_sha},
                )
            )

        # 2. Re-write media blob through store restore
        store_res = self._media.restore(
            media_id=media_id,
            content=backup_bytes,
        )
        if store_res.is_err():
            return Err(store_res.unwrap_err())

        return Ok(True)
