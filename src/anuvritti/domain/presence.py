"""Little Things and Right Now - ambient family presence (PRD 17, 18).

These are the lowest-friction objects in the product. They exist because the things most
worth keeping are usually the ones nobody has time to write down.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
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


class LittleThingKind(StrEnum):
    NOTE = "NOTE"
    WORD = "WORD"


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
    kind: LittleThingKind = LittleThingKind.NOTE
    meaning: str | None = None
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
        kind: LittleThingKind = LittleThingKind.NOTE,
        meaning: str | None = None,
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
                kind=kind,
                meaning=meaning.strip() if meaning and meaning.strip() else None,
                pending_events=(
                    LittleThingCaptured(
                        aggregate_id=str(little_thing_id),
                        occurred_at=at,
                        has_audio=audio_media_id is not None,
                    ),
                ),
            )
        )

    @classmethod
    def capture_word(
        cls,
        *,
        little_thing_id: LittleThingId,
        family_id: FamilyId,
        author_id: MemberId,
        word: str,
        meaning: str,
        at: datetime,
        subject_child_id: ChildId | None = None,
        audio_media_id: str | None = None,
    ) -> Result[LittleThing, DomainError]:
        """TASK-812: 'The Dictionary of Us' - records invented words in
        first-heard order.
        """
        cleaned_word = word.strip()
        cleaned_meaning = meaning.strip()
        if not cleaned_word:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "a word cannot be blank"))
        if not cleaned_meaning:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "a word meaning cannot be blank"))
        return Ok(
            cls(
                id=little_thing_id,
                family_id=family_id,
                author_id=author_id,
                subject_child_id=subject_child_id,
                text=cleaned_word,
                kind=LittleThingKind.WORD,
                meaning=cleaned_meaning,
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
    """The answer to one Right Now question, anchored in time (PRD 17, 48 F5).

    Right Now exists to catch what is true today before it becomes an unremarked past:
    the favourite colour that changes every three weeks, the current mispronunciation,
    the friend whose name comes up at every meal. It never aggregates across families
    and it never scores a child against a norm.
    """

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
        right_now_id: RightNowId | None = None,
        snapshot_id: RightNowId | None = None,
        family_id: FamilyId,
        child_id: ChildId,
        prompt: str,
        answer: str,
        at: datetime,
    ) -> Result[RightNowSnapshot, DomainError]:
        actual_id = right_now_id or snapshot_id
        if actual_id is None:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "a snapshot requires an id"))
        cleaned_prompt = prompt.strip()
        cleaned_answer = answer.strip()
        if not cleaned_prompt:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "a snapshot requires a prompt"))
        if not cleaned_answer:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "a snapshot requires an answer"))
        return Ok(
            cls(
                id=actual_id,
                family_id=family_id,
                child_id=child_id,
                prompt=cleaned_prompt,
                answer=cleaned_answer,
                captured_at=at,
                pending_events=(
                    RightNowCaptured(
                        aggregate_id=str(actual_id),
                        occurred_at=at,
                        child_id=str(child_id),
                        prompt=cleaned_prompt,
                    ),
                ),
            )
        )

    def with_events_cleared(self) -> RightNowSnapshot:
        return replace(self, pending_events=())


MIN_SNAPSHOT_INTERVAL_DAYS: Final[int] = 60


@dataclass(frozen=True, slots=True)
class RightNowMilestone:
    """PRD 17 - Occasional multi-field snapshot across seasons, avoiding daily habit loops."""

    id: RightNowId
    family_id: FamilyId
    child_id: ChildId
    captured_at: datetime
    obsessions: str = ""
    funny_words: str = ""
    favorite_things: str = ""
    interests: tuple[str, ...] = ()
    difficult_questions: str = ""
    notes: str = ""
    pending_events: tuple[DomainEvent, ...] = ()

    @classmethod
    def capture(
        cls,
        *,
        milestone_id: RightNowId,
        family_id: FamilyId,
        child_id: ChildId,
        at: datetime,
        obsessions: str = "",
        funny_words: str = "",
        favorite_things: str = "",
        interests: tuple[str, ...] = (),
        difficult_questions: str = "",
        notes: str = "",
    ) -> Result[RightNowMilestone, DomainError]:
        has_content = any(
            (
                obsessions.strip(),
                funny_words.strip(),
                favorite_things.strip(),
                difficult_questions.strip(),
                notes.strip(),
                interests,
            )
        )
        if not has_content:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "a milestone snapshot needs at least one field answered",
                )
            )
        return Ok(
            cls(
                id=milestone_id,
                family_id=family_id,
                child_id=child_id,
                captured_at=at,
                obsessions=obsessions.strip(),
                funny_words=funny_words.strip(),
                favorite_things=favorite_things.strip(),
                interests=tuple(i.strip() for i in interests if i.strip()),
                difficult_questions=difficult_questions.strip(),
                notes=notes.strip(),
                pending_events=(
                    RightNowCaptured(
                        aggregate_id=str(milestone_id),
                        occurred_at=at,
                        child_id=str(child_id),
                        prompt="Right Now Milestone Snapshot",
                    ),
                ),
            )
        )

    def is_due(self, now: datetime, min_interval_days: int = MIN_SNAPSHOT_INTERVAL_DAYS) -> bool:
        return (now - self.captured_at).days >= min_interval_days

    def with_events_cleared(self) -> RightNowMilestone:
        return replace(self, pending_events=())
