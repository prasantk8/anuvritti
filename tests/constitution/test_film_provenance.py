"""PRD 8.7, 47 - a film may only claim what the archive can show.

autovideo has a rule that every frame is traceable to a source it can name, and the reason
it survives contact with deadlines is that it is a build failure rather than a review
comment. This file applies the same rule to something much less forgiving than a marketing
video: a record of a childhood, which the child eventually watches, and which is the only
version of those years they will have.

The specific failure this guards against does not look like a bug. It looks like a good
film. A scene appears that nobody can trace - a nice line, a plausible afternoon, a
photograph attached to a memory it was not from - and it is beautiful, and it is watched at
eighteen, and it becomes something the person believes about their own childhood. Nothing
crashes. No test goes red. There is no one to notice, because the only witness was four.

So the boundary here is drawn in three places, and each one is a different way of saying
the same thing:

1. Every citation in a compiled film has been *followed*, not just written down.
2. A film with even one citation that cannot be followed does not get built.
3. The ledger of what was followed ships with the film, as `provenance.json`, so the
   guarantee outlives this codebase, this company and this decade.

If a test in this file starts failing, the question is never how to make it pass. It is
which of those three the product just stopped doing.
"""

from __future__ import annotations

import json
from dataclasses import MISSING, fields, replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.film.export import FILM_FILENAME, FilesystemFilmExporter
from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.adapters.film.render import ChromiumFfmpegRenderer
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmCommand,
)
from anuvritti.domain.film import (
    PROVENANCE_FILENAME,
    Citation,
    CitationKind,
    FilmPackage,
    Provenance,
    ProvenanceEntry,
    ProvenanceStatus,
    SceneKind,
)
from anuvritti.domain.moment import Moment
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import (
    FamilyId,
    MomentId,
    SparkId,
)
from anuvritti.shared.result import Ok
from tests.support.archive import NOW, Archive, a_year
from tests.support.fakes import FAMILY, PAPA

pytestmark = pytest.mark.constitution


@pytest.fixture
def archive() -> Archive:
    return a_year()


class TestEveryCitationWasFollowed:
    """Written down is not the same as checked. This is the difference."""

    def test_a_film_that_ships_has_had_every_citation_verified(self, archive):
        package = archive.compile().unwrap()

        assert package.provenance.entries
        assert package.provenance.is_clean
        assert [entry.status for entry in package.provenance.entries] == [
            ProvenanceStatus.VERIFIED
        ] * len(package.provenance.entries)

    def test_the_ledger_covers_every_citation_in_the_film_with_nothing_left_over(self, archive):
        package = archive.compile().unwrap()

        claimed = {
            (scene.id, citation.kind.value, citation.id)
            for scene in package.spec.scenes
            for citation in scene.cites
        }
        assert package.provenance.keys == claimed

    def test_every_evidence_scene_is_represented_in_the_ledger(self, archive):
        """A scene that claims something appears in the ledger, by name."""
        package = archive.compile().unwrap()

        evidence = {scene.id for scene in package.spec.scenes if scene.kind.is_evidence}
        checked = {entry.scene_id for entry in package.provenance.entries}
        assert evidence and evidence <= checked

    def test_a_media_citation_is_verified_against_the_bytes_not_against_a_row(self, archive):
        """The catalogue is what the composer already trusted. Trusting it twice proves nothing.

        Tampering here changes the stored bytes and leaves every row saying what it said
        before, which is exactly the shape of the failure a database-only check misses.
        """
        drafted = archive.draft().unwrap()
        photo = sorted(drafted.bundle.ids)[0]
        archive.media.tamper(photo, b"a different photograph entirely")

        ledger = archive.verifier().execute(drafted).unwrap()

        altered = [e for e in ledger.entries if e.citation.id == photo]
        assert altered and all(e.status is ProvenanceStatus.ALTERED for e in altered)
        assert not ledger.is_clean


class TestAFilmThatCannotCiteIsNotBuilt:
    """The rule with teeth. Everything above is reporting; this is refusal.

    These tests hand the pipeline a spec the composer did not write, because that is the only
    honest way to model the threat. `ComposeFilmUseCase` builds citations out of rows it has
    just read, so it cannot produce an unfounded one today. The failure this guards against
    arrives the day something *else* produces a spec - an import, a template, a fixture, a
    second composer written in a hurry - and the checkpoint has to hold for specs it did not
    author, or it holds for nothing.
    """

    def _forged(self, archive, citation: Citation):
        """A real draft of a real year, with one scene taught to claim something extra."""
        draft = archive.draft().unwrap()
        scene = draft.spec.scenes[1]
        return replace(
            draft,
            spec=replace(
                draft.spec,
                scenes=(
                    draft.spec.scenes[0],
                    replace(scene, cites=(*scene.cites, citation)),
                    *draft.spec.scenes[2:],
                ),
            ),
        )

    def _pipeline(self, archive, draft, compiler=None):
        class Stranger:
            def execute(self, command):
                return Ok(draft)

        return CompileFilmUseCase(
            compose=Stranger(),
            verify=archive.verifier(),
            compiler=compiler or FilmkitFilmCompiler(),
        )

    def test_a_citation_to_a_spark_that_does_not_exist_stops_the_build(self, archive):
        """Not "drop the scene". A year does not get to be quietly shorter than it was."""
        forged = self._forged(archive, Citation(CitationKind.SPARK, "spk-nobody-wrote-this"))

        error = (
            self._pipeline(archive, forged)
            .execute(ComposeFilmCommand(family_id=FAMILY, actor_id=PAPA))
            .unwrap_err()
        )

        assert error.code is ErrorCode.FILM_NOT_COMPILABLE
        assert "nobody can find" in error.message
        assert error.details["cites"] == "spk-nobody-wrote-this"

    def test_a_citation_into_another_family_is_refused_and_told_nothing(self, archive):
        """The refusal must not double as a lookup service for other people's children."""
        theirs = archive.moments.save(
            Moment.create(
                moment_id=MomentId("mom-elsewhere"),
                family_id=FamilyId("fam-2"),
                spark_id=SparkId("spk-elsewhere"),
                created_by=PAPA,
                spark_captured_at=datetime(2026, 4, 1, tzinfo=UTC),
                at=NOW,
                happened_on=date(2026, 4, 1),
            ).unwrap()
        ).unwrap()
        forged = self._forged(archive, Citation(CitationKind.MOMENT, str(theirs.id)))

        ledger = archive.verifier().execute(forged).unwrap()

        foreign = next(e for e in ledger.entries if e.citation.id == str(theirs.id))
        unknown = (
            archive.verifier()
            .execute(self._forged(archive, Citation(CitationKind.MOMENT, "mom-nothing")))
            .unwrap()
        )
        stranger = next(e for e in unknown.entries if e.citation.id == "mom-nothing")
        assert (foreign.status, foreign.detail) == (stranger.status, stranger.detail)

    def test_altered_media_stops_the_build(self, archive):
        """The row is intact, the bytes are not. A film does not travel with a swapped file."""
        drafted = archive.draft().unwrap()
        archive.media.tamper(sorted(drafted.bundle.ids)[0], b"not the same picture")

        error = archive.compile().unwrap_err()

        assert error.code is ErrorCode.FILM_NOT_COMPILABLE
        assert error.details["status"] == ProvenanceStatus.ALTERED.value

    def test_a_replaced_recording_is_caught_even_though_its_row_still_measures_right(self, archive):
        """The worst version of this failure: the arithmetic still adds up.

        A voice note carries the measured length, and the length is what the film is built
        on. Swap the audio and leave the row alone and every downstream number stays correct
        while a child hears a different recording than the one that was cited.
        """
        drafted = archive.draft().unwrap()
        recording = sorted(drafted.bundle.ids)[-1]
        archive.media.tamper(recording, b"somebody else, saying something else")

        ledger = archive.verifier().execute(drafted).unwrap()

        swapped = next(e for e in ledger.entries if e.citation.kind is CitationKind.VOICE_NOTE)
        assert swapped.status is ProvenanceStatus.ALTERED

    def test_the_compiler_is_never_reached_by_a_film_that_cannot_cite(self, archive):
        """Refuse early, where the failure is still a sentence a person can read."""

        class Unreachable:
            def compile(self, spec):
                raise AssertionError("a film that cannot cite must never reach the compiler")

        forged = self._forged(archive, Citation(CitationKind.SPARK, "spk-nope"))

        refused = self._pipeline(archive, forged, Unreachable()).execute(
            ComposeFilmCommand(family_id=FAMILY, actor_id=PAPA)
        )

        assert refused.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE

    def test_a_package_cannot_be_assembled_around_a_failed_ledger(self, archive):
        """Not merely "the use case checks". The type refuses."""
        package = archive.compile().unwrap()
        first = package.provenance.entries[0]
        broken = Provenance(
            film_id=package.provenance.film_id,
            family_id=package.provenance.family_id,
            verified_at=package.provenance.verified_at,
            entries=(
                ProvenanceEntry(
                    scene_id=first.scene_id,
                    scene_kind=first.scene_kind,
                    citation=first.citation,
                    status=ProvenanceStatus.MISSING,
                    detail="not in this family's archive",
                ),
                *package.provenance.entries[1:],
            ),
        )

        with pytest.raises(ValueError, match="which is missing"):
            FilmPackage(draft=package.draft, film=package.film, provenance=broken)

    def test_a_ledger_that_skipped_a_scene_is_not_a_ledger(self, archive):
        """The cheap way to make this file pass would be to check less. It is not available."""
        package = archive.compile().unwrap()
        thinner = Provenance(
            film_id=package.provenance.film_id,
            family_id=package.provenance.family_id,
            verified_at=package.provenance.verified_at,
            entries=package.provenance.entries[1:],
        )

        with pytest.raises(ValueError, match="nobody checked"):
            FilmPackage(draft=package.draft, film=package.film, provenance=thinner)

    def test_a_ledger_cannot_vouch_for_something_the_film_does_not_cite(self, archive):
        package = archive.compile().unwrap()
        padded = Provenance(
            film_id=package.provenance.film_id,
            family_id=package.provenance.family_id,
            verified_at=package.provenance.verified_at,
            entries=(
                *package.provenance.entries,
                ProvenanceEntry(
                    scene_id="moment-mom-1",
                    scene_kind=SceneKind.MOMENT,
                    citation=Citation(CitationKind.SPARK, "spk-99"),
                    status=ProvenanceStatus.VERIFIED,
                ),
            ),
        )

        with pytest.raises(ValueError, match="does not cite"):
            FilmPackage(draft=package.draft, film=package.film, provenance=padded)

    def test_provenance_is_a_required_field_and_stays_one(self):
        """A default here would let a film ship unverified without one line changing shape.

        This assertion exists to be annoying to whoever tries. That is its whole purpose.
        """
        provenance = next(f for f in fields(FilmPackage) if f.name == "provenance")
        assert provenance.default is MISSING
        assert provenance.default_factory is MISSING


class TestTheLedgerTravelsWithTheFilm:
    """PRD 47 - the promise is checkable by the family, not only by us."""

    def test_provenance_json_is_written_beside_the_film(self, archive, tmp_path: Path):
        package = archive.compile().unwrap()

        exporter = FilesystemFilmExporter(archive.media)
        export = exporter.export(package, into=tmp_path / "out").unwrap()

        assert export.provenance_path.name == PROVENANCE_FILENAME
        assert export.provenance_path.parent == export.film_path.parent
        assert export.film_path.name == FILM_FILENAME

    def test_the_shipped_ledger_names_every_source_by_id(self, archive, tmp_path: Path):
        """What a person needs in fifteen years is the identifier, not our reassurance."""
        package = archive.compile().unwrap()
        FilesystemFilmExporter(archive.media).export(package, into=tmp_path / "out")

        ledger = json.loads((tmp_path / "out" / PROVENANCE_FILENAME).read_text())

        assert ledger["unverified_count"] == 0
        shipped = {(e["cites"]["kind"], e["cites"]["id"]) for e in ledger["entries"]}
        assert shipped == {
            (citation.kind.value, citation.id)
            for scene in package.spec.scenes
            for citation in scene.cites
        }
        assert {"SPARK", "MOMENT", "MEDIA", "VOICE_NOTE"} >= {kind for kind, _ in shipped}

    def test_the_media_that_travels_is_exactly_the_media_the_ledger_vouches_for(
        self, archive, tmp_path: Path
    ):
        package = archive.compile().unwrap()

        exporter = FilesystemFilmExporter(archive.media)
        export = exporter.export(package, into=tmp_path / "out").unwrap()

        travelled = {path.stem for path in export.media_paths}
        vouched = {
            entry.citation.id
            for entry in package.provenance.entries
            if entry.citation.kind is CitationKind.MEDIA
        }
        assert travelled >= vouched
        assert travelled == package.bundle.ids


class TestTheRendererStillChecksTheReceipts:
    """An export may travel between verification and pixels; trust does not travel with it."""

    def test_a_ledger_altered_after_export_never_reaches_chromium(self, archive, tmp_path: Path):
        package = archive.compile().unwrap()
        exported = (
            FilesystemFilmExporter(archive.media).export(package, into=tmp_path / "out").unwrap()
        )
        ledger = json.loads(exported.provenance_path.read_text())
        ledger["entries"][0]["status"] = "MISSING"
        ledger["unverified_count"] = 1
        exported.provenance_path.write_text(json.dumps(ledger))

        result = ChromiumFfmpegRenderer(workspace=tmp_path / "work").render(
            exported.directory, destination=tmp_path / "film.mp4"
        )

        assert result.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE
        assert not (tmp_path / "work").exists(), "a failed receipt must be cheap to refuse"

    def test_media_altered_after_export_never_becomes_a_frame(self, archive, tmp_path: Path):
        package = archive.compile().unwrap()
        exported = (
            FilesystemFilmExporter(archive.media).export(package, into=tmp_path / "out").unwrap()
        )
        exported.media_paths[0].write_bytes(b"not the photograph the ledger vouched for")

        result = ChromiumFfmpegRenderer(workspace=tmp_path / "work").render(
            exported.directory, destination=tmp_path / "film.mp4"
        )

        assert result.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE
        assert not (tmp_path / "film.mp4").exists()
