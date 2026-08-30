"""TASK-1302: Whole Open Archive Exporter Verification (PRD 45, PRD 24, PRD 44).

Verifies:
1. Single command exports whole archive as ordinary files a person can open in 20+ years.
2. Complete directory layout with archive.json, manifest.json, sparks.json, moments.json,
   voice_notes.json, little_things.json, lexicon.json, media/, and READER.html.
3. All files are content-addressed and verified against manifest.json SHA-256 digests.
4. Media files are decrypted and readable as standard JPEG / WAV files.
5. Reader HTML is completely offline with zero external network CDN dependencies.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from anuvritti.application.export import ARCHIVE_FORMAT_VERSION, ExportArchiveUseCase
from anuvritti.domain.family import ChildProfile, Family, Member, MemberRole
from anuvritti.domain.lexicon import Evidence, FamilyLexicon, LexiconField
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import Confidence, SourceRef
from anuvritti.domain.voice import Transcript, VoiceNote
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
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
def populated_env():
    family_id = FamilyId("fam-open-1")
    parent_id = MemberId("mem-papa")
    child_id = ChildId("child-leo")

    family = Family(
        id=family_id,
        name="The Singh Family",
        created_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        members=(
            Member(
                id=parent_id,
                display_name="Papa",
                role=MemberRole.PARENT,
            ),
        ),
        children=(
            ChildProfile(
                id=child_id,
                member_id=parent_id,
                display_name="Leo",
                date_of_birth=date(2024, 5, 12),
            ),
        ),
    )

    photo_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"child-smiling-photo" * 50
    audio_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"first-word-audio" * 50
    why_audio_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"why-recording-audio" * 50

    media_store = InMemoryMediaStore()
    now_dt = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    photo_meta = media_store.put(
        family_id, content=photo_bytes, mime_type="image/jpeg", at=now_dt
    ).unwrap()
    photo_id = photo_meta.id
    audio_meta = media_store.put(
        family_id, content=audio_bytes, mime_type="audio/wav", at=now_dt
    ).unwrap()
    audio_id = audio_meta.id
    why_meta = media_store.put(
        family_id, content=why_audio_bytes, mime_type="audio/wav", at=now_dt
    ).unwrap()
    why_id = why_meta.id

    spark = (
        Spark.capture(
            spark_id=SparkId("spark-01"),
            family_id=family_id,
            owner_id=parent_id,
            source=SourceRef.from_text("First Steps - Walking across the rug"),
            at=now_dt,
            subject_child_id=child_id,
        )
        .record_why(text="He looked so happy", voice_media_id=why_id, at=now_dt)
        .unwrap()
    )

    moment = Moment(
        id=MomentId("mom-01"),
        family_id=family_id,
        spark_id=SparkId("spark-01"),
        happened_on=date(2026, 6, 1),
        reflection="A memorable sunny morning.",
        photo_media_id=photo_id,
        audio_media_id=audio_id,
        created_by=parent_id,
        created_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    transcript = Transcript.machine(
        "Look at him walking towards mama!",
        confidence=Confidence.HIGH,
        engine="whisper-tiny",
        at=datetime(2026, 6, 1, 12, 0, 5, tzinfo=UTC),
    ).unwrap()

    voice_note = VoiceNote(
        media_id=audio_id,
        family_id=family_id,
        author_id=parent_id,
        duration_seconds=5.2,
        recorded_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        transcript=transcript,
    )

    little_thing = LittleThing(
        id=LittleThingId("lt-word-01"),
        family_id=family_id,
        author_id=parent_id,
        subject_child_id=child_id,
        text="Dadaa (first spoken pointing at boots)",
        audio_media_id=str(audio_id),
        created_at=datetime(2026, 5, 20, 8, 0, tzinfo=UTC),
    )

    lexicon = FamilyLexicon(
        family_id=family_id,
        entries={
            (LexiconField.CATEGORY, "choo-choo", "TRAIN"): Evidence(
                times=3,
                last_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            )
        },
    )

    families = InMemoryFamilyRepository()
    families.save(family)

    sparks = InMemorySparkRepository()
    sparks.save(spark)

    moments = InMemoryMomentRepository()
    moments.save(moment)

    voice_notes = InMemoryVoiceNoteRepository()
    voice_notes.save(voice_note)

    little_things = InMemoryLittleThingRepository()
    little_things.save(little_thing)

    lexicons = InMemoryLexiconRepository()
    lexicons.save(lexicon)

    return {
        "family_id": family_id,
        "families": families,
        "sparks": sparks,
        "moments": moments,
        "voice_notes": voice_notes,
        "little_things": little_things,
        "lexicons": lexicons,
        "media": media_store,
        "photo_id": photo_id,
        "audio_id": audio_id,
        "photo_bytes": photo_bytes,
        "audio_bytes": audio_bytes,
    }


def test_export_archive_produces_complete_self_contained_folder(populated_env, tmp_path: Path):
    """Export produces the full specification layout with zero external dependencies."""
    dest = tmp_path / "my_family_archive"
    clock = FrozenClock(datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC))

    use_case = ExportArchiveUseCase(
        families=populated_env["families"],
        sparks=populated_env["sparks"],
        moments=populated_env["moments"],
        voice_notes=populated_env["voice_notes"],
        little_things=populated_env["little_things"],
        lexicons=populated_env["lexicons"],
        media=populated_env["media"],
        clock=clock,
    )

    result = use_case.execute(populated_env["family_id"], destination_dir=dest)
    assert result.is_ok()
    archive_res = result.unwrap()

    assert archive_res.destination == dest
    assert archive_res.file_count >= 8

    # 1. Required files exist
    assert (dest / "archive.json").exists()
    assert (dest / "manifest.json").exists()
    assert (dest / "sparks.json").exists()
    assert (dest / "moments.json").exists()
    assert (dest / "voice_notes.json").exists()
    assert (dest / "little_things.json").exists()
    assert (dest / "lexicon.json").exists()
    assert (dest / "READER.html").exists()
    assert (dest / "media").is_dir()

    # 2. archive.json check
    archive_json = json.loads((dest / "archive.json").read_text(encoding="utf-8"))
    assert archive_json["format_version"] == ARCHIVE_FORMAT_VERSION
    assert archive_json["family"]["name"] == "The Singh Family"
    assert archive_json["counts"]["sparks"] == 1
    assert archive_json["counts"]["moments"] == 1
    assert archive_json["counts"]["media_files"] == 3

    # 3. Media files exist and are unencrypted
    photo_file = dest / "media" / f"{populated_env['photo_id']}.jpg"
    assert photo_file.exists()
    assert photo_file.read_bytes() == populated_env["photo_bytes"]

    audio_file = dest / "media" / f"{populated_env['audio_id']}.wav"
    assert audio_file.exists()
    assert audio_file.read_bytes() == populated_env["audio_bytes"]

    # 4. manifest.json fixity check
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "SHA-256"
    assert len(manifest["files"]) >= 8

    for entry in manifest["files"]:
        target = dest / entry["relative_path"]
        assert target.exists(), f"File {entry['relative_path']} listed in manifest must exist"
        data = target.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        assert actual_hash == entry["sha256"], f"Checksum mismatch on {entry['relative_path']}"
        assert len(data) == entry["byte_size"]

    # 5. READER.html contains no external script/link tags
    reader_html = (dest / "READER.html").read_text(encoding="utf-8")
    assert "http://" not in reader_html
    assert "https://" not in reader_html
    assert "<script>" in reader_html


def test_export_refuses_non_empty_destination(populated_env, tmp_path: Path):
    """Refuses to overwrite existing files in a non-empty directory."""
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "stray.txt").write_text("already here", encoding="utf-8")

    use_case = ExportArchiveUseCase(
        families=populated_env["families"],
        sparks=populated_env["sparks"],
        moments=populated_env["moments"],
        voice_notes=populated_env["voice_notes"],
        little_things=populated_env["little_things"],
        lexicons=populated_env["lexicons"],
        media=populated_env["media"],
    )

    res = use_case.execute(populated_env["family_id"], destination_dir=dest)
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.CONFLICT
    assert "not empty" in res.unwrap_err().message


def test_export_missing_family_returns_not_found(populated_env, tmp_path: Path):
    """Missing family returns FAMILY_NOT_FOUND error."""
    use_case = ExportArchiveUseCase(
        families=populated_env["families"],
        sparks=populated_env["sparks"],
        moments=populated_env["moments"],
        voice_notes=populated_env["voice_notes"],
        little_things=populated_env["little_things"],
        lexicons=populated_env["lexicons"],
        media=populated_env["media"],
    )

    res = use_case.execute(FamilyId("fam-unknown"), destination_dir=tmp_path / "out")
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.FAMILY_NOT_FOUND
