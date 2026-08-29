"""In-memory adapters used by unit tests.

They implement the same ports as the real ones, so a use case never knows the difference.
Integration tests run the same scenarios against SQLite.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from anuvritti.application.ports import RenderedFilm, RenderedFrame
from anuvritti.domain.events import DomainEvent
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.inbox import FutureMessage, PresentedArtifact, SealLedger
from anuvritti.domain.lexicon import FamilyLexicon
from anuvritti.domain.media import MediaKind, MediaObject
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import Confidence, IntentType, MemberRole, SparkStatus
from anuvritti.domain.voice import Transcript, VoiceNote
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    FutureMessageId,
    MediaId,
    MemberId,
    MomentId,
    SparkId,
)
from anuvritti.shared.result import Err, Ok, Result

PAPA = MemberId("mem-papa")
CHILD = ChildId("ch-1")
FAMILY = FamilyId("fam-1")


def build_family(dob: datetime | None = None) -> Family:
    born = (dob or datetime(2021, 6, 1, tzinfo=UTC)).date()
    return Family(
        id=FAMILY,
        name="Our family",
        members=(Member(PAPA, "Papa", MemberRole.PARENT),),
        children=(ChildProfile(CHILD, MemberId("mem-son"), "Aarav", born),),
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


class InMemoryFutureInboxStore:
    """A fake with the real port's indivisible save shape."""

    def __init__(self) -> None:
        self._messages: dict[str, FutureMessage] = {}
        self._artifacts: dict[str, PresentedArtifact] = {}

    def save(
        self, message: FutureMessage, artifact: PresentedArtifact
    ) -> Result[FutureMessage, DomainError]:
        key = str(message.id)
        if key in self._messages:
            return Err(DomainError(ErrorCode.CONFLICT, "a Future Inbox seal is immutable"))
        verified = message.ledger.entry.verify(artifact)
        if isinstance(verified, Err):
            return verified
        self._messages[key] = message
        self._artifacts[key] = artifact
        return Ok(message)

    def get(self, message_id: FutureMessageId) -> Result[FutureMessage, DomainError]:
        found = self._messages.get(str(message_id))
        return Ok(found) if found else self._missing(message_id)

    def get_artifact(self, message_id: FutureMessageId) -> Result[PresentedArtifact, DomainError]:
        found = self._artifacts.get(str(message_id))
        return Ok(found) if found else self._missing(message_id)

    def ledger(self, message_id: FutureMessageId) -> Result[SealLedger, DomainError]:
        found = self.get(message_id)
        if isinstance(found, Err):
            return found
        return Ok(found.value.ledger)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[FutureMessage], DomainError]:
        return Ok(
            [message for message in self._messages.values() if message.family_id == family_id]
        )

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        doomed = [key for key, message in self._messages.items() if message.family_id == family_id]
        for key in doomed:
            del self._messages[key]
            del self._artifacts[key]
        return Ok(len(doomed))

    @staticmethod
    def _missing(message_id: FutureMessageId) -> Err[DomainError]:
        return Err(
            DomainError(
                ErrorCode.MEDIA_NOT_FOUND,
                "the Future Inbox seal does not exist",
                {"message_id": str(message_id)},
            )
        )


class InMemoryFamilyRepository:
    def __init__(self, *families: Family) -> None:
        self._families: dict[str, Family] = {str(f.id): f for f in families}

    def get(self, family_id: FamilyId) -> Result[Family, DomainError]:
        found = self._families.get(str(family_id))
        if found is None:
            return Err(DomainError(ErrorCode.FAMILY_NOT_FOUND, f"no family {family_id}"))
        return Ok(found)

    def save(self, family: Family) -> Result[Family, DomainError]:
        self._families[str(family.id)] = family
        return Ok(family)

    def delete(self, family_id: FamilyId) -> Result[int, DomainError]:
        return Ok(1 if self._families.pop(str(family_id), None) else 0)


class InMemorySparkRepository:
    def __init__(self, *sparks: Spark) -> None:
        self._sparks: dict[str, Spark] = {str(s.id): s for s in sparks}

    def get(self, spark_id: SparkId) -> Result[Spark, DomainError]:
        found = self._sparks.get(str(spark_id))
        if found is None:
            return Err(DomainError(ErrorCode.SPARK_NOT_FOUND, f"no spark {spark_id}"))
        return Ok(found)

    def save(self, spark: Spark) -> Result[Spark, DomainError]:
        self._sparks[str(spark.id)] = spark.with_events_cleared()
        return Ok(spark)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Spark], DomainError]:
        return Ok([s for s in self._sparks.values() if s.family_id == family_id])

    def search(
        self,
        family_id: FamilyId,
        *,
        text: str | None = None,
        intent: IntentType | None = None,
        child_id: ChildId | None = None,
        age_years: int | None = None,
        status: SparkStatus | None = None,
        limit: int = 25,
    ) -> Result[Sequence[Spark], DomainError]:
        found = [s for s in self._sparks.values() if s.family_id == family_id]
        if text:
            needle = text.lower()
            found = [
                s
                for s in found
                if needle in s.title.lower()
                or needle in (s.note or "").lower()
                or any(needle in tag for tag in s.tags)
                or needle in s.category.value.lower()
            ]
        if intent:
            found = [s for s in found if s.intent.value is intent]
        if child_id:
            found = [s for s in found if s.subject_child_id == child_id]
        if age_years is not None:
            found = [s for s in found if s.is_age_appropriate_for(age_years)]
        if status:
            found = [s for s in found if s.status is status]
        found.sort(key=lambda s: s.created_at, reverse=True)
        return Ok(found[:limit])

    def list_returnable(self, family_id: FamilyId) -> Result[Sequence[Spark], DomainError]:
        return Ok(
            [
                s
                for s in self._sparks.values()
                if s.family_id == family_id and s.status.is_returnable
            ]
        )

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        doomed = [k for k, s in self._sparks.items() if s.family_id == family_id]
        for key in doomed:
            del self._sparks[key]
        return Ok(len(doomed))


class InMemoryMomentRepository:
    def __init__(self) -> None:
        self._moments: dict[str, Moment] = {}

    def get(self, moment_id: MomentId) -> Result[Moment, DomainError]:
        found = self._moments.get(str(moment_id))
        if found is None:
            return Err(DomainError(ErrorCode.MOMENT_NOT_FOUND, f"no moment {moment_id}"))
        return Ok(found)

    def save(self, moment: Moment) -> Result[Moment, DomainError]:
        self._moments[str(moment.id)] = moment.with_events_cleared()
        return Ok(moment)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Moment], DomainError]:
        return Ok([m for m in self._moments.values() if m.family_id == family_id])

    def find_by_spark(self, spark_id: SparkId) -> Result[Moment | None, DomainError]:
        for moment in self._moments.values():
            if moment.spark_id == spark_id:
                return Ok(moment)
        return Ok(None)

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        doomed = [k for k, m in self._moments.items() if m.family_id == family_id]
        for key in doomed:
            del self._moments[key]
        return Ok(len(doomed))


class InMemoryLittleThingRepository:
    def __init__(self) -> None:
        self._items: dict[str, LittleThing] = {}

    def save(self, little_thing: LittleThing) -> Result[LittleThing, DomainError]:
        self._items[str(little_thing.id)] = little_thing.with_events_cleared()
        return Ok(little_thing)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[LittleThing], DomainError]:
        return Ok([i for i in self._items.values() if i.family_id == family_id])

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        doomed = [k for k, i in self._items.items() if i.family_id == family_id]
        for key in doomed:
            del self._items[key]
        return Ok(len(doomed))


class InMemoryRightNowRepository:
    def __init__(self) -> None:
        self._items: dict[str, RightNowSnapshot] = {}

    def save(self, snapshot: RightNowSnapshot) -> Result[RightNowSnapshot, DomainError]:
        self._items[str(snapshot.id)] = snapshot.with_events_cleared()
        return Ok(snapshot)

    def list_for_family(
        self, family_id: FamilyId
    ) -> Result[Sequence[RightNowSnapshot], DomainError]:
        return Ok([i for i in self._items.values() if i.family_id == family_id])

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        doomed = [k for k, i in self._items.items() if i.family_id == family_id]
        for key in doomed:
            del self._items[key]
        return Ok(len(doomed))


class InMemoryMediaStore:
    def __init__(self) -> None:
        self._bytes: dict[str, bytes] = {}
        self._meta: dict[str, MediaObject] = {}
        self._n = 0

    def put(
        self, family_id: FamilyId, *, content: bytes, mime_type: str, at: datetime
    ) -> Result[MediaObject, DomainError]:
        kind = MediaKind.for_mime_type(mime_type)
        if kind is None:
            return Err(DomainError(ErrorCode.MEDIA_KIND_UNSUPPORTED, mime_type))
        self._n += 1
        media_id = MediaId(f"med-{self._n:04d}")
        meta = MediaObject(
            id=media_id,
            family_id=family_id,
            kind=kind,
            mime_type=mime_type,
            byte_size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
            storage_key=str(media_id),
            encrypted=True,
            created_at=at,
        )
        self._bytes[str(media_id)] = content
        self._meta[str(media_id)] = meta
        return Ok(meta)

    def get(self, media_id: MediaId) -> Result[bytes, DomainError]:
        """Re-hashes on read, exactly as the encrypted store does.

        A fake that cannot fail its own integrity check is a fake that quietly passes tests
        about integrity, which is the only kind of test that matters here.
        """
        found = self._bytes.get(str(media_id))
        if found is None:
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, str(media_id)))
        if hashlib.sha256(found).hexdigest() != self._meta[str(media_id)].content_hash:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    f"media {media_id} failed its integrity check",
                    {"media_id": str(media_id)},
                )
            )
        return Ok(found)

    def tamper(self, media_id: str, content: bytes) -> None:
        """Replace the bytes without telling the catalogue. Only a test would ever do this."""
        self._bytes[media_id] = content

    def lose_bytes(self, media_id: str) -> None:
        """Keep the row, drop the file - what a half-finished restore actually looks like."""
        self._bytes.pop(media_id, None)

    def describe(self, media_id: MediaId) -> Result[MediaObject, DomainError]:
        found = self._meta.get(str(media_id))
        if found is None:
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, str(media_id)))
        return Ok(found)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[MediaObject], DomainError]:
        return Ok([m for m in self._meta.values() if m.family_id == family_id])

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        doomed = [k for k, m in self._meta.items() if m.family_id == family_id]
        for key in doomed:
            del self._meta[key]
            self._bytes.pop(key, None)
        return Ok(len(doomed))


class RecordingEventPublisher:
    """Captures everything published so tests can assert the audit trail."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []
        self._by_family: dict[str, list[DomainEvent]] = {}

    def publish(self, events: Sequence[DomainEvent], *, family_id: FamilyId) -> None:
        self.events.extend(events)
        self._by_family.setdefault(str(family_id), []).extend(events)

    def list_for_family(self, family_id: FamilyId) -> Sequence[DomainEvent]:
        return list(self._by_family.get(str(family_id), []))

    def delete_for_family(self, family_id: FamilyId) -> int:
        removed = self._by_family.pop(str(family_id), [])
        return len(removed)

    def names(self) -> list[str]:
        return [type(e).__name__ for e in self.events]


class NullUnitOfWork:
    def __enter__(self) -> NullUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class NullTranscriber:
    """Keeps the voice and transcribes nothing (PRD 44, local-first).

    The shipping default, not a stub - see `adapters/transcription/local.py`.
    """

    def transcribe(self, media_id: MediaId) -> Result[Transcript | None, DomainError]:
        return Ok(None)


class FakeFilmRenderer:
    """Records the portable folder handed across the render port and draws no pixel."""

    def __init__(self, result: RenderedFilm | None = None) -> None:
        self.calls: list[tuple[Path, Path]] = []
        self.result = result or RenderedFilm(
            path=Path("film.mp4"),
            manifest_path=Path("film.manifest.json"),
            frames=(RenderedFrame("opening", Path("opening.png"), Path("opening.html")),),
            duration_seconds=3.0,
        )

    def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
        self.calls.append((archive, destination))
        return Ok(self.result)


class FakeAudioDurationMeasurer:
    """Returns a measurement independent of anything the handset claimed."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.seen: list[tuple[bytes, str]] = []

    def measure(self, content: bytes, *, mime_type: str) -> Result[float, DomainError]:
        self.seen.append((content, mime_type))
        return Ok(self.seconds)


class DeafTranscriber:
    """A transcriber that always fails. Nothing it does may cost a family a recording."""

    def transcribe(self, media_id: MediaId) -> Result[Transcript | None, DomainError]:
        return Err(DomainError(ErrorCode.VALIDATION_FAILED, "the model fell over"))


class StubTranscriber:
    """Hears whatever the test put in its mouth, with honest machine provenance."""

    def __init__(self, text: str, *, confidence: float = 0.7, engine: str = "stub") -> None:
        self._text = text
        self._confidence = confidence
        self._engine = engine
        self.calls: list[str] = []

    def transcribe(self, media_id: MediaId) -> Result[Transcript | None, DomainError]:
        self.calls.append(str(media_id))
        return Transcript.machine(
            self._text,
            confidence=Confidence(self._confidence),
            engine=self._engine,
            at=datetime(2026, 1, 13, 21, 40, tzinfo=UTC),
        )


class InMemoryVoiceNoteRepository:
    def __init__(self) -> None:
        self._items: dict[str, VoiceNote] = {}

    def get(self, media_id: MediaId) -> Result[VoiceNote, DomainError]:
        found = self._items.get(str(media_id))
        if found is None:
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, "no recording with that id"))
        return Ok(found)

    def save(self, note: VoiceNote) -> Result[VoiceNote, DomainError]:
        self._items[str(note.media_id)] = note.with_events_cleared()
        return Ok(note)

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[VoiceNote], DomainError]:
        kept = [n for n in self._items.values() if n.family_id == family_id]
        return Ok(sorted(kept, key=lambda n: n.recorded_at, reverse=True))

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        doomed = [k for k, n in self._items.items() if n.family_id == family_id]
        for key in doomed:
            del self._items[key]
        return Ok(len(doomed))


class InMemoryLexiconRepository:
    """One dictionary per family, and no way to read across them.

    The real one is a table whose primary key starts with `family_id`. This one is keyed
    by family for the same reason: a fake that let a test read every family's words at once
    would make the guarantee untestable in exactly the tests that most want to check it.
    """

    def __init__(self) -> None:
        self._by_family: dict[str, FamilyLexicon] = {}

    def load(self, family_id: FamilyId) -> Result[FamilyLexicon, DomainError]:
        return Ok(self._by_family.get(str(family_id)) or FamilyLexicon.empty(family_id))

    def save(self, lexicon: FamilyLexicon) -> Result[FamilyLexicon, DomainError]:
        self._by_family[str(lexicon.family_id)] = lexicon
        return Ok(lexicon)

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]:
        removed = self._by_family.pop(str(family_id), None)
        return Ok(len(removed) if removed else 0)


#: How many bytes of this fake's audio format make up a second. The number is arbitrary; what
#: matters is that the length comes out of the *file*, which is what a real prober does.
SPOKEN_BYTES_PER_SECOND = 4000


class FakeNarrator:
    """A synthesiser that produces a file and then measures the file it produced.

    The honesty of this fake is the whole point of it. It would be much simpler to hand back a
    duration taken from a lookup table keyed on the line - and a test suite built on that fake
    would pass happily on the day somebody starts estimating lengths from word counts, because
    the fake would be estimating too. So this one writes real bytes into the media store and
    derives the length from `len(audio)`. Nothing anywhere in it looks at the words.

    `failing` is the other half: a synthesiser is a thing that is sometimes not there, and what
    the product does then is a product decision that deserves a test.
    """

    def __init__(
        self,
        media: InMemoryMediaStore,
        *,
        at: datetime | None = None,
        failing: frozenset[str] = frozenset(),
    ) -> None:
        self._media = media
        self._at = at or datetime(2026, 1, 1, tzinfo=UTC)
        self._failing = failing
        self.spoken: list[str] = []

    def speak(self, line: object, *, family_id: FamilyId) -> Result[object, DomainError]:
        from anuvritti.application.ports import SynthesisedSpeech

        name = getattr(line, "value", str(line))
        if name in self._failing:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the synthesiser is not available",
                    {"line": name},
                )
            )
        audio = b"\x00\x00\x00\x20ftypM4A " + (f"<{name}>".encode() * 900)
        stored = self._media.put(family_id, content=audio, mime_type="audio/mp4", at=self._at)
        if stored.is_err():
            return Err(stored.unwrap_err())
        self.spoken.append(name)
        return Ok(
            SynthesisedSpeech(
                media_id=stored.unwrap().id,
                seconds=len(audio) / SPOKEN_BYTES_PER_SECOND,
            )
        )
