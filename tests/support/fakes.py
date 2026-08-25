"""In-memory adapters used by unit tests.

They implement the same ports as the real ones, so a use case never knows the difference.
Integration tests run the same scenarios against SQLite.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import TracebackType

from anuvritti.domain.events import DomainEvent
from anuvritti.domain.family import ChildProfile, Family, Member
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
            content_hash="fake",
            storage_key=str(media_id),
            encrypted=True,
            created_at=at,
        )
        self._bytes[str(media_id)] = content
        self._meta[str(media_id)] = meta
        return Ok(meta)

    def get(self, media_id: MediaId) -> Result[bytes, DomainError]:
        found = self._bytes.get(str(media_id))
        if found is None:
            return Err(DomainError(ErrorCode.MEDIA_NOT_FOUND, str(media_id)))
        return Ok(found)

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
