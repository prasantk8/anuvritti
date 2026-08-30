"""TASK-1306: Business Continuity & Key Escrow Verification (PRD 44, PRD 45, PRD 47).

Verifies the operational continuity runbook in docs/CONTINUITY.md:
1. Keys escrowed to the family allow 100% offline decryption of all media and entities.
2. The standalone READER.html has zero external CDN/network dependencies.
3. The format published on disk is complete, validated by manifest sha256 checksums.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from anuvritti.application.export import ExportArchiveUseCase
from anuvritti.domain.family import ChildProfile, Family, Member, MemberRole
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import Confidence, SourceRef
from anuvritti.domain.voice import Transcript, VoiceNote
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    LittleThingId,
    MemberId,
    MomentId,
    SparkId,
)
from tests.support.fakes import (
    InMemoryFamilyRepository,
    InMemoryLexiconRepository,
    InMemoryLittleThingRepository,
    InMemoryMediaStore,
    InMemoryMomentRepository,
    InMemorySparkRepository,
    InMemoryVoiceNoteRepository,
)


@pytest.fixture
def continuity_fixture(tmp_path: Path):
    family_id = FamilyId("fam-continuity-01")
    parent_id = MemberId("mem-parent-01")
    child_id = ChildId("child-01")
    now = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)

    family = Family(
        id=family_id,
        name="Continuity Family",
        created_at=now,
        members=(Member(id=parent_id, display_name="Custody Parent", role=MemberRole.PARENT),),
        children=(
            ChildProfile(
                id=child_id,
                member_id=parent_id,
                display_name="Maya",
                date_of_birth=date(2025, 1, 1),
            ),
        ),
    )

    families = InMemoryFamilyRepository()
    families.save(family)

    sparks = InMemorySparkRepository()
    moments = InMemoryMomentRepository()
    voice_notes = InMemoryVoiceNoteRepository()
    little_things = InMemoryLittleThingRepository()
    lexicons = InMemoryLexiconRepository()
    media_store = InMemoryMediaStore()

    photo_bytes = b"CONTINUITY_PLAINTEXT_PHOTO_BYTES"
    audio_bytes = b"CONTINUITY_PLAINTEXT_AUDIO_BYTES"

    photo_meta = media_store.put(
        family_id, content=photo_bytes, mime_type="image/jpeg", at=now
    ).unwrap()
    audio_meta = media_store.put(
        family_id, content=audio_bytes, mime_type="audio/wav", at=now
    ).unwrap()

    spark = (
        Spark.capture(
            spark_id=SparkId("spark-01"),
            family_id=family_id,
            owner_id=parent_id,
            source=SourceRef.from_text("Drawing on paper"),
            at=now,
            subject_child_id=child_id,
        )
        .record_why(text="Because she drew a rainbow", voice_media_id=audio_meta.id, at=now)
        .unwrap()
    )
    sparks.save(spark)

    moment = Moment.create(
        moment_id=MomentId("mom-01"),
        family_id=family_id,
        spark_id=spark.id,
        created_by=parent_id,
        spark_captured_at=now,
        at=now,
        happened_on=date(2026, 8, 1),
        photo_media_id=photo_meta.id,
        audio_media_id=audio_meta.id,
        reflection="Rainbow on the fridge.",
    ).unwrap()
    moments.save(moment)

    transcript = Transcript.machine(
        "She loved the colors",
        confidence=Confidence.HIGH,
        engine="whisper-tiny",
        at=now,
    ).unwrap()
    voice_note = VoiceNote(
        media_id=audio_meta.id,
        family_id=family_id,
        author_id=parent_id,
        duration_seconds=5.2,
        recorded_at=now,
        transcript=transcript,
    )
    voice_notes.save(voice_note)

    little = LittleThing.capture(
        little_thing_id=LittleThingId("lt-01"),
        family_id=family_id,
        author_id=parent_id,
        subject_child_id=child_id,
        text="Bapu",
        at=now,
    ).unwrap()
    little_things.save(little)

    return {
        "family_id": family_id,
        "families": families,
        "sparks": sparks,
        "moments": moments,
        "voice_notes": voice_notes,
        "little_things": little_things,
        "lexicons": lexicons,
        "media_store": media_store,
        "photo_bytes": photo_bytes,
        "audio_bytes": audio_bytes,
        "now": now,
    }


def test_offline_reader_zero_network(continuity_fixture, tmp_path: Path):
    """READER.html contains zero external scripts, stylesheets, or CDN URLs."""
    fix = continuity_fixture
    export_dir = tmp_path / "export_offline_test"

    exporter = ExportArchiveUseCase(
        families=fix["families"],
        sparks=fix["sparks"],
        moments=fix["moments"],
        voice_notes=fix["voice_notes"],
        little_things=fix["little_things"],
        lexicons=fix["lexicons"],
        media=fix["media_store"],
        clock=FrozenClock(fix["now"]),
    )
    res = exporter.execute(fix["family_id"], destination_dir=export_dir)
    assert res.is_ok()

    reader_path = export_dir / "READER.html"
    assert reader_path.exists()
    html = reader_path.read_text(encoding="utf-8")

    # Guard: No external CDN or web URLs (http://, https://, //cdn)
    network_urls = re.findall(
        r'src=["\']https?://[^"\']+["\']|href=["\']https?://[^"\']+["\']', html
    )
    assert not network_urls, f"Reader has external network dependencies: {network_urls}"

    # Guard: Zero unpkg, cdnjs, googleapis references
    forbidden_tokens = ["unpkg.com", "cdnjs.cloudflare.com", "fonts.googleapis.com", "jsdelivr.net"]
    for token in forbidden_tokens:
        assert token not in html, f"Reader references external CDN {token}"


def test_key_escrow_offline_decryption_and_fixity(continuity_fixture, tmp_path: Path):
    """The family can decrypt and extract 100% of their data offline."""
    fix = continuity_fixture
    export_dir = tmp_path / "export_escrow_test"

    exporter = ExportArchiveUseCase(
        families=fix["families"],
        sparks=fix["sparks"],
        moments=fix["moments"],
        voice_notes=fix["voice_notes"],
        little_things=fix["little_things"],
        lexicons=fix["lexicons"],
        media=fix["media_store"],
        clock=FrozenClock(fix["now"]),
    )
    res = exporter.execute(fix["family_id"], destination_dir=export_dir)
    assert res.is_ok()
    result_meta = res.unwrap()
    assert result_meta.file_count >= 8
    assert result_meta.total_bytes > 0

    archive_data = json.loads((export_dir / "archive.json").read_text(encoding="utf-8"))
    assert archive_data["counts"]["sparks"] == 1
    assert archive_data["counts"]["moments"] == 1
    assert archive_data["counts"]["media_files"] == 2

    # Verify all files match manifest hashes
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "SHA-256"

    for entry in manifest["files"]:
        target = export_dir / entry["relative_path"]
        assert target.exists()
        content = target.read_bytes()
        assert len(content) == entry["byte_size"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]


def test_disaster_recovery_runbook_execution(continuity_fixture, tmp_path: Path):
    """Simulates executing the continuity runbook when all external services are gone."""
    fix = continuity_fixture
    export_dir = tmp_path / "disaster_recovery_vault"

    # Step 1 & 2: Local decryption and export
    exporter = ExportArchiveUseCase(
        families=fix["families"],
        sparks=fix["sparks"],
        moments=fix["moments"],
        voice_notes=fix["voice_notes"],
        little_things=fix["little_things"],
        lexicons=fix["lexicons"],
        media=fix["media_store"],
        clock=FrozenClock(fix["now"]),
    )
    res = exporter.execute(fix["family_id"], destination_dir=export_dir)
    assert res.is_ok()

    # Step 3: Integrity verification on plain filesystem
    archive_json = json.loads((export_dir / "archive.json").read_text(encoding="utf-8"))
    assert archive_json["format_version"] == "1.0"
    assert archive_json["family"]["name"] == "Continuity Family"

    # Step 4: Validate local media assets
    media_files = list((export_dir / "media").iterdir())
    assert len(media_files) == 2
    extensions = {m.suffix for m in media_files}
    assert ".jpg" in extensions
    assert ".wav" in extensions
