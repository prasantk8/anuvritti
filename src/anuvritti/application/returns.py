"""TASK-811 - Ask Papa, later (PRD 8.1, 17, 33).

When a child asks a question the parent cannot answer in the moment, it is recorded
without urgency or guilt. Years later, on age alone, the Return Engine surfaces it:
"She asked this when she was four."

The parent records an answer filed against the question. The film compiler gathers
these into the chapter "Your questions, and what Papa found out".

Never listed as "unanswered", never counted, no scorekeeping.
"""

from __future__ import annotations

from dataclasses import dataclass

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    MomentRepository,
    SparkRepository,
    UnitOfWork,
)
from anuvritti.domain.events import DeferredQuestionAnswered
from anuvritti.domain.moment import Moment
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import (
    IntentType,
    SparkStatus,
)
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    IdGenerator,
    MemberId,
    MomentId,
    SparkId,
)
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class DeferredQuestionSurfaced:
    """A question surfaced when the child has grown older."""

    spark: Spark
    child_name: str
    asked_age_years: int
    prompt_text: str


@dataclass(frozen=True, slots=True)
class AnswerDeferredQuestionCommand:
    family_id: FamilyId
    spark_id: SparkId
    author_id: MemberId
    audio_media_id: str | None = None
    note: str | None = None


class DeferredQuestionsUseCase:
    """Brings back questions a child asked years ago, and records the answer."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        moments: MomentRepository,
        events: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._moments = moments
        self._events = events
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def surface_for_child(
        self, family_id: FamilyId, child_id: ChildId
    ) -> Result[list[DeferredQuestionSurfaced], DomainError]:
        family_res = self._families.get(family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())
        family = family_res.unwrap()
        child_res = family.child(child_id)
        if child_res.is_err():
            return Err(child_res.unwrap_err())
        child = child_res.unwrap()

        sparks_res = self._sparks.list_for_family(family_id)
        if sparks_res.is_err():
            return Err(sparks_res.unwrap_err())

        surfaced: list[DeferredQuestionSurfaced] = []
        now = self._clock.now()
        current_age = child.age_years(now.date())

        for spark in sparks_res.unwrap():
            if spark.subject_child_id != child_id:
                continue
            if spark.intent.value != IntentType.TELL:
                continue
            if spark.status.is_lived or spark.status is SparkStatus.ARCHIVED:
                continue

            asked_age = child.age_years(spark.created_at.date())
            # Return years on (at least 1 full year older)
            if current_age > asked_age:
                prompt_text = (
                    f"{child.display_name} asked this when {child.display_name} was {asked_age}."
                )
                surfaced.append(
                    DeferredQuestionSurfaced(
                        spark=spark,
                        child_name=child.display_name,
                        asked_age_years=asked_age,
                        prompt_text=prompt_text,
                    )
                )

        return Ok(surfaced)

    def answer_question(
        self, command: AnswerDeferredQuestionCommand
    ) -> Result[Moment, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        spark_res = self._sparks.get(command.spark_id)
        if spark_res.is_err():
            return Err(spark_res.unwrap_err())
        spark = spark_res.unwrap()

        if spark.family_id != command.family_id:
            return Err(
                DomainError(ErrorCode.PERMISSION_DENIED, "spark belongs to a different family")
            )

        now = self._clock.now()
        source_title = spark.source.title or "Question"
        reflection_text = (
            f"What Papa found out: {command.note}"
            if command.note
            else f"What Papa found out: {source_title}"
        )
        moment_res = Moment.create(
            moment_id=MomentId(self._ids.new_id()),
            family_id=command.family_id,
            spark_id=command.spark_id,
            created_by=command.author_id,
            spark_captured_at=spark.created_at,
            at=now,
            happened_on=now.date(),
            reflection=reflection_text,
            audio_media_id=command.audio_media_id,
        )
        if moment_res.is_err():
            return Err(moment_res.unwrap_err())

        moment = moment_res.unwrap()
        experienced_spark = spark.experience(now)
        if experienced_spark.is_err():
            return Err(experienced_spark.unwrap_err())

        with self._uow:
            saved_moment = self._moments.save(moment)
            if saved_moment.is_err():
                self._uow.rollback()
                return Err(saved_moment.unwrap_err())
            saved_spark = self._sparks.save(experienced_spark.unwrap())
            if saved_spark.is_err():
                self._uow.rollback()
                return Err(saved_spark.unwrap_err())

            event = DeferredQuestionAnswered(
                aggregate_id=str(moment.id),
                occurred_at=now,
                spark_id=str(spark.id),
                child_id=str(spark.subject_child_id or ""),
            )
            self._events.publish((event,), family_id=command.family_id)
            self._uow.commit()

        return Ok(moment)
