"""The verifier's edges: every way a citation fails to resolve, and the one that is not a failure.

`tests/constitution/test_film_provenance.py` states the rule. This file walks the paths that
rule depends on, including the several that only ever run on a bad day - a half-finished
restore, a store that will not answer, a bundle that disagrees with the catalogue it came
from. Each of those has to produce a *different* outcome, and getting them confused is how a
ledger ends up asserting something that was never checked.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.application.provenance import NOT_IN_ARCHIVE, VerifyProvenanceUseCase
from anuvritti.domain.film import (
    BundledMedia,
    Citation,
    CitationKind,
    FilmDraft,
    FilmScene,
    FilmSpec,
    MediaBundle,
    ProvenanceStatus,
    SceneKind,
    SceneVoice,
)
from anuvritti.domain.media import MediaKind
from anuvritti.domain.presence import LittleThing
from anuvritti.domain.voice import VoiceNote
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, LittleThingId, MediaId
from anuvritti.shared.result import Err, Ok
from tests.support.fakes import (
    FAMILY,
    PAPA,
    InMemoryLittleThingRepository,
    InMemoryMediaStore,
    InMemoryMomentRepository,
    InMemorySparkRepository,
    InMemoryVoiceNoteRepository,
)

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
OTHER = FamilyId("fam-2")
PICTURE = b"\xff\xd8\xff\xe0" + b"a hand around a finger" * 12


class Bench:
    """One scene, whatever it happens to cite, and the stores it will be checked against."""

    def __init__(self) -> None:
        self.sparks = InMemorySparkRepository()
        self.moments = InMemoryMomentRepository()
        self.voice_notes = InMemoryVoiceNoteRepository()
        self.little_things = InMemoryLittleThingRepository()
        self.media = InMemoryMediaStore()

    def verifier(self, **overrides) -> VerifyProvenanceUseCase:
        parts = {
            "sparks": self.sparks,
            "moments": self.moments,
            "voice_notes": self.voice_notes,
            "little_things": self.little_things,
            "media": self.media,
            "clock": FrozenClock(NOW),
        }
        parts.update(overrides)
        return VerifyProvenanceUseCase(**parts)

    def draft(self, *cites: Citation, bundle: MediaBundle | None = None) -> FilmDraft:
        scene = FilmScene(
            id="scene-1",
            kind=SceneKind.MOMENT,
            heading="the afternoon in question",
            voice=SceneVoice.silent(4.5),
            cites=cites,
        )
        spec = FilmSpec(id="film-1", family_id=FAMILY, title="A year", scenes=(scene,))
        return FilmDraft(spec=spec, bundle=bundle or MediaBundle())

    def verdict(self, *cites: Citation, bundle: MediaBundle | None = None, **overrides):
        ledger = self.verifier(**overrides).execute(self.draft(*cites, bundle=bundle))
        return ledger.unwrap().entries[0] if ledger.is_ok() else ledger

    # ------------------------------------------------------------------ writing
    def picture(self, family_id: FamilyId = FAMILY) -> str:
        stored = self.media.put(family_id, content=PICTURE, mime_type="image/jpeg", at=NOW)
        return str(stored.unwrap().id)

    def little_thing(self, family_id: FamilyId = FAMILY) -> str:
        thing = LittleThing.capture(
            little_thing_id=LittleThingId("lit-1"),
            family_id=family_id,
            author_id=PAPA,
            at=NOW,
            text="said 'again' forty times",
        ).unwrap()
        self.little_things.save(thing)
        return str(thing.id)


@pytest.fixture
def bench() -> Bench:
    return Bench()


class TestSmallThingsAreCitedLikeEverythingElse:
    """`LittleThing` has no `get`, so this is the one citation checked by membership."""

    def test_one_of_the_familys_own_little_things_verifies(self, bench):
        cited = bench.little_thing()
        entry = bench.verdict(Citation(CitationKind.LITTLE_THING, cited))
        assert entry.status is ProvenanceStatus.VERIFIED

    def test_a_little_thing_nobody_wrote_does_not(self, bench):
        entry = bench.verdict(Citation(CitationKind.LITTLE_THING, "lit-never"))
        assert (entry.status, entry.detail) == (ProvenanceStatus.MISSING, NOT_IN_ARCHIVE)

    def test_another_familys_little_thing_is_indistinguishable_from_one_that_never_existed(
        self, bench
    ):
        cited = bench.little_thing(OTHER)
        entry = bench.verdict(Citation(CitationKind.LITTLE_THING, cited))
        assert (entry.status, entry.detail) == (ProvenanceStatus.MISSING, NOT_IN_ARCHIVE)

    def test_a_list_that_cannot_be_read_stops_the_ledger_rather_than_filling_it_in(self, bench):
        broken = _refusing(ErrorCode.CONFLICT, "the archive could not be read")
        result = bench.verdict(Citation(CitationKind.LITTLE_THING, "lit-1"), little_things=broken)
        assert result.unwrap_err().code is ErrorCode.CONFLICT


class TestARecordingIsCheckedAsBothARowAndAFile:
    def test_another_familys_recording_is_refused_without_confirming_it_exists(self, bench):
        media_id = bench.picture(OTHER)
        bench.voice_notes.save(
            VoiceNote.kept(
                media_id=MediaId(media_id),
                family_id=OTHER,
                author_id=PAPA,
                duration_seconds=3.0,
                at=NOW,
            ).unwrap()
        )
        entry = bench.verdict(Citation(CitationKind.VOICE_NOTE, media_id))
        assert (entry.status, entry.detail) == (ProvenanceStatus.MISSING, NOT_IN_ARCHIVE)

    def test_a_recording_nobody_kept_a_row_for_is_missing(self, bench):
        """A well-formed id pointing at nothing. The ordinary case, not the exotic one."""
        entry = bench.verdict(Citation(CitationKind.VOICE_NOTE, "med-nobody-kept"))
        assert (entry.status, entry.detail) == (ProvenanceStatus.MISSING, NOT_IN_ARCHIVE)

    def test_a_failed_entry_carries_its_reason_into_the_ledger(self, bench):
        """A ledger that says only MISSING sends someone reading it back to the source code."""
        entry = bench.verdict(Citation(CitationKind.VOICE_NOTE, "med-nobody-kept"))
        assert entry.to_dict()["detail"] == NOT_IN_ARCHIVE
        assert entry.to_dict()["cites"] == {"kind": "VOICE_NOTE", "id": "med-nobody-kept"}


class TestWhatTheBytesSay:
    def test_a_file_belonging_to_another_family_is_not_in_this_archive(self, bench):
        theirs = bench.picture(OTHER)
        entry = bench.verdict(
            Citation(CitationKind.MEDIA, theirs),
            bundle=_bundle(theirs, "0" * 64),
        )
        assert (entry.status, entry.detail) == (ProvenanceStatus.MISSING, NOT_IN_ARCHIVE)

    def test_a_bundle_that_disagrees_with_the_catalogue_is_altered_not_missing(self, bench):
        """Two records of the same file disagreeing. Neither gets the benefit of the doubt."""
        media_id = bench.picture()
        entry = bench.verdict(
            Citation(CitationKind.MEDIA, media_id),
            bundle=_bundle(media_id, "b" * 64),
        )
        assert entry.status is ProvenanceStatus.ALTERED
        assert "measured against" in entry.detail

    def test_a_row_whose_file_is_gone_says_so_in_those_words(self, bench):
        """A half-restored archive. The catalogue survived; the photographs did not."""
        media_id = bench.picture()
        bench.media.lose_bytes(media_id)
        entry = bench.verdict(
            Citation(CitationKind.MEDIA, media_id),
            bundle=_bundle(media_id, bench.media.describe(MediaId(media_id)).unwrap().content_hash),
        )
        assert entry.status is ProvenanceStatus.MISSING
        assert entry.detail == "the row is here, the bytes are not"

    def test_a_store_that_will_not_answer_is_never_written_down_as_a_verdict(self, bench):
        """Neither "missing" nor "altered". The question was not answered, so no film today."""
        media_id = bench.picture()
        real = bench.media.describe(MediaId(media_id)).unwrap()

        class Sulking:
            def describe(self, mid):
                return Ok(real)

            def get(self, mid):
                return Err(DomainError(ErrorCode.PERMISSION_DENIED, "the key is not here"))

        result = bench.verdict(
            Citation(CitationKind.MEDIA, media_id),
            bundle=_bundle(media_id, real.content_hash),
            media=Sulking(),
        )
        assert result.unwrap_err().code is ErrorCode.PERMISSION_DENIED

    def test_a_catalogue_that_will_not_answer_is_not_an_empty_catalogue(self, bench):
        class Silent:
            def describe(self, mid):
                return Err(DomainError(ErrorCode.CONFLICT, "the catalogue is locked"))

        result = bench.verdict(
            Citation(CitationKind.MEDIA, "med-0001"),
            bundle=_bundle("med-0001", "c" * 64),
            media=Silent(),
        )
        assert result.unwrap_err().code is ErrorCode.CONFLICT


def _bundle(media_id: str, content_hash: str) -> MediaBundle:
    return MediaBundle(
        (
            BundledMedia(
                id=MediaId(media_id),
                kind=MediaKind.IMAGE,
                mime_type="image/jpeg",
                byte_size=len(PICTURE),
                content_hash=content_hash,
            ),
        )
    )


def _refusing(code: ErrorCode, message: str) -> object:
    class Refusing:
        def list_for_family(self, family_id):
            return Err(DomainError(code, message))

    return Refusing()
