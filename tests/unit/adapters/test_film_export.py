"""The export refuses more often than it writes, which is the right ratio for this module.

Everything the exporter touches is a real photograph or a real recording of a child, being
copied out of the vault in plaintext so a renderer can open it. The three refusals here are
what keeps that copy from being wrong in a way nobody sees: a folder already holding another
film, a file the store will not hand over, and bytes that are not the ones this film was
measured against.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.film.export import (
    FILM_FILENAME,
    MEDIA_DIRECTORY,
    FilesystemFilmExporter,
)
from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmCommand,
    ComposeFilmUseCase,
)
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.domain.film import PROVENANCE_FILENAME, MediaBundle
from anuvritti.domain.moment import Moment
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceRef
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    MomentId,
    SequentialIdGenerator,
    SparkId,
)
from anuvritti.shared.result import Err
from tests.support.fakes import (
    CHILD,
    FAMILY,
    PAPA,
    InMemoryFamilyRepository,
    InMemoryLittleThingRepository,
    InMemoryMediaStore,
    InMemoryMomentRepository,
    InMemorySparkRepository,
    InMemoryVoiceNoteRepository,
    build_family,
)

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
DAY = date(2026, 6, 11)
PICTURE = b"\xff\xd8\xff\xe0" + b"soaked through, delighted" * 15


@pytest.fixture
def package():
    media = InMemoryMediaStore()
    photo = str(media.put(FAMILY, content=PICTURE, mime_type="image/jpeg", at=NOW).unwrap().id)

    sparks = InMemorySparkRepository()
    moments = InMemoryMomentRepository()
    at = datetime.combine(DAY, datetime.min.time(), tzinfo=UTC)
    spark = sparks.save(
        Spark.capture(
            spark_id=SparkId("spk-1"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_text("ran straight into the sprinkler"),
            at=at,
            subject_child_id=CHILD,
        )
    ).unwrap()
    moments.save(
        Moment.create(
            moment_id=MomentId("mom-1"),
            family_id=FAMILY,
            spark_id=spark.id,
            created_by=PAPA,
            spark_captured_at=at,
            at=at,
            happened_on=DAY,
            photo_media_id=photo,
        ).unwrap()
    )

    use_case = CompileFilmUseCase(
        compose=ComposeFilmUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=sparks,
            moments=moments,
            voice_notes=InMemoryVoiceNoteRepository(),
            media=media,
            ids=SequentialIdGenerator("film"),
        ),
        verify=VerifyProvenanceUseCase(
            sparks=sparks,
            moments=moments,
            voice_notes=InMemoryVoiceNoteRepository(),
            little_things=InMemoryLittleThingRepository(),
            media=media,
            clock=FrozenClock(NOW),
        ),
        compiler=FilmkitFilmCompiler(),
    )
    compiled = use_case.execute(ComposeFilmCommand(family_id=FAMILY, actor_id=PAPA)).unwrap()
    return compiled, media


class TestWhatLandsOnDisk:
    def test_the_film_its_receipts_and_its_files_all_arrive(self, package, tmp_path: Path):
        film, media = package

        export = FilesystemFilmExporter(media).export(film, into=tmp_path / "out").unwrap()

        assert (tmp_path / "out" / FILM_FILENAME).exists()
        assert (tmp_path / "out" / PROVENANCE_FILENAME).exists()
        assert [p.parent.name for p in export.media_paths] == [MEDIA_DIRECTORY]
        assert export.byte_size == len(PICTURE)

    def test_a_photograph_keeps_the_extension_its_type_implies(self, package, tmp_path: Path):
        """A renderer's cache is keyed on these names, so they cannot depend on the machine."""
        film, media = package

        export = FilesystemFilmExporter(media).export(film, into=tmp_path / "out").unwrap()

        assert export.media_paths[0].suffix == ".jpg"
        assert export.media_paths[0].read_bytes() == PICTURE

    def test_the_folder_is_not_readable_by_the_rest_of_the_machine(self, package, tmp_path: Path):
        film, media = package

        FilesystemFilmExporter(media).export(film, into=tmp_path / "out")

        assert (tmp_path / "out" / MEDIA_DIRECTORY).stat().st_mode & 0o077 == 0


class TestTheRefusals:
    def test_a_folder_that_already_holds_something_is_left_alone(self, package, tmp_path: Path):
        film, media = package
        existing = tmp_path / "out"
        existing.mkdir()
        (existing / "somebody-elses-film.json").write_text("{}")

        error = FilesystemFilmExporter(media).export(film, into=existing).unwrap_err()

        assert error.code is ErrorCode.CONFLICT
        assert not (existing / MEDIA_DIRECTORY).exists()

    def test_a_file_the_store_will_not_hand_over_stops_the_export(self, package, tmp_path: Path):
        film, _ = package

        class Locked:
            def get(self, media_id):
                return Err(DomainError(ErrorCode.PERMISSION_DENIED, "the key is not here"))

        error = FilesystemFilmExporter(Locked()).export(film, into=tmp_path / "out").unwrap_err()

        assert error.code is ErrorCode.PERMISSION_DENIED

    def test_bytes_that_are_not_the_ones_this_film_measured_do_not_travel(
        self, package, tmp_path: Path
    ):
        """The store answered, and its answer disagreed with the bundle. Nothing ships."""
        film, media = package
        forged = replace(
            film,
            draft=replace(
                film.draft,
                bundle=MediaBundle(
                    tuple(replace(item, content_hash="d" * 64) for item in film.bundle.items)
                ),
            ),
        )

        error = FilesystemFilmExporter(media).export(forged, into=tmp_path / "out").unwrap_err()

        assert error.code is ErrorCode.CONFLICT
        assert "will not travel" in error.message
