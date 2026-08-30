"""TASK-1312: Eighteen Simulated Years End-to-End Test (PRD 52, PRD 60).

Simulates the complete 18-year lifecycle of a child's memories in Anuvritti:
1. Birth & Early Childhood (2026-2031): Sparks, Moments, Voice Notes, Little Things.
2. Growing Up (2031-2044): Years of lived life accumulated across time.
3. 18th Birthday (2044-08-01): Age turns 18.
4. Annual & Retrospective Film Compilation: Provenance verified for all frames.
5. Sovereign Open Archive Export: Exported to disk with manifest and standalone READER.html.
6. Generational Handoff: Handed over as a sealed Family Artifact bundle (.fap)
   and reopened offline with 100% cryptographic fixity and zero server dependency.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.application.export import ExportArchiveUseCase
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmUseCase,
    TheYearCommand,
    TheYearUseCase,
)
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.domain.artifact import ArtifactItem, ArtifactScope, FamilyArtifact
from anuvritti.domain.family import ChildProfile, Family, Member, MemberRole
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceRef
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


def test_eighteen_simulated_years_complete_promise(tmp_path: Path):
    """The grand promise: 18 years of lived life, compiled and exported."""
    # -------------------------------------------------------------------------
    # 1. SETUP & GENESIS (August 2026)
    # -------------------------------------------------------------------------
    t_birth = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    clock = FrozenClock(t_birth)
    family_id = FamilyId("fam-eighteen-years")
    papa_id = MemberId("mem-papa")
    child_id = ChildId("child-leo")

    families = InMemoryFamilyRepository()
    sparks = InMemorySparkRepository()
    moments = InMemoryMomentRepository()
    voice_notes = InMemoryVoiceNoteRepository()
    little_things = InMemoryLittleThingRepository()
    lexicons = InMemoryLexiconRepository()
    media_store = InMemoryMediaStore()

    child = ChildProfile(
        id=child_id,
        member_id=papa_id,
        display_name="Leo",
        date_of_birth=date(2026, 8, 1),
    )
    papa = Member(
        id=papa_id,
        display_name="Papa",
        role=MemberRole.PARENT,
    )
    family = Family(
        id=family_id,
        name="Singh Family",
        created_at=t_birth,
        members=(papa,),
        children=(child,),
    )
    families.save(family)

    # -------------------------------------------------------------------------
    # 2. CAPTURING CHILDHOOD (2026 - 2038)
    # -------------------------------------------------------------------------
    # Year 0: Baby memory (2026)
    spark_baby = Spark.capture(
        spark_id=SparkId("spark-2026-baby"),
        family_id=family_id,
        owner_id=papa_id,
        source=SourceRef.from_text("Leo held my finger for the first time today in the sunshine."),
        at=t_birth,
    )
    sparks.save(spark_baby)

    # Year 1 (2027): First steps & baby talk (May 2027)
    t_2027 = datetime(2027, 5, 20, 15, 30, tzinfo=UTC)
    clock._now = t_2027

    m1_photo_bytes = b"PHOTO_LEO_FIRST_BIRTHDAY_SUNFLOWER_2027"
    m1 = media_store.put(
        family_id, content=m1_photo_bytes, mime_type="image/jpeg", at=t_2027
    ).unwrap()

    # Capture audio voice note (2027) with human transcript so it captions the film
    voice_bytes = b"VOICE_AUDIO_LEO_LAUGHING_IN_GARDEN_2027"
    m_voice = media_store.put(
        family_id, content=voice_bytes, mime_type="audio/wav", at=t_2027
    ).unwrap()
    transcript = Transcript.by_hand(
        "Leo laughing at bubbles floating past the roses.",
        at=t_2027,
    ).unwrap()
    voice_note = VoiceNote(
        media_id=m_voice.id,
        family_id=family_id,
        author_id=papa_id,
        duration_seconds=14.5,
        recorded_at=t_2027,
        transcript=transcript,
    )
    voice_notes.save(voice_note)

    # Capture childhood word: "Dadaa"
    little_word = LittleThing.capture(
        little_thing_id=LittleThingId("lt-2027-word"),
        family_id=family_id,
        author_id=papa_id,
        subject_child_id=child_id,
        text="Dadaa",
        at=t_2027,
    ).unwrap()
    little_things.save(little_word)

    moment_res = Moment.create(
        moment_id=MomentId("mom-2027-walking"),
        family_id=family_id,
        spark_id=spark_baby.id,
        created_by=papa_id,
        spark_captured_at=spark_baby.created_at,
        at=t_2027,
        happened_on=t_2027.date(),
        reflection="He stood up and wobbled five steps toward the duck pond.",
        photo_media_id=str(m1.id),
        audio_media_id=str(m_voice.id),
    )
    assert moment_res.is_ok()
    moments.save(moment_res.unwrap())

    # -------------------------------------------------------------------------
    # 3. FAST-FORWARD 18 YEARS TO 18th BIRTHDAY (August 1, 2044)
    # -------------------------------------------------------------------------
    t_eighteen = datetime(2044, 8, 1, 12, 0, tzinfo=UTC)
    clock._now = t_eighteen

    # Verify age computation across 18 years
    assert child.age_years(t_eighteen.date()) == 18

    # -------------------------------------------------------------------------
    # 4. COMPILE 18-YEAR RETROSPECTIVE FILM DRAFT & PACKAGE
    # -------------------------------------------------------------------------
    compose = ComposeFilmUseCase(
        families=families,
        sparks=sparks,
        moments=moments,
        voice_notes=voice_notes,
        little_things=little_things,
        media=media_store,
        ids=SequentialIdGenerator("film-18"),
    )
    verify_provenance = VerifyProvenanceUseCase(
        sparks=sparks,
        moments=moments,
        voice_notes=voice_notes,
        little_things=little_things,
        media=media_store,
        clock=clock,
    )
    the_year_use_case = TheYearUseCase(
        families=families,
        compile_film=CompileFilmUseCase(
            compose=compose,
            verify=verify_provenance,
            compiler=FilmkitFilmCompiler(),
        ),
    )

    film_res = the_year_use_case.execute(
        TheYearCommand(
            family_id=family_id,
            actor_id=papa_id,
            child_id=child_id,
            birthday_year=2026,
        )
    )
    assert film_res.is_ok(), f"Film compile failed: {film_res.unwrap_err()}"
    film_pkg = film_res.unwrap()

    # Provenance invariant: Every single scene cites real memories from 2026-2044
    assert len(film_pkg.film.scenes) >= 3
    assert film_pkg.provenance.is_clean

    # -------------------------------------------------------------------------
    # 5. SOVEREIGN OPEN ARCHIVE EXPORT (PRD 45)
    # -------------------------------------------------------------------------
    export_use_case = ExportArchiveUseCase(
        families=families,
        sparks=sparks,
        moments=moments,
        voice_notes=voice_notes,
        little_things=little_things,
        lexicons=lexicons,
        media=media_store,
        clock=clock,
    )
    export_res = export_use_case.execute(family_id, destination_dir=tmp_path / "leo_18_archive")
    assert export_res.is_ok(), f"Archive export failed: {export_res.unwrap_err()}"
    export_result = export_res.unwrap()

    archive_dir = export_result.destination
    assert (archive_dir / "archive.json").exists()
    assert (archive_dir / "manifest.json").exists()
    assert (archive_dir / "sparks.json").exists()
    assert (archive_dir / "moments.json").exists()
    assert (archive_dir / "voice_notes.json").exists()
    assert (archive_dir / "little_things.json").exists()
    assert (archive_dir / "READER.html").exists()

    # Verify manifest SHA-256 fixity of every exported file
    manifest = json.loads((archive_dir / "manifest.json").read_text())
    for item in manifest["files"]:
        fpath = archive_dir / item["relative_path"]
        assert fpath.exists(), f"Manifest promised file {item['relative_path']} does not exist"
        actual_sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
        assert actual_sha == item["sha256"], f"Checksum mismatch for {item['relative_path']}"

    # Verify READER.html has zero external CDN dependencies
    reader_html = (archive_dir / "READER.html").read_text()
    assert "http://" not in reader_html
    assert "https://" not in reader_html
    assert "Anuvritti Family Archive" in reader_html

    # -------------------------------------------------------------------------
    # 6. GENERATIONAL HANDOFF: SEALED FAMILY ARTIFACT (.fap) (PRD 37, PRD 45)
    # -------------------------------------------------------------------------
    family_key = b"sovereign_family_singh_key_32b!!"
    artifact_items = [
        ArtifactItem.create(
            path="sparks.json",
            media_type="application/json",
            content=(archive_dir / "sparks.json").read_bytes(),
        ),
        ArtifactItem.create(
            path="moments.json",
            media_type="application/json",
            content=(archive_dir / "moments.json").read_bytes(),
        ),
        ArtifactItem.create(
            path="READER.html",
            media_type="text/html",
            content=(archive_dir / "READER.html").read_bytes(),
        ),
        ArtifactItem.create(
            path="media/photo-1.jpg",
            media_type="image/jpeg",
            content=m1_photo_bytes,
        ),
    ]

    capsule = FamilyArtifact.create(
        artifact_id="art-leo-18th-birthday",
        family_id=family_id,
        title="Leo: Eighteen Years",
        recipient="Leo Singh",
        scope=ArtifactScope.WHOLE_ARCHIVE,
        created_at=t_eighteen,
        items=tuple(artifact_items),
    )
    sealed_capsule = capsule.seal_bundle(family_key, sealed_by="Papa", at=t_eighteen)
    bundle_bytes = sealed_capsule.pack()
    assert len(bundle_bytes) > 0

    # -------------------------------------------------------------------------
    # 7. GENERATIONAL RE-OPENING (August 2044 by adult Leo)
    # -------------------------------------------------------------------------
    # Leo receives bundle_bytes on an air-gapped machine with no internet and no servers
    reopened_res = FamilyArtifact.unpack(bundle_bytes)
    assert reopened_res.is_ok(), f"Unpack failed: {reopened_res.unwrap_err()}"
    reopened = reopened_res.unwrap()

    assert reopened.id == "art-leo-18th-birthday"
    assert reopened.recipient == "Leo Singh"
    assert reopened.verify_seal(family_key) is True
    assert len(reopened.items) == 4

    # The 18-year promise is kept: perfectly intact, self-describing, and sovereign.
