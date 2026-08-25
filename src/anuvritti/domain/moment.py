"""The Moment - a Spark that left the phone and entered life (PRD 15).

The only hard rule here is that recording a Moment must never feel like homework.
Every attachment is optional, because the thing worth counting is the experience.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from anuvritti.domain.events import DomainEvent, MomentCreated
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId, MomentId, SparkId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class Moment:
    """What actually happened."""

    id: MomentId
    family_id: FamilyId
    spark_id: SparkId
    happened_on: date
    reflection: str | None
    photo_media_id: str | None
    audio_media_id: str | None
    created_by: MemberId
    created_at: datetime
    pending_events: tuple[DomainEvent, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        moment_id: MomentId,
        family_id: FamilyId,
        spark_id: SparkId,
        created_by: MemberId,
        spark_captured_at: datetime,
        at: datetime,
        happened_on: date | None = None,
        reflection: str | None = None,
        photo_media_id: str | None = None,
        audio_media_id: str | None = None,
    ) -> Result[Moment, DomainError]:
        day = happened_on or at.date()
        if day > at.date():
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "a moment cannot have happened in the future",
                    {"happened_on": day.isoformat()},
                )
            )
        if day < spark_captured_at.date():
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "a moment cannot predate the spark it came from",
                    {"happened_on": day.isoformat()},
                )
            )

        cleaned = reflection.strip() if reflection and reflection.strip() else None
        days_from_capture = max(0, (day - spark_captured_at.date()).days)

        return Ok(
            cls(
                id=moment_id,
                family_id=family_id,
                spark_id=spark_id,
                happened_on=day,
                reflection=cleaned,
                photo_media_id=photo_media_id,
                audio_media_id=audio_media_id,
                created_by=created_by,
                created_at=at,
                pending_events=(
                    MomentCreated(
                        aggregate_id=str(moment_id),
                        occurred_at=at,
                        spark_id=str(spark_id),
                        days_from_capture=days_from_capture,
                        has_photo=photo_media_id is not None,
                        has_audio=audio_media_id is not None,
                        has_reflection=cleaned is not None,
                    ),
                ),
            )
        )

    @property
    def has_evidence(self) -> bool:
        """Whether anything was kept. A Moment with nothing attached still counts."""
        return any((self.reflection, self.photo_media_id, self.audio_media_id))

    def with_events_cleared(self) -> Moment:
        return replace(self, pending_events=())
