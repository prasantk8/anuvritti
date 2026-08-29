"""The Spark aggregate - the fundamental product object (PRD 9, 10).

Three rules this module exists to hold:

1. The lifecycle is a state machine. An illegal transition is a returned `Err`, never a
   raised exception and never a silently-accepted write.
2. Every AI-derived field carries its provenance, and a human correction is permanent.
3. A Spark keeps its meaning even when the link it came from disappears (PRD 43).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from anuvritti.domain.events import (
    DomainEvent,
    SparkArchived,
    SparkCaptured,
    SparkEnriched,
    SparkFieldOverridden,
    SparkPlanned,
    SparkSnoozed,
    SparkSuggested,
    SparkWhyRecorded,
)
from anuvritti.domain.values import (
    AgeRange,
    Attributed,
    Confidence,
    IntentType,
    SourceRef,
    SparkStatus,
    Visibility,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId
from anuvritti.shared.result import Err, Ok, Result

UNCATEGORISED = "uncategorised"


@dataclass(frozen=True, slots=True)
class Inference:
    """What the Intent Engine believes about a Spark (PRD 13).

    A plain value object, so the domain never depends on how the inference was produced.
    """

    title: str
    intent: IntentType
    intent_confidence: Confidence
    category: str
    category_confidence: Confidence
    age_range: AgeRange | None = None
    age_confidence: Confidence | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Why:
    """The human answer to "what made you save this?" (PRD 12)."""

    text: str | None
    voice_media_id: str | None
    recorded_at: datetime

    @property
    def has_voice(self) -> bool:
        return self.voice_media_id is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "voice_media_id": self.voice_media_id,
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class Spark:
    """Something that made a person think: I want to remember this for us."""

    id: SparkId
    family_id: FamilyId
    owner_id: MemberId
    subject_child_id: ChildId | None
    title: str
    note: str | None
    source: SourceRef
    intent: Attributed[IntentType]
    category: Attributed[str]
    age_range: Attributed[AgeRange] | None
    tags: tuple[str, ...]
    why: Why | None
    status: SparkStatus
    visibility: Visibility
    suggested_count: int
    last_suggested_at: datetime | None
    snoozed_until: datetime | None
    created_at: datetime
    updated_at: datetime
    pending_events: tuple[DomainEvent, ...] = ()

    # ------------------------------------------------------------- creation
    @classmethod
    def capture(
        cls,
        *,
        spark_id: SparkId,
        family_id: FamilyId,
        owner_id: MemberId,
        source: SourceRef,
        at: datetime,
        subject_child_id: ChildId | None = None,
        note: str | None = None,
        visibility: Visibility | None = None,
    ) -> Spark:
        """Save it now, understand it later. PRD 11 targets under ten seconds."""
        return cls(
            id=spark_id,
            family_id=family_id,
            owner_id=owner_id,
            subject_child_id=subject_child_id,
            title=source.display_title(),
            note=note.strip() if note and note.strip() else None,
            source=source,
            # Before the engine speaks, the honest default is "I want to remember this".
            intent=Attributed.defaulted(IntentType.REMEMBER),
            category=Attributed.defaulted(UNCATEGORISED),
            age_range=None,
            tags=(),
            why=None,
            status=SparkStatus.CAPTURED,
            visibility=visibility or Visibility.default(),
            suggested_count=0,
            last_suggested_at=None,
            snoozed_until=None,
            created_at=at,
            updated_at=at,
            pending_events=(
                SparkCaptured(
                    aggregate_id=str(spark_id),
                    occurred_at=at,
                    family_id=str(family_id),
                    owner_id=str(owner_id),
                    subject_child_id=str(subject_child_id) if subject_child_id else None,
                    source_kind=source.kind,
                ),
            ),
        )

    # ------------------------------------------------------------ inference
    def apply_inference(self, inference: Inference) -> Spark:
        """Apply AI understanding, leaving every human correction untouched (PRD 13)."""
        if self.status is SparkStatus.ARCHIVED:
            return self

        intent = self.intent.reinferred(inference.intent, inference.intent_confidence)
        category = self.category.reinferred(inference.category, inference.category_confidence)

        age_range = self.age_range
        if inference.age_range is not None and inference.age_confidence is not None:
            age_range = (
                age_range.reinferred(inference.age_range, inference.age_confidence)
                if age_range is not None
                else Attributed.inferred(inference.age_range, inference.age_confidence)
            )

        # A human-chosen title is not something the engine gets to rewrite.
        title = inference.title if not self.intent.human_override else self.title
        status = SparkStatus.WAITING if self.status is SparkStatus.CAPTURED else self.status

        return self._evolve(
            title=title or self.title,
            intent=intent,
            category=category,
            age_range=age_range,
            tags=tuple(dict.fromkeys(self.tags + inference.tags)),
            status=status,
            at=self.updated_at,
            event=SparkEnriched(
                aggregate_id=str(self.id),
                occurred_at=self.updated_at,
                intent=intent.value,
                confidence=intent.confidence.value,
                category=category.value,
            ),
        )

    # ------------------------------------------------------ human overrides
    def override_intent(self, intent: IntentType) -> Result[Spark, DomainError]:
        if not intent.is_available_in_v0:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    f"{intent} is not one of the six V0 intents (PRD 48 F4)",
                    {"allowed": sorted(i.value for i in IntentType.v0_set())},
                )
            )
        return Ok(self._overridden("intent", intent=self.intent.override(intent)))

    def override_age_range(self, age_range: AgeRange) -> Result[Spark, DomainError]:
        current = self.age_range or Attributed.defaulted(age_range)
        return Ok(self._overridden("age_range", age_range=current.override(age_range)))

    def override_category(self, category: str) -> Result[Spark, DomainError]:
        cleaned = category.strip()
        if not cleaned:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "category cannot be blank"))
        return Ok(self._overridden("category", category=self.category.override(cleaned)))

    def change_visibility(self, visibility: Visibility) -> Result[Spark, DomainError]:
        return Ok(self._evolve(visibility=visibility, at=self.updated_at))

    def _overridden(self, field: str, **changes: Any) -> Spark:
        return self._evolve(
            at=self.updated_at,
            event=SparkFieldOverridden(
                aggregate_id=str(self.id), occurred_at=self.updated_at, field=field
            ),
            **changes,
        )

    # ------------------------------------------------------------ why layer
    def record_why(
        self,
        *,
        at: datetime,
        text: str | None = None,
        voice_media_id: str | None = None,
    ) -> Result[Spark, DomainError]:
        """PRD 12 - five seconds of voice can outlive every other field on the record."""
        cleaned = text.strip() if text else None
        if not cleaned and not voice_media_id:
            return Err(
                DomainError(ErrorCode.VALIDATION_FAILED, "a why needs either text or a voice note")
            )
        why = Why(text=cleaned, voice_media_id=voice_media_id, recorded_at=at)
        return Ok(
            self._evolve(
                why=why,
                at=at,
                event=SparkWhyRecorded(
                    aggregate_id=str(self.id), occurred_at=at, has_voice=why.has_voice
                ),
            )
        )

    # ------------------------------------------------------------ lifecycle
    def mark_relevant(self) -> Result[Spark, DomainError]:
        if self.status is not SparkStatus.WAITING:
            return self._illegal("mark_relevant")
        return Ok(self._evolve(status=SparkStatus.RELEVANT, at=self.updated_at))

    def mark_suggested(
        self, at: datetime, *, score: float, reason_key: str = "time_passed"
    ) -> Result[Spark, DomainError]:
        if self.status is SparkStatus.ARCHIVED:
            return self._archived("mark_suggested")
        if not self.status.is_returnable:
            return self._illegal("mark_suggested")
        return Ok(
            self._evolve(
                status=SparkStatus.SUGGESTED,
                suggested_count=self.suggested_count + 1,
                last_suggested_at=at,
                snoozed_until=None,
                at=at,
                event=SparkSuggested(
                    aggregate_id=str(self.id),
                    occurred_at=at,
                    score=score,
                    reason_key=reason_key,
                    days_since_capture=self.days_since_capture(at),
                ),
            )
        )

    def snooze(self, *, until: datetime) -> Result[Spark, DomainError]:
        """ "Maybe later" (PRD 48 F6). Later must actually mean later (PRD 8.5)."""
        if self.status is not SparkStatus.SUGGESTED:
            return self._illegal("snooze")
        if until <= self.updated_at:
            return Err(
                DomainError(ErrorCode.VALIDATION_FAILED, "snooze must point into the future")
            )
        return Ok(
            self._evolve(
                status=SparkStatus.WAITING,
                snoozed_until=until,
                at=self.updated_at,
                event=SparkSnoozed(
                    aggregate_id=str(self.id), occurred_at=self.updated_at, snoozed_until=until
                ),
            )
        )

    def archive(self) -> Result[Spark, DomainError]:
        """ "Not relevant anymore". The system must take no for an answer (PRD 8.5)."""
        if self.status is SparkStatus.ARCHIVED:
            return self._archived("archive")
        if self.status.is_lived:
            return self._illegal("archive")
        return Ok(
            self._evolve(
                status=SparkStatus.ARCHIVED,
                at=self.updated_at,
                event=SparkArchived(aggregate_id=str(self.id), occurred_at=self.updated_at),
            )
        )

    def plan(self) -> Result[Spark, DomainError]:
        """ "Let's do it"."""
        if self.status is SparkStatus.ARCHIVED:
            return self._archived("plan")
        if self.status is not SparkStatus.SUGGESTED:
            return self._illegal("plan")
        return Ok(
            self._evolve(
                status=SparkStatus.PLANNED,
                at=self.updated_at,
                event=SparkPlanned(aggregate_id=str(self.id), occurred_at=self.updated_at),
            )
        )

    def experience(self, at: datetime) -> Result[Spark, DomainError]:
        """It actually happened (PRD 15). Real life does not wait for a notification."""
        if self.status is SparkStatus.ARCHIVED:
            return self._archived("experience")
        if not (self.status.is_returnable or self.status is SparkStatus.PLANNED):
            return self._illegal("experience")
        return Ok(self._evolve(status=SparkStatus.EXPERIENCED, at=at))

    def remember(self) -> Result[Spark, DomainError]:
        if self.status is not SparkStatus.EXPERIENCED:
            return self._illegal("remember")
        return Ok(self._evolve(status=SparkStatus.REMEMBERED, at=self.updated_at))

    # -------------------------------------------------------------- queries
    @property
    def retains_meaning_without_network(self) -> bool:
        """PRD 43 - would this still say something if the link died today?"""
        return self.source.retains_meaning_without_network or bool(
            self.note or (self.why and (self.why.text or self.why.voice_media_id))
        )

    def is_age_appropriate_for(self, age_years: int) -> bool:
        if self.age_range is None:
            return True
        return self.age_range.value.contains(age_years)

    def days_since_capture(self, now: datetime) -> int:
        return (now - self.created_at).days

    def is_snoozed_at(self, now: datetime) -> bool:
        return self.snoozed_until is not None and now < self.snoozed_until

    def with_events_cleared(self) -> Spark:
        return replace(self, pending_events=())

    # --------------------------------------------------------------- internals
    def _evolve(self, *, at: datetime, event: DomainEvent | None = None, **changes: Any) -> Spark:
        events = (*self.pending_events, event) if event is not None else self.pending_events
        return replace(self, updated_at=max(at, self.updated_at), pending_events=events, **changes)

    def _illegal(self, action: str) -> Err[DomainError]:
        return Err(
            DomainError(
                ErrorCode.SPARK_INVALID_TRANSITION,
                f"cannot {action} a spark that is {self.status.value}",
                {"status": self.status.value, "action": action},
            )
        )

    def _archived(self, action: str) -> Err[DomainError]:
        return Err(
            DomainError(
                ErrorCode.SPARK_ARCHIVED,
                f"cannot {action}: this spark was marked not relevant anymore",
                {"status": self.status.value, "action": action},
            )
        )
