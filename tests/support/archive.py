"""A year of a real family, written the way the product writes it.

Constitution tests need a whole archive rather than a fixture object: a Spark, the Moment it
became, a photograph with real bytes behind it, a recording with a measured length, and the
use cases wired the way the composition root wires them. Every test that asks a question about
a *film* needs all of that before it can ask anything at all.

It lives here rather than in one test file because two different constitutions now depend on
it - one about what a film may claim, one about whose voice says it - and a second copy of
this harness would be a second definition of what a family's year looks like. When they drift,
the tests keep passing and stop meaning the same thing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmCommand,
    ComposeFilmUseCase,
)
from anuvritti.application.ports import Narrator
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.domain.film import FilmDraft, FilmPackage
from anuvritti.domain.moment import Moment
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceRef
from anuvritti.domain.voice import VoiceNote
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import (
    MediaId,
    MomentId,
    SequentialIdGenerator,
    SparkId,
)
from anuvritti.shared.result import Result
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
PHOTO = b"\xff\xd8\xff\xe0" + b"the morning he let go of the fence" * 20
CLIP = b"\x00\x00\x00\x20ftypM4A " + b"you did it, you did it" * 40


class Archive:
    """A family's own box, with the reading side wired exactly as production wires it."""

    def __init__(self, *, narrator: Narrator | None = None) -> None:
        self.families = InMemoryFamilyRepository(build_family())
        self.sparks = InMemorySparkRepository()
        self.moments = InMemoryMomentRepository()
        self.voice_notes = InMemoryVoiceNoteRepository()
        self.little_things = InMemoryLittleThingRepository()
        self.media = InMemoryMediaStore()
        self.narrator = narrator
        self._n = 0

    # ------------------------------------------------------------------ writing
    def moment(
        self,
        title: str,
        *,
        on: date,
        photo: str | None = None,
        audio: str | None = None,
    ) -> Moment:
        self._n += 1
        at = datetime.combine(on, datetime.min.time(), tzinfo=UTC)
        spark = self.sparks.save(
            Spark.capture(
                spark_id=SparkId(f"spk-{self._n}"),
                family_id=FAMILY,
                owner_id=PAPA,
                source=SourceRef.from_text(title),
                at=at,
                subject_child_id=CHILD,
            )
        ).unwrap()
        return self.moments.save(
            Moment.create(
                moment_id=MomentId(f"mom-{self._n}"),
                family_id=FAMILY,
                spark_id=spark.id,
                created_by=PAPA,
                spark_captured_at=at,
                at=at,
                happened_on=on,
                photo_media_id=photo,
                audio_media_id=audio,
            ).unwrap()
        ).unwrap()

    def upload(self, content: bytes = PHOTO, mime: str = "image/jpeg") -> str:
        stored = self.media.put(FAMILY, content=content, mime_type=mime, at=NOW)
        return str(stored.unwrap().id)

    def recording(self, seconds: float = 6.2) -> str:
        media_id = self.upload(CLIP, "audio/mp4")
        self.voice_notes.save(
            VoiceNote.kept(
                media_id=MediaId(media_id),
                family_id=FAMILY,
                author_id=PAPA,
                duration_seconds=seconds,
                at=NOW,
            ).unwrap()
        )
        return media_id

    # ------------------------------------------------------------------ reading
    def composer(self) -> ComposeFilmUseCase:
        return ComposeFilmUseCase(
            families=self.families,
            sparks=self.sparks,
            moments=self.moments,
            voice_notes=self.voice_notes,
            media=self.media,
            ids=SequentialIdGenerator("film"),
            narrator=self.narrator,
        )

    def verifier(self) -> VerifyProvenanceUseCase:
        return VerifyProvenanceUseCase(
            sparks=self.sparks,
            moments=self.moments,
            voice_notes=self.voice_notes,
            little_things=self.little_things,
            media=self.media,
            clock=FrozenClock(NOW),
        )

    def draft(self) -> Result[FilmDraft, DomainError]:
        return self.composer().execute(ComposeFilmCommand(family_id=FAMILY, actor_id=PAPA))

    def compile(self) -> Result[FilmPackage, DomainError]:
        use_case = CompileFilmUseCase(
            compose=self.composer(),
            verify=self.verifier(),
            compiler=FilmkitFilmCompiler(),
        )
        return use_case.execute(ComposeFilmCommand(family_id=FAMILY, actor_id=PAPA))


def a_year(*, narrator: Narrator | None = None) -> Archive:
    """The year both constitutions are written against: one photograph, one recording."""
    box = Archive(narrator=narrator)
    box.moment("first time down the slide alone", on=date(2026, 3, 4), photo=box.upload())
    box.moment("counting to twenty in the bath", on=date(2026, 5, 19), audio=box.recording())
    return box
