"""TASK-1412 - The product's most important test.

PRD 60, PRD 61, PRD 47.

"Would a parent be glad, in fifteen years, that this existed."

Full end-to-end multi-year lifecycle proof:
1. Capture voice notes, spoken sayings, and developmental moments across childhood years.
2. Export the entire sovereign family archive to standard open files.
3. Verify that fifteen years later, the offline reader and JSON archive can be read
   completely without any network, server, or proprietary dependencies.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from cryptography.fernet import Fernet

from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteLexiconRepository,
    SqliteLittleThingRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqliteSparkRepository,
    SqliteVoiceNoteRepository,
)
from anuvritti.application.export import ExportArchiveUseCase
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import MemberRole, SourceRef, Visibility
from anuvritti.domain.voice import VoiceNote
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MemberId,
    SequentialIdGenerator,
    SparkId,
)


def test_fifteen_year_family_archive_durability_and_joy(tmp_path: Path) -> None:
    start_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    clock = FrozenClock(start_time)
    conn = connect(":memory:")
    migrate(conn)

    families = SqliteFamilyRepository(conn)
    sparks = SqliteSparkRepository(conn)
    moments = SqliteMomentRepository(conn)
    voice_notes = SqliteVoiceNoteRepository(conn)
    little_things = SqliteLittleThingRepository(conn)
    lexicon = SqliteLexiconRepository(conn)
    catalogue = SqliteMediaCatalogue(conn)
    ids = SequentialIdGenerator("med")

    media_dir = tmp_path / "media_store"
    media_dir.mkdir(parents=True, exist_ok=True)
    media_store = EncryptedFilesystemMediaStore(
        root=media_dir,
        catalogue=catalogue,
        ids=ids,
        encryption_key=Fernet.generate_key().decode(),
        max_bytes=10 * 1024 * 1024,
        allowed_mime_types=frozenset({"image/jpeg", "audio/wav", "audio/mp4"}),
    )

    family_id = FamilyId("fam-aarav-legacy")
    father_id = MemberId("mem-father")
    child_id = ChildId("child-aarav")

    family = Family(
        id=family_id,
        name="The Singhs",
        members=(Member(id=father_id, role=MemberRole.PARENT, display_name="Prashant"),),
        children=(
            ChildProfile(
                id=child_id,
                member_id=MemberId("mem-aarav"),
                display_name="Aarav",
                date_of_birth=date(2026, 9, 1),
            ),
        ),
        created_at=start_time,
    )
    families.save(family)

    # 1. Year 1: First words recorded
    audio_bytes_y1 = b"RIFF_FAKE_WAV_HEADER_YEAR_1_FIRST_WORDS"
    media_res_y1 = media_store.put(
        family_id,
        content=audio_bytes_y1,
        mime_type="audio/wav",
        at=start_time,
    )
    assert media_res_y1.is_ok()
    media_id_y1 = media_res_y1.unwrap().id

    spark_y1 = Spark.capture(
        spark_id=SparkId("spark-y1"),
        family_id=family_id,
        owner_id=father_id,
        subject_child_id=child_id,
        source=SourceRef.from_text("Aarav said 'dada' clearly while pointing at the book."),
        at=start_time,
        visibility=Visibility.FAMILY,
    )
    sparks.save(spark_y1)

    voice_res_y1 = VoiceNote.kept(
        media_id=media_id_y1,
        family_id=family_id,
        author_id=father_id,
        duration_seconds=4.2,
        at=start_time,
    )
    assert voice_res_y1.is_ok()
    voice_notes.save(voice_res_y1.unwrap())

    # 2. Advance 5 years: Kindergarten curiosity
    clock.advance(days=365 * 5)
    t_y5 = clock.now()
    spark_y5 = Spark.capture(
        spark_id=SparkId("spark-y5"),
        family_id=family_id,
        owner_id=father_id,
        subject_child_id=child_id,
        source=SourceRef.from_text("Why does the moon follow our car home at night?"),
        at=t_y5,
        visibility=Visibility.FAMILY,
    )
    sparks.save(spark_y5)

    # 3. Advance 10 more years (Total 15 years): Teenage reflection
    clock.advance(days=365 * 10)
    t_y15 = clock.now()
    spark_y15 = Spark.capture(
        spark_id=SparkId("spark-y15"),
        family_id=family_id,
        owner_id=father_id,
        subject_child_id=child_id,
        source=SourceRef.from_text("Heading off to his first robotics state championship."),
        at=t_y15,
        visibility=Visibility.FAMILY,
    )
    sparks.save(spark_y15)

    # 4. Export the entire sovereign archive after 15 years
    export_use_case = ExportArchiveUseCase(
        families,
        sparks,
        moments,
        voice_notes,
        little_things,
        lexicon,
        media_store,
        clock=clock,
    )

    export_dest = tmp_path / "export_output"
    export_dest.mkdir(parents=True, exist_ok=True)

    export_res = export_use_case.execute(family_id, destination_dir=export_dest)
    assert export_res.is_ok()
    result = export_res.unwrap()

    # 5. Assert export completeness and offline reader presence
    assert result.file_count >= 3

    # Verify standard readable files on filesystem
    archive_json = export_dest / "archive.json"
    reader_html = export_dest / "READER.html"
    manifest_json = export_dest / "manifest.json"

    assert archive_json.exists()
    assert reader_html.exists()
    assert manifest_json.exists()

    # Verify archive content validity
    archive_data = json.loads(archive_json.read_text(encoding="utf-8"))
    assert archive_data["family"]["name"] == "The Singhs"
    assert archive_data["counts"]["sparks"] == 3

    # Verify READER.html is self-contained with no external CSS/JS network links
    reader_content = reader_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in reader_content
    assert "https://" not in reader_content  # Zero remote CDNs or tracking links
    assert "http://" not in reader_content
