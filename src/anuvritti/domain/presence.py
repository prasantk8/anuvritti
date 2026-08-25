"""Little Things and Right Now - ambient family presence (PRD 17, 18).

These are the lowest-friction objects in the product. They exist because the things most
worth keeping are usually the ones nobody has time to write down.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Final

from anuvritti.domain.events import DomainEvent, LittleThingCaptured, RightNowCaptured
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    LittleThingId,
    MemberId,
    RightNowId,
)
from anuvritti.shared.result import Err, Ok, Result

#: PRD 18/63.6. Every prompt asks the parent to *notice*, never to assess.
RIGHT_NOW_PROMPTS: Final[tuple[str, ...]] = (
    "What is he obsessed with this week?",
    "What made him laugh today?",
    "What word is he saying wrong in a way you hope he never fixes?",
    "What does he want to be in the middle of, right now?",
    "What question did he ask that you could not answer?",
    "What does he do when he thinks nobody is watching?",
    "What is his favourite thing to eat this month?",
    "What is he afraid of at the moment?",
    "What song is stuck in the house?",
    "What did he make today?",
    "Who did he talk about most this week?",
    "What is he suddenly good at?",
)


@dataclass(frozen=True, slots=True)
class LittleThing:
    """A note kept because it was small, not in spite of it (PRD 17)."""

    id: LittleThingId
    family_id: FamilyId
    author_id: MemberId
    subject_child_id: ChildId | None
    text: str | None
    audio_media_id: str | None
    created_at: datetime
    pending_events: tuple[DomainEvent, ...] = ()

    @classmethod
    def capture(
        cls,
        *,
        little_thing_id: LittleThingId,
        family_id: FamilyId,
        author_id: MemberId,
        at: datetime,
        subject_child_id: ChildId | None = None,
        text: str | None = None,
        audio_media_id: str | None = None,
    ) -> Result[LittleThing, DomainError]:
        cleaned = text.strip() if text and text.strip() else None
        if not cleaned and not audio_media_id:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED, "a little thing needs either words or a voice note"
                )
            )
        return Ok(
            cls(
                id=little_thing_id,
                family_id=family_id,
                author_id=author_id,
                subject_child_id=subject_child_id,
                text=cleaned,
                audio_media_id=audio_media_id,
                created_at=at,
                pending_events=(
                    LittleThingCaptured(
                        aggregate_id=str(little_thing_id),
                        occurred_at=at,
                        has_audio=audio_media_id is not None,
                    ),
                ),
            )
        )

    def with_events_cleared(self) -> LittleThing:
        return replace(self, pending_events=())


@dataclass(frozen=True, slots=True)
class RightNowSnapshot:
    """Who this child is at this moment, before it quietly becomes something else."""

    id: RightNowId
    family_id: FamilyId
    child_id: ChildId
    prompt: str
    answer: str
    captured_at: datetime
    pending_events: tuple[DomainEvent, ...] = ()

    @classmethod
    def prompt_for(cls, day: date) -> str:
        """Deterministic daily rotation - the same question all day, a new one tomorrow."""
        return RIGHT_NOW_PROMPTS[day.toordinal() % len(RIGHT_NOW_PROMPTS)]

    @classmethod
    def capture(
        cls,
        *,
        right_now_id: RightNowId,
        family_id: FamilyId,
        child_id: ChildId,
        prompt: str,
        answer: str,
        at: datetime,
    ) -> Result[RightNowSnapshot, DomainError]:
        if not prompt.strip():
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "a snapshot needs a prompt"))
        if not answer.strip():
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "a snapshot needs an answer"))
        return Ok(
            cls(
                id=right_now_id,
                family_id=family_id,
                child_id=child_id,
                prompt=prompt.strip(),
                answer=answer.strip(),
                captured_at=at,
                pending_events=(
                    RightNowCaptured(
                        aggregate_id=str(right_now_id),
                        occurred_at=at,
                        child_id=str(child_id),
                        prompt=prompt.strip(),
                    ),
                ),
            )
        )

    def with_events_cleared(self) -> RightNowSnapshot:
        return replace(self, pending_events=())
