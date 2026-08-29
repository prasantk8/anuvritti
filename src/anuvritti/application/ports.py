"""Application ports.

The application says what it needs; adapters supply it. Nothing in this module knows that
SQLite, a filesystem or an HTTP framework exists - which is what makes the local-first
promise in PRD 44 an implementation detail rather than a rewrite.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, runtime_checkable

from anuvritti.domain.access import Device, PairingRequest
from anuvritti.domain.events import DomainEvent
from anuvritti.domain.family import Family
from anuvritti.domain.film import CompiledFilm, ConnectiveLine, FilmSpec
from anuvritti.domain.lexicon import FamilyLexicon
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

    #: One Spark, erased. PRD 44 gives a family the right to remove a single memory
    #: without surrendering the archive, so this belongs on the port, not only on the
    #: adapter that happens to implement it.
    def delete(self, spark_id: SparkId) -> Result[int, DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


@runtime_checkable
class MomentRepository(Protocol):
    def get(self, moment_id: MomentId) -> Result[Moment, DomainError]: ...

    def save(self, moment: Moment) -> Result[Moment, DomainError]: ...

    def list_for_family(self, family_id: FamilyId) -> Result[Sequence[Moment], DomainError]: ...

    def find_by_spark(self, spark_id: SparkId) -> Result[Moment | None, DomainError]: ...

    def delete(self, moment_id: MomentId) -> Result[int, DomainError]: ...

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

    def infer(
        self,
        source: SourceRef,
        *,
        note: str | None = None,
        lexicon: FamilyLexicon | None = None,
    ) -> Inference: ...


@runtime_checkable
class LexiconRepository(Protocol):
    """The family's own lexicon, in the family's own archive (TASK-801; PRD 44).

    Keyed by family and only by family. There is no `load_all`, no `list_families` and no
    call that returns more than one family's words - so there is no seam through which a
    shared model could be assembled later without someone adding a method here on purpose.
    """

    def load(self, family_id: FamilyId) -> Result[FamilyLexicon, DomainError]: ...

    def save(self, lexicon: FamilyLexicon) -> Result[FamilyLexicon, DomainError]: ...

    def delete_for_family(self, family_id: FamilyId) -> Result[int, DomainError]: ...


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
class FilmCompiler(Protocol):
    """Turns a planned film into a film that adds up (PRD 34).

    Look at what this protocol cannot say. There is no `render`, no output path, no codec,
    no frame rate argument and no way to hand back a video file. That is the whole design.

    Drawing a film needs a browser and an encoder - hundreds of megabytes of software with a
    network stack, a JIT and a monthly CVE, running for minutes at full tilt. The family's box
    is a small always-on machine holding every recording of their child, and `test_no_public_model`
    already forbids anything under `adapters/` from reaching a socket. Installing Chromium there
    so it can draw a birthday card would undo that in one line of a Dockerfile.

    So the compiler does everything a film needs *except* the pixels: it places the scenes,
    measures against the real audio, times the captions and checks that the arithmetic holds.
    What comes out is a `CompiledFilm` plus, at TASK-705, a bundle of the media it names -
    enough to draw the film anywhere, and not itself a film. The machine with the browser on
    it is a machine the family can turn off, and never one holding their archive.

    The other half of the arrangement is that this stays *cheap*: compiling is arithmetic over
    durations, so a parent can reorder a year, see the new running time, and change their mind,
    without a render farm being involved in the decision.
    """

    def compile(self, spec: FilmSpec) -> Result[CompiledFilm, DomainError]: ...


@dataclass(frozen=True, slots=True)
class SynthesisedSpeech:
    """A file a machine produced, and how long that file turned out to be.

    `seconds` is a probe of the audio, never a calculation over the words. A synthesiser is
    exactly the thing whose output length is least predictable from its input - two voices
    reading the same four words differ by half a second, and half a second is the difference
    between a line landing and a line being clipped.
    """

    media_id: MediaId
    seconds: float

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise ValueError("a spoken line that lasts no time was not spoken")


@runtime_checkable
class Narrator(Protocol):
    """Reads one of the product's own connective lines aloud (PRD 12, 39, 47).

    Three things about this signature are the design, and all three are things it *cannot* do.

    It takes a `ConnectiveLine`, not a string. There is no parameter here through which a
    sentence about a child could reach a synthesiser, so "synthesis is only used for neutral
    connective tissue" is enforced by the type of the port rather than by the discipline of
    whoever calls it next year.

    It returns a measured length, so nothing downstream ever has to estimate one. The contract
    is that `seconds` was probed from the file that was produced.

    It is optional everywhere it is used. `ComposeFilmUseCase` defaults to no narrator at all,
    and a film composed without one is silent between its memories rather than narrated by a
    machine - because silence is a legitimate answer and PRD 39 keeps voice synthesis at
    research status, not shipped by default.

    The file must be in the family's own media store before this returns. The film bundles
    every file it names, and a bundle that names audio nobody can fetch is a film that will
    fail at the far end instead of here.
    """

    def speak(
        self, line: ConnectiveLine, *, family_id: FamilyId
    ) -> Result[SynthesisedSpeech, DomainError]: ...


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
