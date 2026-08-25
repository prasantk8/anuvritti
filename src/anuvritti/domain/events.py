"""Domain events.

The audit trail PRD 44 asks for and the source of the PRD 53 metrics. Payloads are
structural only: the log records that something happened, never what was said. See
docs/contracts/events.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from anuvritti.domain.values import IntentType, SourceKind


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base event. `aggregate_id` and `occurred_at` are common to all."""

    aggregate_id: str
    occurred_at: datetime

    @property
    def name(self) -> str:
        return type(self).__name__

    def payload(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True, slots=True)
class SparkCaptured(DomainEvent):
    family_id: str
    owner_id: str
    subject_child_id: str | None
    source_kind: SourceKind

    def payload(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "owner_id": self.owner_id,
            "subject_child_id": self.subject_child_id,
            "source_kind": self.source_kind.value,
        }


@dataclass(frozen=True, slots=True)
class SparkEnriched(DomainEvent):
    intent: IntentType
    confidence: float
    category: str

    def payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "category": self.category,
        }


@dataclass(frozen=True, slots=True)
class SparkWhyRecorded(DomainEvent):
    has_voice: bool

    def payload(self) -> dict[str, Any]:
        return {"has_voice": self.has_voice}


@dataclass(frozen=True, slots=True)
class SparkFieldOverridden(DomainEvent):
    field: str

    def payload(self) -> dict[str, Any]:
        return {"field": self.field}


@dataclass(frozen=True, slots=True)
class SparkSuggested(DomainEvent):
    score: float
    reason_key: str
    days_since_capture: int

    def payload(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reason_key": self.reason_key,
            "days_since_capture": self.days_since_capture,
        }


@dataclass(frozen=True, slots=True)
class SparkSnoozed(DomainEvent):
    snoozed_until: datetime

    def payload(self) -> dict[str, Any]:
        return {"snoozed_until": self.snoozed_until.isoformat()}


@dataclass(frozen=True, slots=True)
class SparkArchived(DomainEvent):
    def payload(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True, slots=True)
class SparkPlanned(DomainEvent):
    def payload(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True, slots=True)
class MomentCreated(DomainEvent):
    """The event the whole product exists to produce (PRD 53)."""

    spark_id: str
    days_from_capture: int
    has_photo: bool
    has_audio: bool
    has_reflection: bool

    def payload(self) -> dict[str, Any]:
        return {
            "spark_id": self.spark_id,
            "days_from_capture": self.days_from_capture,
            "has_photo": self.has_photo,
            "has_audio": self.has_audio,
            "has_reflection": self.has_reflection,
        }


@dataclass(frozen=True, slots=True)
class LittleThingCaptured(DomainEvent):
    has_audio: bool

    def payload(self) -> dict[str, Any]:
        return {"has_audio": self.has_audio}


@dataclass(frozen=True, slots=True)
class RightNowCaptured(DomainEvent):
    child_id: str
    prompt: str

    def payload(self) -> dict[str, Any]:
        return {"child_id": self.child_id, "prompt": self.prompt}


@dataclass(frozen=True, slots=True)
class FamilyDataExported(DomainEvent):
    spark_count: int
    media_count: int

    def payload(self) -> dict[str, Any]:
        return {"spark_count": self.spark_count, "media_count": self.media_count}


@dataclass(frozen=True, slots=True)
class FamilyDataDeleted(DomainEvent):
    deleted_counts: dict[str, int]

    def payload(self) -> dict[str, Any]:
        return {"deleted_counts": dict(self.deleted_counts)}
