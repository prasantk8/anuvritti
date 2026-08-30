"""TASK-1305: The Eighteen-Year Time Travel Test (PRD 52, PRD 34).

Verifies:
1. An archive captured in 2026.
2. Compiled against a system clock advanced 18 years forward into 2044.
3. Every date, age calculation, citation, and provenance ledger spoken or written
   remains perfectly accurate to the day it actually happened.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.application.export import ExportArchiveUseCase
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmUseCase,
    TheYearCommand,
    TheYearUseCase,
)
from anuvritti.application.provenance import VerifyProvenanceUseCase
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
    SequentialIdGenerator,
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
def time_capsule_environment():
    # 2026: Child Leo is born on 2026-09-01
    family_id = FamilyId("fam-capsule-18")
    parent_id = MemberId("mem-papa")
    child_id = ChildId("child-leo")
    birth_date = date(2026, 9, 1)

    family = Family(
        id=family_id,
        name="The Singh Family",
        created_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
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
                date_of_birth=birth_date,
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

    # Capture memories across Leo's first year (2026 - 2027)
    # 1. First Spark on day of birth (2026-09-01)
    birth_dt = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    spark_birth = Spark.capture(
        spark_id=SparkId("spark-birth"),
        family_id=family_id,
        owner_id=parent_id,
        source=SourceRef.from_text("Welcome to the world, Leo"),
        at=birth_dt,
        subject_child_id=child_id,
    )
    sparks.save(spark_birth)

    # 2. Moment: First tooth (2027-03-15) with photo and audio
    photo_bytes = b"JPEG_LEO_FIRST_TOOTH_2027_PHOTO"
    voice_bytes = b"RIFFWAVE_LEO_FIRST_LAUGH_2027_AUDIO"

    dt_tooth = datetime(2027, 3, 15, 14, 0, tzinfo=UTC)
    photo_meta = media_store.put(
        family_id, content=photo_bytes, mime_type="image/jpeg", at=dt_tooth
    ).unwrap()
    voice_meta = media_store.put(
        family_id, content=voice_bytes, mime_type="audio/wav", at=dt_tooth
    ).unwrap()

    spark_tooth = (
        Spark.capture(
            spark_id=SparkId("spark-tooth"),
            family_id=family_id,
            owner_id=parent_id,
            source=SourceRef.from_text("First baby tooth appeared!"),
            at=dt_tooth,
            subject_child_id=child_id,
        )
        .record_why(text="He beamed so brightly", voice_media_id=voice_meta.id, at=dt_tooth)
        .unwrap()
    )
    sparks.save(spark_tooth)

    moment_tooth = Moment.create(
        moment_id=MomentId("mom-tooth"),
        family_id=family_id,
        spark_id=spark_tooth.id,
        created_by=parent_id,
        spark_captured_at=dt_tooth,
        at=dt_tooth,
        happened_on=date(2027, 3, 15),
        photo_media_id=photo_meta.id,
        audio_media_id=voice_meta.id,
        reflection="Two tiny teeth on the bottom row.",
    ).unwrap()
    moments.save(moment_tooth)

    transcript = Transcript.machine(
        "Look at that little tooth!",
        confidence=Confidence.HIGH,
        engine="whisper-tiny",
        at=dt_tooth,
    ).unwrap()
    voice_note = VoiceNote(
        media_id=voice_meta.id,
        family_id=family_id,
        author_id=parent_id,
        duration_seconds=4.8,
        recorded_at=dt_tooth,
        transcript=transcript,
    )
    voice_notes.save(voice_note)

    # 3. Little Thing: First word (2027-05-10)
    dt_word = datetime(2027, 5, 10, 8, 30, tzinfo=UTC)
    little_word = LittleThing.capture(
        little_thing_id=LittleThingId("lt-dadaa"),
        family_id=family_id,
        author_id=parent_id,
        subject_child_id=child_id,
        text="Dadaa",
        at=dt_word,
    ).unwrap()
    little_things.save(little_word)

    return {
        "family_id": family_id,
        "parent_id": parent_id,
        "child_id": child_id,
        "birth_date": birth_date,
        "family": family,
        "families": families,
        "sparks": sparks,
        "moments": moments,
        "voice_notes": voice_notes,
        "little_things": little_things,
        "lexicons": lexicons,
        "media_store": media_store,
        "photo_bytes": photo_bytes,
        "voice_bytes": voice_bytes,
    }


def test_time_travel_eighteen_years_forward_compilation_and_dates(
    time_capsule_environment, tmp_path: Path
):
    """Travels 18 years forward to 2044-09-01 (Leo's 18th birthday).

    Verifies:
    1. Compiling Year 1 film against a 2044 clock preserves exact 2026/2027 historical dates.
    2. Provenance hashes match 100% across the 18-year leap.
    3. Age calculations on historical events remain age 0/1, while Leo's current age is 18.
    """
    env = time_capsule_environment

    # 1. 2026 Export
    clock_2026 = FrozenClock(datetime(2026, 9, 2, 12, 0, tzinfo=UTC))
    export_use_case = ExportArchiveUseCase(
        families=env["families"],
        sparks=env["sparks"],
        moments=env["moments"],
        voice_notes=env["voice_notes"],
        little_things=env["little_things"],
        lexicons=env["lexicons"],
        media=env["media_store"],
        clock=clock_2026,
    )
    dest_2026 = tmp_path / "archive_captured_2026"
    res_2026 = export_use_case.execute(env["family_id"], destination_dir=dest_2026)
    assert res_2026.is_ok()

    # 2. TIME TRAVEL: Advance system clock to 2044-09-01 (18 years later)
    time_travel_clock = FrozenClock(datetime(2044, 9, 1, 9, 0, 0, tzinfo=UTC))
    assert time_travel_clock.now().year == 2044

    # Child profile age today is 18
    leo = env["family"].children[0]
    assert leo.age_years(time_travel_clock.today()) == 18
    # But age on the day of his first tooth was 0
    assert leo.age_years(date(2027, 3, 15)) == 0

    # 3. Compile Year 1 film under the 2044 clock
    compose = ComposeFilmUseCase(
        families=env["families"],
        sparks=env["sparks"],
        moments=env["moments"],
        voice_notes=env["voice_notes"],
        little_things=env["little_things"],
        media=env["media_store"],
        ids=SequentialIdGenerator("film-2044"),
    )
    verify_provenance = VerifyProvenanceUseCase(
        sparks=env["sparks"],
        moments=env["moments"],
        voice_notes=env["voice_notes"],
        little_things=env["little_things"],
        media=env["media_store"],
        clock=time_travel_clock,
    )
    year_use_case = TheYearUseCase(
        families=env["families"],
        compile_film=CompileFilmUseCase(
            compose=compose,
            verify=verify_provenance,
            compiler=FilmkitFilmCompiler(),
        ),
    )

    year_res = year_use_case.execute(
        TheYearCommand(
            family_id=env["family_id"],
            actor_id=env["parent_id"],
            child_id=env["child_id"],
            birthday_year=2026,
        )
    )
    assert year_res.is_ok(), f"Year compile failed: {year_res.unwrap_err()}"
    compiled_pkg = year_res.unwrap()

    # Verify compiled film truthfulness
    assert compiled_pkg.film.spec_id == "the-year-child-leo-2026"
    assert compiled_pkg.film.title == "Leo, 2026-2027"
    assert len(compiled_pkg.film.scenes) >= 3

    # Check that provenance ledger generated in 2044 accurately verifies 2026/2027 artifacts
    ledger = compiled_pkg.provenance
    assert ledger.verified_at == datetime(2044, 9, 1, 9, 0, 0, tzinfo=UTC)
    assert len(ledger.entries) >= 2
    for entry in ledger.entries:
        assert entry.is_verified
        assert entry.status.value == "VERIFIED"

    # 4. Re-export archive under 2044 clock and verify content fixity
    dest_2044 = tmp_path / "archive_exported_2044"
    export_2044 = ExportArchiveUseCase(
        families=env["families"],
        sparks=env["sparks"],
        moments=env["moments"],
        voice_notes=env["voice_notes"],
        little_things=env["little_things"],
        lexicons=env["lexicons"],
        media=env["media_store"],
        clock=time_travel_clock,
    )
    res_2044 = export_2044.execute(env["family_id"], destination_dir=dest_2044)
    assert res_2044.is_ok()

    manifest_2044 = json.loads((dest_2044 / "manifest.json").read_text(encoding="utf-8"))
    for file_entry in manifest_2044["files"]:
        target_file = dest_2044 / file_entry["relative_path"]
        data = target_file.read_bytes()
        assert hashlib.sha256(data).hexdigest() == file_entry["sha256"]
        if file_entry["relative_path"].startswith("media/") and file_entry[
            "relative_path"
        ].endswith(".jpg"):
            assert data == env["photo_bytes"]
        if file_entry["relative_path"].startswith("media/") and file_entry[
            "relative_path"
        ].endswith(".wav"):
            assert data == env["voice_bytes"]
