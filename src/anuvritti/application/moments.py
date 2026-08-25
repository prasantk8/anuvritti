"""Mark As Done - a Spark becomes a Moment (PRD 15, 48 F7).

    "Did this happen?"  ->  one photo, five seconds of audio, one sentence, or nothing.

This is the use case the entire product is measured by (PRD 53: Intent -> Moment
conversion). It must therefore be the easiest thing in the system to complete, which is
why every attachment is optional and "nothing" is an accepted answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from anuvritti.application.ports import (
    EventPublisher,
    MomentRepository,
    SparkRepository,
    UnitOfWork,
)
from anuvritti.domain.moment import Moment
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import IdGenerator, MemberId, MomentId, SparkId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class MarkAsDoneCommand:
    spark_id: SparkId
    created_by: MemberId
    happened_on: date | None = None
    reflection: str | None = None
    photo_media_id: str | None = None
    audio_media_id: str | None = None


class MarkAsDoneUseCase:
    """It happened. Record it with as little ceremony as possible."""

    def __init__(
        self,
        *,
        sparks: SparkRepository,
        moments: MomentRepository,
        events: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
        uow: UnitOfWork,
    ) -> None:
        self._sparks = sparks
        self._moments = moments
        self._events = events
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def execute(self, command: MarkAsDoneCommand) -> Result[Moment, DomainError]:
        found = self._sparks.get(command.spark_id)
        if found.is_err():
            return Err(found.unwrap_err())
        spark = found.unwrap()

        existing = self._moments.find_by_spark(command.spark_id)
        if existing.is_err():
            return Err(existing.unwrap_err())
        if existing.unwrap() is not None:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "this spark already became a moment",
                    {"spark_id": str(command.spark_id)},
                )
            )

        now = self._clock.now()
        experienced = spark.experience(now)
        if experienced.is_err():
            return Err(experienced.unwrap_err())
        spark = experienced.unwrap()

        moment_result = Moment.create(
            moment_id=MomentId(self._ids.new_id()),
            family_id=spark.family_id,
            spark_id=spark.id,
            created_by=command.created_by,
            spark_captured_at=spark.created_at,
            at=now,
            happened_on=command.happened_on,
            reflection=command.reflection,
            photo_media_id=command.photo_media_id,
            audio_media_id=command.audio_media_id,
        )
        if moment_result.is_err():
            return Err(moment_result.unwrap_err())
        moment = moment_result.unwrap()

        with self._uow:
            saved_spark = self._sparks.save(spark)
            if saved_spark.is_err():
                self._uow.rollback()
                return Err(saved_spark.unwrap_err())
            saved_moment = self._moments.save(moment)
            if saved_moment.is_err():
                self._uow.rollback()
                return Err(saved_moment.unwrap_err())
            self._events.publish(
                (*spark.pending_events, *moment.pending_events), family_id=spark.family_id
            )
            self._uow.commit()
        return Ok(moment)
