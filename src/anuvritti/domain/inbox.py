"""The Future Inbox - words whose opening belongs to a child's future (PRD 20).

A Future Inbox message is not a scheduled notification. It is a sealed artifact and a
promise about the conditions under which that artifact may be shown again. This module
makes the promise in three types:

* ``OpeningKey`` is a closed vocabulary chosen by the parent. Birthdays are calendar
  conditions; leaving home and "whenever you choose" are human decisions. There is no
  generic rule expression into which an inference engine can be smuggled.
* ``SealLedger`` fingerprints the exact UTF-8 or recording bytes presented at sealing.
  Opening returns those presented bytes only after kind, identity, size and digest all
  agree. The aggregate itself deliberately retains no plaintext or audio.
* ``MessageCare.SENSITIVE`` cannot be combined with a calendar key. Heartbreak, grief,
  conflict and fear are not facts a machine gets to infer about a child and act upon.

The parent's projection is intentionally smaller than the aggregate: it says ``sealed``.
It contains neither the message nor its opening condition and has nowhere to put a count.
Love deposited for later is not a progress metric.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Final

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, FutureMessageId, MediaId, MemberId
from anuvritti.shared.result import Err, Ok, Result

_SHA256_HEX_LENGTH: Final = 64


class ArtifactKind(StrEnum):
    """The two kinds of truth a message may preserve."""

    WRITTEN = "WRITTEN"
    RECORDING = "RECORDING"


class MessageCare(StrEnum):
    """Whether opening this message requires an explicitly human moment."""

    ORDINARY = "ORDINARY"
    SENSITIVE = "SENSITIVE"


class OpeningKey(StrEnum):
    """The complete set of promises a parent can put on a Future Inbox message.

    The enum is deliberately not named ``Trigger``. Two values describe life events that
    software cannot observe honestly, and one belongs solely to the child. Calling all six
    triggers would quietly invite the product to manufacture evidence for the last two.
    """

    FIFTH_BIRTHDAY = "FIFTH_BIRTHDAY"
    TENTH_BIRTHDAY = "TENTH_BIRTHDAY"
    THIRTEENTH_BIRTHDAY = "THIRTEENTH_BIRTHDAY"
    EIGHTEENTH_BIRTHDAY = "EIGHTEENTH_BIRTHDAY"
    LEAVING_HOME = "LEAVING_HOME"
    WHENEVER_YOU_CHOOSE = "WHENEVER_YOU_CHOOSE"

    @property
    def age(self) -> int | None:
        return _AGES.get(self)

    @property
    def is_calendar_key(self) -> bool:
        return self.age is not None


_AGES: Final[dict[OpeningKey, int]] = {
    OpeningKey.FIFTH_BIRTHDAY: 5,
    OpeningKey.TENTH_BIRTHDAY: 10,
    OpeningKey.THIRTEENTH_BIRTHDAY: 13,
    OpeningKey.EIGHTEENTH_BIRTHDAY: 18,
}


@dataclass(frozen=True, slots=True)
class PresentedArtifact:
    """Bytes retrieved from private storage and presented for verification."""

    kind: ArtifactKind
    source_id: str
    content: bytes = field(repr=False)

    @classmethod
    def written(cls, text: str, *, message_id: FutureMessageId | None = None) -> PresentedArtifact:
        # ``message_id`` is supplied by ``FutureMessage`` at verification time when callers
        # do not yet know the storage identity. Text is never stripped or normalised.
        return cls(ArtifactKind.WRITTEN, str(message_id) if message_id else "", text.encode())

    @classmethod
    def recording(cls, media_id: MediaId, content: bytes) -> PresentedArtifact:
        return cls(ArtifactKind.RECORDING, str(media_id), content)


@dataclass(frozen=True, slots=True)
class OpenedMessage:
    """Verified content released after its opening key has been honoured."""

    message_id: FutureMessageId
    kind: ArtifactKind
    opened_by: str
    opened_at: datetime
    content: bytes = field(repr=False)

    @property
    def written_text(self) -> str | None:
        if self.kind is not ArtifactKind.WRITTEN:
            return None
        return self.content.decode("utf-8")


@dataclass(frozen=True, slots=True)
class SealedArtifact:
    """One immutable entry in the message's provenance ledger."""

    kind: ArtifactKind
    source_id: str
    content_hash: str
    byte_size: int

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("a sealed artifact must identify what was sealed")
        if self.byte_size <= 0:
            raise ValueError("a sealed artifact must contain bytes")
        if len(self.content_hash) != _SHA256_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be a sha256 hex digest")

    @classmethod
    def from_written(
        cls, message_id: FutureMessageId, text: str
    ) -> Result[SealedArtifact, DomainError]:
        if not text.strip():
            return _invalid("a Future Inbox letter cannot be blank")
        return Ok(cls._from_bytes(ArtifactKind.WRITTEN, str(message_id), text.encode("utf-8")))

    @classmethod
    def from_recording(
        cls, media_id: MediaId, content: bytes
    ) -> Result[SealedArtifact, DomainError]:
        if not content:
            return _invalid("a Future Inbox recording cannot be empty")
        return Ok(cls._from_bytes(ArtifactKind.RECORDING, str(media_id), content))

    @classmethod
    def _from_bytes(cls, kind: ArtifactKind, source_id: str, content: bytes) -> SealedArtifact:
        return cls(
            kind=kind,
            source_id=source_id,
            content_hash=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
        )

    def verify(self, presented: PresentedArtifact) -> Result[bytes, DomainError]:
        """Return exact bytes or a content-free refusal; never a best-effort opening."""
        source_id = presented.source_id
        # A written artifact's id is its message id. Callers can omit it because the ledger
        # already knows it; recordings retain their independent media identity.
        if presented.kind is ArtifactKind.WRITTEN and not source_id:
            source_id = self.source_id
        matches = (
            presented.kind is self.kind
            and source_id == self.source_id
            and len(presented.content) == self.byte_size
            and hmac.compare_digest(
                hashlib.sha256(presented.content).hexdigest(), self.content_hash
            )
        )
        if not matches:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "the artifact presented at opening does not match the sealed provenance",
                    {"expected_kind": self.kind.value, "presented_kind": presented.kind.value},
                )
            )
        return Ok(presented.content)

    def to_dict(self) -> dict[str, str | int]:
        """Portable proof only: identifiers and measurements, never the content."""
        return {
            "kind": self.kind.value,
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True, slots=True)
class SealLedger:
    """The portable proof of what was present when one message was sealed."""

    message_id: FutureMessageId
    sealed_at: datetime
    entries: tuple[SealedArtifact, ...]

    def __post_init__(self) -> None:
        if len(self.entries) != 1:
            raise ValueError("a Future Inbox ledger covers exactly one sealed artifact")

    @property
    def entry(self) -> SealedArtifact:
        return self.entries[0]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "anuvritti.future-inbox-provenance.v1",
            "message_id": str(self.message_id),
            "sealed_at": self.sealed_at.isoformat(),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ParentSealedView:
    """Everything the parent's inbox is permitted to say about sealed messages."""

    label: str = "sealed"

    def __post_init__(self) -> None:
        if self.label != "sealed":
            raise ValueError("the parent view of a Future Inbox message only says sealed")

    def to_dict(self) -> dict[str, str]:
        return {"status": self.label}


@dataclass(frozen=True, slots=True)
class FutureMessage:
    """A sealed promise, containing proof and policy but no family content."""

    id: FutureMessageId
    family_id: FamilyId
    child_id: ChildId
    sealed_by: MemberId
    opening_key: OpeningKey
    care: MessageCare
    sealed_at: datetime
    ledger: SealLedger

    def __post_init__(self) -> None:
        if self.ledger.message_id != self.id:
            raise ValueError("the seal ledger must belong to this Future Inbox message")
        if self.ledger.sealed_at != self.sealed_at:
            raise ValueError("the seal ledger must record the moment this message was sealed")
        if self.care is MessageCare.SENSITIVE and self.opening_key.is_calendar_key:
            raise ValueError("a sensitive message may not have a machine-triggered opening key")

    @classmethod
    def seal_written(
        cls,
        *,
        message_id: FutureMessageId,
        family_id: FamilyId,
        child_id: ChildId,
        sealed_by: MemberId,
        opening_key: OpeningKey,
        care: MessageCare,
        text: str,
        at: datetime,
    ) -> Result[FutureMessage, DomainError]:
        artifact = SealedArtifact.from_written(message_id, text)
        if isinstance(artifact, Err):
            return artifact
        return cls._seal(
            message_id=message_id,
            family_id=family_id,
            child_id=child_id,
            sealed_by=sealed_by,
            opening_key=opening_key,
            care=care,
            artifact=artifact.value,
            at=at,
        )

    @classmethod
    def seal_recording(
        cls,
        *,
        message_id: FutureMessageId,
        family_id: FamilyId,
        child_id: ChildId,
        sealed_by: MemberId,
        opening_key: OpeningKey,
        care: MessageCare,
        media_id: MediaId,
        content: bytes,
        at: datetime,
    ) -> Result[FutureMessage, DomainError]:
        artifact = SealedArtifact.from_recording(media_id, content)
        if isinstance(artifact, Err):
            return artifact
        return cls._seal(
            message_id=message_id,
            family_id=family_id,
            child_id=child_id,
            sealed_by=sealed_by,
            opening_key=opening_key,
            care=care,
            artifact=artifact.value,
            at=at,
        )

    @classmethod
    def _seal(
        cls,
        *,
        message_id: FutureMessageId,
        family_id: FamilyId,
        child_id: ChildId,
        sealed_by: MemberId,
        opening_key: OpeningKey,
        care: MessageCare,
        artifact: SealedArtifact,
        at: datetime,
    ) -> Result[FutureMessage, DomainError]:
        if at.tzinfo is None or at.utcoffset() is None:
            return _invalid("a Future Inbox seal needs an absolute time")
        if care is MessageCare.SENSITIVE and opening_key.is_calendar_key:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "a sensitive message needs a human-chosen opening key",
                    {"opening_key": opening_key.value},
                )
            )
        ledger = SealLedger(message_id=message_id, sealed_at=at, entries=(artifact,))
        return Ok(
            cls(
                id=message_id,
                family_id=family_id,
                child_id=child_id,
                sealed_by=sealed_by,
                opening_key=opening_key,
                care=care,
                sealed_at=at,
                ledger=ledger,
            )
        )

    def for_parent(self) -> ParentSealedView:
        return ParentSealedView()

    def open_automatically(
        self,
        presented: PresentedArtifact,
        *,
        child_born_on: date,
        on: date,
        at: datetime,
    ) -> Result[OpenedMessage, DomainError]:
        age = self.opening_key.age
        if age is None or self.care is MessageCare.SENSITIVE:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "this opening belongs to a person, not a machine",
                    {"opening_key": self.opening_key.value},
                )
            )
        due_on = _birthday(child_born_on, age)
        if on < due_on:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "this message is still sealed",
                    {"opens_on": due_on.isoformat()},
                )
            )
        return self._verified_open(presented, opened_by="calendar", at=at)

    def open_by_choice(
        self,
        presented: PresentedArtifact,
        *,
        opening_key: OpeningKey,
        opened_by: MemberId | ChildId,
        at: datetime,
    ) -> Result[OpenedMessage, DomainError]:
        if self.opening_key.is_calendar_key or opening_key is not self.opening_key:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "the person opening this message did not present its chosen key",
                    {"opening_key": opening_key.value},
                )
            )
        if self.opening_key is OpeningKey.WHENEVER_YOU_CHOOSE and opened_by != self.child_id:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "whenever you choose belongs only to the child it was written for",
                )
            )
        return self._verified_open(presented, opened_by=str(opened_by), at=at)

    def _verified_open(
        self, presented: PresentedArtifact, *, opened_by: str, at: datetime
    ) -> Result[OpenedMessage, DomainError]:
        if at.tzinfo is None or at.utcoffset() is None:
            return _invalid("opening a Future Inbox message needs an absolute time")
        if at < self.sealed_at:
            return _invalid("a Future Inbox message cannot open before it was sealed")
        verified = self.ledger.entry.verify(presented)
        if isinstance(verified, Err):
            return verified
        return Ok(
            OpenedMessage(
                message_id=self.id,
                kind=self.ledger.entry.kind,
                opened_by=opened_by,
                opened_at=at,
                content=verified.value,
            )
        )


def _birthday(born_on: date, years: int) -> date:
    try:
        return born_on.replace(year=born_on.year + years)
    except ValueError:
        # A child born on 29 February reaches the milestone at the end of February in a
        # non-leap year. Waiting until March would make the product miss the birthday.
        return born_on.replace(year=born_on.year + years, day=28)


def _invalid(message: str) -> Err[DomainError]:
    return Err(DomainError(ErrorCode.VALIDATION_FAILED, message))
