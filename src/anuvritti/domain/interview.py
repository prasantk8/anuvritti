"""The Annual Birthday Interview in two voices (TASK-810, PRD 34, PRD 52, PRD 24).

On each birthday, the same short questions are asked to the child ("What is Papa terrible at?")
and to the parent, recorded in their own voices, filed against the age, never re-recorded.

The film gains a second narrator, and the film at eight plays the answers at four, five,
six and seven across the years.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from anuvritti.domain.events import DomainEvent
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId
from anuvritti.shared.result import Err, Ok, Result

DEFAULT_INTERVIEW_QUESTIONS: Final[tuple[str, ...]] = (
    "What is Papa terrible at?",
    "What is your favourite thing to do together?",
    "What makes you laugh the hardest?",
    "What do you want to learn this year?",
    "What is something you love about our family?",
)


@dataclass(frozen=True, slots=True)
class AnnualInterviewRecorded(DomainEvent):
    family_id: str
    child_id: str
    age_years: int

    def payload(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "child_id": self.child_id,
            "age_years": self.age_years,
        }


@dataclass(frozen=True, slots=True)
class InterviewAnswer:
    """One question, answered by child and/or parent."""

    question: str
    child_audio_media_id: str | None = None
    child_answer_text: str | None = None
    parent_audio_media_id: str | None = None
    parent_answer_text: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("interview question cannot be blank")
        has_child = bool(
            self.child_audio_media_id or (self.child_answer_text and self.child_answer_text.strip())
        )
        has_parent = bool(
            self.parent_audio_media_id
            or (self.parent_answer_text and self.parent_answer_text.strip())
        )
        if not (has_child or has_parent):
            raise ValueError("an interview answer must contain at least one voice or note")


@dataclass(frozen=True, slots=True)
class AnnualInterview:
    """A yearly artifact capturing child and parent voices on a birthday."""

    id: str
    family_id: FamilyId
    child_id: ChildId
    age_years: int
    recorded_on: date
    answers: tuple[InterviewAnswer, ...]
    created_at: datetime
    pending_events: tuple[DomainEvent, ...] = ()

    @classmethod
    def record(
        cls,
        *,
        interview_id: str,
        family_id: FamilyId,
        child_id: ChildId,
        age_years: int,
        recorded_on: date,
        answers: tuple[InterviewAnswer, ...],
        at: datetime,
    ) -> Result[AnnualInterview, DomainError]:
        if age_years < 1:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "age must be positive"))
        if not answers:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED, "annual interview requires at least one answer"
                )
            )

        return Ok(
            cls(
                id=interview_id,
                family_id=family_id,
                child_id=child_id,
                age_years=age_years,
                recorded_on=recorded_on,
                answers=answers,
                created_at=at,
                pending_events=(
                    AnnualInterviewRecorded(
                        aggregate_id=interview_id,
                        occurred_at=at,
                        family_id=str(family_id),
                        child_id=str(child_id),
                        age_years=age_years,
                    ),
                ),
            )
        )

    def with_events_cleared(self) -> AnnualInterview:
        return replace_events(self)


def replace_events(interview: AnnualInterview) -> AnnualInterview:
    from dataclasses import replace

    return replace(interview, pending_events=())


@dataclass(frozen=True, slots=True)
class InterviewProgression:
    """Answers to the same question across successive birthdays."""

    question: str
    responses_by_age: tuple[tuple[int, InterviewAnswer], ...]
