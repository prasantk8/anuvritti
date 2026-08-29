"""Integration tests for archive backup and disaster recovery (TASK-905, PRD 44, HARDENING 5.4).

Verifies that:
1. `sqlite3 .backup` produces a consistent snapshot.
2. Encrypted media files synchronize with verified hashes.
3. Restoration into a clean scratch environment restores full repository fidelity.
4. Corrupted snapshots fail verification loudly before restoration.
5. Continuity documentation exists and contains actionable recovery procedures.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.backup import create_backup, restore_backup, verify_backup
from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqliteSparkRepository,
)
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.moment import Moment
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import (
    MemberRole,
    SourceRef,
)
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import ChildId, FamilyId, IdGenerator, MemberId, MomentId, SparkId

#: `bash` resolved once, so the S607 partial-path warning is answered by fact.
BASH = shutil.which("bash") or "/bin/bash"


class SequentialIds(IdGenerator):
    def __init__(self, prefix: str = "test") -> None:
        self._prefix = prefix
        self._count = 0

    def new_id(self) -> str:
        self._count += 1
        return f"{self._prefix}-{self._count:04d}"


@pytest.fixture
def media_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def live_archive(tmp_path: Path, media_key: str):
    db_path = tmp_path / "live" / "anuvritti.db"
    media_dir = tmp_path / "live" / "media"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(str(db_path))
    migrate(conn)
    ids = SequentialIds()
    clock = FrozenClock(datetime(2026, 8, 26, 12, 0, tzinfo=UTC))

    families = SqliteFamilyRepository(conn)
    sparks = SqliteSparkRepository(conn)
    moments = SqliteMomentRepository(conn)
    catalogue = SqliteMediaCatalogue(conn)

    media_store = EncryptedFilesystemMediaStore(
        root=media_dir,
        catalogue=catalogue,
        ids=ids,
        encryption_key=media_key,
        max_bytes=10 * 1024 * 1024,
        allowed_mime_types=frozenset({"image/jpeg", "audio/mp4", "audio/x-m4a"}),
    )

    # Seed realistic archive
    family_id = FamilyId("fam-001")
    parent_id = MemberId("mem-001")
    child_id = ChildId("child-001")

    family = Family(
        id=family_id,
        name="The Singers",
        members=(Member(parent_id, "Papa", MemberRole.PARENT),),
        children=(ChildProfile(child_id, MemberId("mem-002"), "Leo", date(2022, 5, 14)),),
        created_at=clock.now(),
    )
    families.save(family)

    # Save photo and voice media
    photo_bytes = b"JPEG_IMAGE_TEST_BYTES_FAMILY_MEMORIES"
    audio_bytes = b"M4A_VOICE_TEST_BYTES_PAPA_VOICE"

    photo_obj = media_store.put(
        family_id, content=photo_bytes, mime_type="image/jpeg", at=clock.now()
    ).unwrap()
    audio_obj = media_store.put(
        family_id, content=audio_bytes, mime_type="audio/mp4", at=clock.now()
    ).unwrap()

    # Save Spark and Moment
    spark_id = SparkId("spark-001")
    spark = (
        Spark.capture(
            spark_id=spark_id,
            family_id=family_id,
            owner_id=parent_id,
            source=SourceRef.from_url("https://example.com/crafts", title="Build a Rocket"),
            at=clock.now(),
            subject_child_id=child_id,
        )
        .record_why(text="He loves space", voice_media_id=audio_obj.id, at=clock.now())
        .unwrap()
    )

    moment_id = MomentId("moment-001")
    moment = Moment(
        id=moment_id,
        family_id=family_id,
        spark_id=spark_id,
        happened_on=clock.now().date(),
        reflection="We built it on Sunday and painted it red.",
        photo_media_id=photo_obj.id,
        audio_media_id=audio_obj.id,
        created_by=parent_id,
        created_at=clock.now(),
    )

    sparks.save(spark)
    moments.save(moment)

    return {
        "tmp_path": tmp_path,
        "db_path": db_path,
        "media_dir": media_dir,
        "media_key": media_key,
        "family_id": family_id,
        "spark_id": spark_id,
        "moment_id": moment_id,
        "photo_id": photo_obj.id,
        "audio_id": audio_obj.id,
        "photo_bytes": photo_bytes,
        "audio_bytes": audio_bytes,
    }


def test_backup_and_restore_roundtrip(live_archive):
    backup_dir = live_archive["tmp_path"] / "backups" / "snap-01"
    restore_db = live_archive["tmp_path"] / "restored" / "anuvritti.db"
    restore_media = live_archive["tmp_path"] / "restored" / "media"

    # 1. Create backup
    manifest = create_backup(
        live_archive["db_path"], live_archive["media_dir"], backup_dir
    ).unwrap()
    assert manifest.media_count == 2
    assert manifest.db_bytes > 0
    assert (backup_dir / "anuvritti.db").exists()
    assert (backup_dir / "manifest.json").exists()

    # 2. Verify backup
    verified = verify_backup(backup_dir).unwrap()
    assert verified.db_sha256 == manifest.db_sha256

    # 3. Restore to scratch directory
    report = restore_backup(backup_dir, restore_db, restore_media).unwrap()
    assert report.integrity_verified is True
    assert report.media_files_restored == 2

    # 4. Open restored archive and verify complete domain state
    conn = connect(str(restore_db))
    families = SqliteFamilyRepository(conn)
    sparks = SqliteSparkRepository(conn)
    moments = SqliteMomentRepository(conn)
    catalogue = SqliteMediaCatalogue(conn)

    restored_fam = families.get(live_archive["family_id"]).unwrap()
    assert restored_fam.name == "The Singers"

    restored_spark = sparks.get(live_archive["spark_id"]).unwrap()
    assert restored_spark.why is not None
    assert restored_spark.why.text == "He loves space"
    assert restored_spark.why.voice_media_id == str(live_archive["audio_id"])

    restored_moment = moments.get_by_spark(live_archive["spark_id"]).unwrap()
    assert restored_moment.reflection == "We built it on Sunday and painted it red."

    # 5. Verify media store can decrypt restored bytes with the key
    media_store = EncryptedFilesystemMediaStore(
        root=restore_media,
        catalogue=catalogue,
        ids=SequentialIds(),
        encryption_key=live_archive["media_key"],
        max_bytes=10 * 1024 * 1024,
        allowed_mime_types=frozenset({"image/jpeg", "audio/mp4"}),
    )

    photo_decrypted = media_store.get(live_archive["photo_id"]).unwrap()
    assert photo_decrypted == live_archive["photo_bytes"]

    audio_decrypted = media_store.get(live_archive["audio_id"]).unwrap()
    assert audio_decrypted == live_archive["audio_bytes"]


def test_corrupted_backup_fails_verification(live_archive):
    backup_dir = live_archive["tmp_path"] / "backups" / "snap-tampered"
    create_backup(live_archive["db_path"], live_archive["media_dir"], backup_dir).unwrap()

    # Tamper with database
    target_db = backup_dir / "anuvritti.db"
    target_db.write_bytes(b"CORRUPTED_DATABASE_BYTES")

    verification = verify_backup(backup_dir)
    assert verification.is_err()
    assert "checksum mismatch" in verification.unwrap_err().message


def test_continuity_document_exists():
    continuity_file = Path("docs/CONTINUITY.md")
    assert continuity_file.exists()
    content = continuity_file.read_text().strip()
    lines = [line for line in content.splitlines() if line.strip() and not line.startswith("#")]
    assert len(lines) == 10
    assert "anuvritti.db" in content
    assert "ANUVRITTI_MEDIA_KEY" in content
    assert "restore.sh" in content


def test_cli_scripts_backup_and_restore(live_archive):
    backup_dest = live_archive["tmp_path"] / "cli_backup"
    restore_db = live_archive["tmp_path"] / "cli_restored" / "anuvritti.db"
    restore_media = live_archive["tmp_path"] / "cli_restored" / "media"

    env = os.environ.copy()
    env["ANUVRITTI_DB_PATH"] = str(live_archive["db_path"])
    env["ANUVRITTI_MEDIA_DIR"] = str(live_archive["media_dir"])

    res_bk = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths built by the test
        [BASH, "scripts/backup.sh", str(backup_dest)], env=env, capture_output=True, text=True
    )
    assert res_bk.returncode == 0, f"backup.sh failed: {res_bk.stderr}"
    assert (backup_dest / "manifest.json").exists()

    res_rst = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths built by the test
        [BASH, "scripts/restore.sh", str(backup_dest), str(restore_db), str(restore_media)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_rst.returncode == 0, f"restore.sh failed: {res_rst.stderr}"
    assert restore_db.exists()
    assert (restore_media / str(live_archive["family_id"])).exists()
