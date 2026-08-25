"""Application ports.

The application says what it needs; adapters supply it. Nothing in this module knows that
SQLite, a filesystem or an HTTP framework exists - which is what makes the local-first
promise in PRD 44 an implementation detail rather than a rewrite.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Protocol, runtime_checkable

from anuvritti.domain.access import Device, PairingRequest
from anuvritti.domain.events import DomainEvent
from anuvritti.domain.family import Family
from anuvritti.domain.media import MediaObject
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.domain.spark import Inference, Spark
from anuvritti.domain.values import IntentType, SourceRef, SparkStatus
from anuvritti.domain.voice import Transcript, VoiceNote
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import (
    ChildId,
    DeviceId,
    FamilyId,
    MediaId,
    MomentId,
    SparkId,
)
from anuvritti.shared.result import Result


@runtime_checkable
class FamilyRepository(Protocol):
    def get(self, family_id: FamilyId) -> Result[Family, DomainError]: ...

    def count(self) -> int: ...

    def save(self, family: Family) -> Result[Family, DomainError]: ...

    def delete(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class SparkRepository(Protocol):
    def get(self, spark_id: SparkId) -> Result[Spark, DomainError]: ...

    def save(self, spark: Spark) -> Result[Spark, DomainError]: ...

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Spark], DomainError]: ...

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
    ) -> Result[Sequence[Spark], DomainError]: ...

    def list_returnable(self, family_id: FamilyId) -> Result[Sequence[Spark], DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class MomentRepository(Protocol):
    def get(self, moment_id: MomentId) -> Result[Moment, DomainError]: ...

    def save(self, moment: Moment) -> Result[Moment, DomainError]: ...

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Moment], DomainError]: ...

    def find_by_spark(self, spark_id: SparkId) -> Result[Moment | None, DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class LittleThingRepository(Protocol):
    def save(self, little_thing: LittleThing) -> Result[LittleThing, DomainError]: ...

    def list_for_family(
        self, family_id: FamilyId
    ) -> Result[Sequence[LittleThing], DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class RightNowRepository(Protocol):
    def save(self, snapshot: RightNowSnapshot) -> Result[RightNowSnapshot, DomainError]: ...

    def list_for_family(
        self, family_id: FamilyId
    ) -> Result[Sequence[RightNowSnapshot], DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class MediaStore(Protocol):
    """Bytes in, metadata out. PRD 44 requires encryption at rest inside the adapter."""

    def put(
        self, family_id: FamilyId, *, content: bytes, mime_type: str, at: datetime
    ) -> Result[MediaObject, DomainError]: ...

    def get(self, media_id: MediaId) -> Result[bytes, DomainError]: ...

    def describe(self, media_id: MediaId) -> Result[MediaObject, DomainError]: ...

    def list_for_family(
        self, family_id: FamilyId
    ) -> Result[Sequence[MediaObject], DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class IntentEngine(Protocol):
    """PRD 13. A port, not a dependency (ADR-0004).

    V0 ships a deterministic offline adapter. An LLM adapter can replace it without the
    domain or the application layer changing a line.
    """

    def infer(self, source: SourceRef, *, note: str | None = None) -> Inference: ...


@runtime_checkable
class VoiceNoteRepository(Protocol):
    """Recordings, keyed by the recording (PRD 21).

    There is no `save_transcript`. A transcript is a field on a `VoiceNote`, so the only
    way to store one is to store the recording it belongs to - which is what stops a
    transcript from ever outliving its audio in this schema.
    """

    def get(self, media_id: MediaId) -> Result[VoiceNote, DomainError]: ...

    def save(self, note: VoiceNote) -> Result[VoiceNote, DomainError]: ...

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[VoiceNote], DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class Transcriber(Protocol):
    """Speech to an index (PRD 44, local-first).

    Returning `Ok(None)` is a first-class answer and the default one: no transcript is
    strictly better than a wrong transcript, because the recording is the artifact and
    loses nothing by being unindexed.

    The return type is a `Transcript`, not a `str`, so an adapter physically cannot hand
    back words without saying which engine produced them and how sure it was. A bare
    string would arrive at the wire indistinguishable from something a parent typed, which
    is the exact failure PRD 8.7 names: AI inference silently becoming family history.
    """

    def transcribe(self, media_id: MediaId) -> Result[Transcript | None, DomainError]: ...


@runtime_checkable
class EventPublisher(Protocol):
    """The audit trail PRD 44 asks for. Payloads are structural, never content."""

    def publish(self, events: Sequence[DomainEvent], *, family_id: FamilyId) -> None: ...

    def list_for_family(self, family_id: FamilyId) -> Sequence[DomainEvent]: ...

    def delete_for_family(self, family_id: FamilyId) -> int: ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Atomicity boundary. One family's archive must never be left half-written."""

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@runtime_checkable
class DeviceRepository(Protocol):
    """Paired devices. HARDENING 5.1.

    Lookup is by *fingerprint*, never by token: the plaintext must not reach a query, a slow
    query log or a database backup. The application hashes, the repository indexes.
    """

    def get(self, device_id: DeviceId) -> Result[Device, DomainError]: ...

    def save(self, device: Device) -> Result[Device, DomainError]: ...

    def find_by_fingerprint(self, fingerprint: str) -> Result[Device | None, DomainError]: ...

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Device], DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class PairingRepository(Protocol):
    """Open pairing codes, and the attempt ledger that makes a short code safe."""

    def save(self, request: PairingRequest) -> Result[PairingRequest, DomainError]: ...

    def find_by_fingerprint(
        self, fingerprint: str
    ) -> Result[PairingRequest | None, DomainError]: ...

    def record_attempt(self, *, succeeded: bool, at: datetime) -> None: ...

    def failures_since(self, since: datetime) -> int: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class IdempotencyStore(Protocol):
    """Replay protection for capture (PRD 11 - capture must survive a lost signal).

    A phone that saved offline replays its queue when the signal returns, and it cannot know
    whether the request that timed out was actually applied. The key makes the second attempt
    return the first attempt's answer instead of creating a second Spark.
    """

    def recall(
        self, key: str, *, family_id: FamilyId
    ) -> Result[tuple[int, str, str] | None, DomainError]:
        """`(status_code, response_json, request_fingerprint)` for a key already seen."""
        ...

    def remember(
        self,
        key: str,
        *,
        family_id: FamilyId,
        request_fingerprint: str,
        status_code: int,
        response_json: str,
        at: datetime,
    ) -> Result[None, DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...
