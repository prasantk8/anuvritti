"""TASK-908 - Import what already exists (PRD 9, PRD 47).

A Photos export, a WhatsApp chat, a Notes dump become Sparks and Moments with source
IMPORTED and their original dates, so the first film has a childhood in it and not just a month.
Nothing is inferred that the import did not carry.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteLittleThingRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqliteSparkRepository,
    SqliteVoiceNoteRepository,
)
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmCommand,
    ComposeFilmUseCase,
    VerifyProvenanceUseCase,
)
from anuvritti.application.import_ import (
    ImportNotesCommand,
    ImportPhotosCommand,
    ImportUseCase,
    ImportWhatsAppCommand,
    NoteImportItem,
    PhotoImportItem,
)
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.values import (
    AttributionSource,
    MemberRole,
    SourceKind,
    SparkStatus,
)
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MemberId,
    SequentialIdGenerator,
)
from tests.support.fakes import RecordingEventPublisher


class DummyUow:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def env(tmp_path: Path):
    db_path = tmp_path / "test.db"
    media_dir = tmp_path / "media"
    conn = connect(str(db_path))
    migrate(conn)

    clock = FrozenClock(datetime(2026, 8, 29, 12, 0, tzinfo=UTC))
    ids = SequentialIdGenerator("imp")
    events = RecordingEventPublisher()
    uow = DummyUow()

    families = SqliteFamilyRepository(conn)
    sparks = SqliteSparkRepository(conn)
    moments = SqliteMomentRepository(conn)
    little_things = SqliteLittleThingRepository(conn)
    voice_notes = SqliteVoiceNoteRepository(conn)
    catalogue = SqliteMediaCatalogue(conn)

    media_key = Fernet.generate_key().decode()
    media_store = EncryptedFilesystemMediaStore(
        root=media_dir,
        catalogue=catalogue,
        ids=ids,
        encryption_key=media_key,
        max_bytes=10 * 1024 * 1024,
        allowed_mime_types=frozenset({"image/jpeg", "image/png", "audio/mp4"}),
    )

    family_id = FamilyId("fam-001")
    papa_id = MemberId("mem-papa")
    mama_id = MemberId("mem-mama")
    child_id = ChildId("child-leo")

    family = Family(
        id=family_id,
        name="The Family",
        members=(
            Member(papa_id, "Papa", MemberRole.PARENT),
            Member(mama_id, "Mama", MemberRole.CO_PARENT),
        ),
        children=(ChildProfile(child_id, papa_id, "Leo", date(2022, 5, 14)),),
        created_at=datetime(2022, 5, 14, 10, 0, tzinfo=UTC),
    )
    families.save(family)

    use_case = ImportUseCase(
        families=families,
        sparks=sparks,
        moments=moments,
        little_things=little_things,
        media=media_store,
        events=events,
        ids=ids,
        clock=clock,
        uow=uow,
    )

    return {
        "use_case": use_case,
        "families": families,
        "sparks": sparks,
        "moments": moments,
        "little_things": little_things,
        "voice_notes": voice_notes,
        "media": media_store,
        "family_id": family_id,
        "papa_id": papa_id,
        "mama_id": mama_id,
        "child_id": child_id,
        "clock": clock,
    }


def test_import_photos_preserves_historical_dates_and_provenance(env):
    use_case: ImportUseCase = env["use_case"]
    family_id: FamilyId = env["family_id"]
    papa_id: MemberId = env["papa_id"]
    child_id: ChildId = env["child_id"]

    photo_1_time = datetime(2023, 6, 15, 14, 30, tzinfo=UTC)
    photo_2_time = datetime(2024, 8, 20, 10, 15, tzinfo=UTC)

    photos = [
        PhotoImportItem(
            filename="IMG_20230615_FirstSteps.jpg",
            content=b"JPEG_BYTES_LEO_FIRST_STEPS",
            mime_type="image/jpeg",
            taken_at=photo_1_time,
            description="Leo took his first three steps across the living room rug.",
            subject_child_id=child_id,
        ),
        PhotoImportItem(
            filename="IMG_20240820_BeachCastle.jpg",
            content=b"JPEG_BYTES_BEACH_SANDCASTLE",
            mime_type="image/jpeg",
            taken_at=photo_2_time,
            description="Building the big moat at the beach.",
            subject_child_id=child_id,
        ),
    ]

    report = use_case.import_photos(
        ImportPhotosCommand(
            family_id=family_id,
            actor_id=papa_id,
            photos=photos,
            default_child_id=child_id,
        )
    ).unwrap()

    assert len(report.sparks) == 2
    assert len(report.moments) == 2

    # Check Spark 1
    s1 = report.sparks[0]
    assert s1.source.kind is SourceKind.IMPORTED
    assert s1.created_at == photo_1_time
    assert s1.intent.source is AttributionSource.HUMAN
    assert s1.status is SparkStatus.EXPERIENCED

    # Check Moment 1
    m1 = report.moments[0]
    assert m1.happened_on == date(2023, 6, 15)
    assert m1.created_at == photo_1_time
    assert m1.reflection == "Leo took his first three steps across the living room rug."

    # Verify media is retrievable and matches
    media_obj = env["media"].get(m1.photo_media_id).unwrap()
    assert media_obj == b"JPEG_BYTES_LEO_FIRST_STEPS"


def test_import_whatsapp_chat_parses_messages_and_attachments(env):
    use_case: ImportUseCase = env["use_case"]
    family_id: FamilyId = env["family_id"]
    papa_id: MemberId = env["papa_id"]
    mama_id: MemberId = env["mama_id"]
    child_id: ChildId = env["child_id"]

    chat_text = """
[14/05/2023, 10:30:15] Messages and calls are end-to-end encrypted. \
 No one outside of this chat can read or listen to them.
[14/05/2023, 10:32:00] Papa: Leo just woke up pointing at the sky saying 'birdie'!
[14/05/2023, 11:00:20] Mama: Look what he painted today <attached: painting.jpg>
[15/05/2023, 08:15:45] Papa: He ate a whole banana without dropping any.
"""

    media_files = {
        "painting.jpg": (b"JPEG_BYTES_TODDLER_PAINTING", "image/jpeg"),
    }
    author_map = {
        "Papa": papa_id,
        "Mama": mama_id,
    }

    report = use_case.import_whatsapp(
        ImportWhatsAppCommand(
            family_id=family_id,
            actor_id=papa_id,
            chat_text=chat_text,
            media_files=media_files,
            author_map=author_map,
            default_child_id=child_id,
        )
    ).unwrap()

    assert len(report.sparks) == 1  # 1 photo attachment
    assert len(report.moments) == 1
    assert len(report.little_things) == 2  # 2 text observations

    moment = report.moments[0]
    assert moment.created_by == mama_id
    assert moment.happened_on == date(2023, 5, 14)
    assert moment.reflection == "Look what he painted today"

    lt1 = report.little_things[0]
    assert lt1.author_id == papa_id
    assert "pointing at the sky" in lt1.text
    assert lt1.created_at == datetime(2023, 5, 14, 10, 32, 0, tzinfo=UTC)


def test_import_notes_creates_waiting_sparks_with_authentic_dates(env):
    use_case: ImportUseCase = env["use_case"]
    family_id: FamilyId = env["family_id"]
    papa_id: MemberId = env["papa_id"]
    child_id: ChildId = env["child_id"]

    note_date = datetime(2024, 1, 10, 18, 0, tzinfo=UTC)
    notes = [
        NoteImportItem(
            title="Things to build together when he turns 4",
            text="1. Cardboard rocket ship\n2. Wooden toolbox\n3. Herb garden in the backyard",
            created_at=note_date,
            subject_child_id=child_id,
        )
    ]

    report = use_case.import_notes(
        ImportNotesCommand(
            family_id=family_id,
            actor_id=papa_id,
            notes=notes,
            default_child_id=child_id,
        )
    ).unwrap()

    assert len(report.sparks) == 1
    spark = report.sparks[0]
    assert spark.title == "Things to build together when he turns 4"
    assert spark.status is SparkStatus.WAITING
    assert spark.source.kind is SourceKind.IMPORTED
    assert spark.created_at == note_date


def test_imported_memories_feed_cleanly_into_film_provenance(env):
    """PRD 47: the first film over imported childhood memories has verified provenance."""
    use_case: ImportUseCase = env["use_case"]
    family_id: FamilyId = env["family_id"]
    papa_id: MemberId = env["papa_id"]
    child_id: ChildId = env["child_id"]

    # Import 3 years of memories
    t1 = datetime(2023, 4, 10, 10, 0, tzinfo=UTC)
    t2 = datetime(2024, 6, 12, 11, 0, tzinfo=UTC)
    t3 = datetime(2025, 7, 14, 16, 0, tzinfo=UTC)

    photos = [
        PhotoImportItem(
            filename="year1.jpg",
            content=b"JPEG_YEAR_1",
            mime_type="image/jpeg",
            taken_at=t1,
            description="First birthday party with balloons",
            subject_child_id=child_id,
        ),
        PhotoImportItem(
            filename="year2.jpg",
            content=b"JPEG_YEAR_2",
            mime_type="image/jpeg",
            taken_at=t2,
            description="Learning to ride the balance bike",
            subject_child_id=child_id,
        ),
        PhotoImportItem(
            filename="year3.jpg",
            content=b"JPEG_YEAR_3",
            mime_type="image/jpeg",
            taken_at=t3,
            description="Swimming in the lake with Papa",
            subject_child_id=child_id,
        ),
    ]

    use_case.import_photos(
        ImportPhotosCommand(
            family_id=family_id,
            actor_id=papa_id,
            photos=photos,
            default_child_id=child_id,
        )
    ).unwrap()

    # Now run film composer and verify provenance
    composer = ComposeFilmUseCase(
        families=env["families"],
        sparks=env["sparks"],
        moments=env["moments"],
        voice_notes=env["voice_notes"],
        media=env["media"],
        ids=SequentialIdGenerator("film"),
    )
    verifier = VerifyProvenanceUseCase(
        sparks=env["sparks"],
        moments=env["moments"],
        voice_notes=env["voice_notes"],
        little_things=env["little_things"],
        media=env["media"],
        clock=env["clock"],
    )
    compiler = FilmkitFilmCompiler()
    pipeline = CompileFilmUseCase(compose=composer, verify=verifier, compiler=compiler)

    package = pipeline.execute(ComposeFilmCommand(family_id=family_id, actor_id=papa_id)).unwrap()

    assert package.provenance.is_clean
    assert len(package.provenance.entries) > 0
    # Every evidence citation comes from genuine imported moments
    assert all(e.status.value == "VERIFIED" for e in package.provenance.entries)
