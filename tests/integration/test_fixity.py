"""TASK-1311: Decades-Long Fixity Verification & Bit-Rot Repair (PRD 8.6, HARDENING 5.4).

Verifies:
1. Scheduled bit-level audit across family media vaults.
2. Detecting corrupted bits and missing media files.
3. Safe cryptographically verified repair from verified backups.
4. Rejecting unverified or corrupted repair candidates out loud.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.application.fixity import FixityEngine, FixityStatus
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId
from tests.support.fakes import InMemoryMediaStore


@pytest.fixture
def fixity_fixture():
    family_id = FamilyId("fam-fixity-01")
    media_store = InMemoryMediaStore()
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    clock = FrozenClock(now)

    # Put sample media files
    photo1_bytes = b"PHOTO_LEO_ONE_YEAR_OLD_ORIGINAL_BYTES"
    photo2_bytes = b"PHOTO_LEO_SWIMMING_ORIGINAL_BYTES"
    audio1_bytes = b"AUDIO_LEO_FIRST_SONG_WAV_BYTES"

    m1 = media_store.put(family_id, content=photo1_bytes, mime_type="image/jpeg", at=now).unwrap()
    m2 = media_store.put(family_id, content=photo2_bytes, mime_type="image/jpeg", at=now).unwrap()
    m3 = media_store.put(family_id, content=audio1_bytes, mime_type="audio/wav", at=now).unwrap()

    engine = FixityEngine(media=media_store, clock=clock)

    return {
        "family_id": family_id,
        "media_store": media_store,
        "clock": clock,
        "engine": engine,
        "m1": m1,
        "m2": m2,
        "m3": m3,
        "photo1_bytes": photo1_bytes,
        "photo2_bytes": photo2_bytes,
        "audio1_bytes": audio1_bytes,
    }


def test_audit_clean_vault_passes(fixity_fixture):
    """When all files are intact, audit reports 100% verified and clean status."""
    fix = fixity_fixture
    engine: FixityEngine = fix["engine"]

    report_res = engine.audit_family(fix["family_id"])
    assert report_res.is_ok()
    report = report_res.unwrap()

    assert report.is_clean is True
    assert report.scanned_count == 3
    assert report.verified_count == 3
    assert report.corrupted_count == 0
    assert report.missing_count == 0
    assert len(report.anomalies) == 0


def test_audit_detects_bit_rot_and_missing_files(fixity_fixture):
    """Detects bit-rot and missing files on disk."""
    fix = fixity_fixture
    engine: FixityEngine = fix["engine"]
    store: InMemoryMediaStore = fix["media_store"]

    # 1. Tamper m1 (bit-rot)
    store._bytes[str(fix["m1"].id)] = b"BIT_ROTTED_CORRUPTED_BYTES"

    # 2. Delete m2 (missing)
    del store._bytes[str(fix["m2"].id)]

    report_res = engine.audit_family(fix["family_id"])
    assert report_res.is_ok()
    report = report_res.unwrap()

    assert report.is_clean is False
    assert report.scanned_count == 3
    assert report.verified_count == 1
    assert report.corrupted_count == 1
    assert report.missing_count == 1
    assert len(report.anomalies) == 2

    anomalies_by_id = {a.media_id: a for a in report.anomalies}

    # Check corrupted m1
    a_m1 = anomalies_by_id[fix["m1"].id]
    assert a_m1.status == FixityStatus.CORRUPTED
    assert a_m1.expected_hash == fix["m1"].content_hash

    # Check missing m2
    a_m2 = anomalies_by_id[fix["m2"].id]
    assert a_m2.status == FixityStatus.MISSING


def test_repair_restores_corrupted_media_from_backup(fixity_fixture):
    """Repairing from backup replica restores fixity and passes subsequent audits."""
    fix = fixity_fixture
    engine: FixityEngine = fix["engine"]
    store: InMemoryMediaStore = fix["media_store"]

    # Introduce bit-rot
    store._bytes[str(fix["m1"].id)] = b"CORRUPTED_BYTES"

    # Repair with original backup bytes
    repair_res = engine.repair_media(
        fix["family_id"],
        fix["m1"].id,
        backup_bytes=fix["photo1_bytes"],
    )
    assert repair_res.is_ok()
    assert repair_res.unwrap() is True

    # Audit again -> must now be clean
    clean_report = engine.audit_family(fix["family_id"]).unwrap()
    assert clean_report.is_clean is True
    assert clean_report.verified_count == 3


def test_repair_rejects_corrupted_or_mismatched_backup_bytes(fixity_fixture):
    """Refuses candidate repair bytes whose SHA-256 does not match recorded fixity."""
    fix = fixity_fixture
    engine: FixityEngine = fix["engine"]

    wrong_bytes = b"COMPLETELY_WRONG_BACKUP_BYTES"
    repair_res = engine.repair_media(
        fix["family_id"],
        fix["m1"].id,
        backup_bytes=wrong_bytes,
    )
    assert repair_res.is_err()
    err = repair_res.unwrap_err()
    assert err.code == ErrorCode.VALIDATION_FAILED
    assert "repair rejected: backup bytes hash" in err.message
