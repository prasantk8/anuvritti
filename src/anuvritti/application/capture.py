"""Universal Capture (PRD 11, 12, 48 F1-F3).

    Share -> Anuvritti -> "Saved."

The design constraint that shapes this module is the ten-second target in PRD 11. Nothing
here may block on a form, and nothing may fail because the person did not answer a
question. AI understanding runs inline only because the V0 engine is local and instant;
the moment that stops being true it moves behind an event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    IntentEngine,
    SparkRepository,
    UnitOfWork,
)
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import AgeRange, IntentType, SourceRef, Visibility
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, IdGenerator, MemberId, SparkId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class CaptureSparkCommand:
    family_id: FamilyId
    owner_id: MemberId
    source: SourceRef
    subject_child_id: ChildId | None = None
    note: str | None = None
    visibility: Visibility | None = None


class CaptureSparkUseCase:
    """Turn a share into a Spark that already understands something about itself."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        intent_engine: IntentEngine,
        events: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._intent_engine = intent_engine
        self._events = events
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def execute(self, command: CaptureSparkCommand) -> Result[Spark, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())

        permitted = family_result.unwrap().can_capture_for(
            command.owner_id, command.subject_child_id
        )
        if permitted.is_err():
            return Err(permitted.unwrap_err())

        now = self._clock.now()
        spark = Spark.capture(
            spark_id=SparkId(self._ids.new_id()),
            family_id=command.family_id,
            owner_id=command.owner_id,
            subject_child_id=command.subject_child_id,
            source=command.source,
            note=command.note,
            visibility=command.visibility,
            at=now,
        )

        # PRD 48 F2 - lightweight understanding, applied immediately so the Spark is
        # searchable and returnable from the second it exists.
        spark = spark.apply_inference(self._intent_engine.infer(command.source, note=command.note))

        with self._uow:
            saved = self._sparks.save(spark)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(spark.pending_events, family_id=command.family_id)
            self._uow.commit()
        return Ok(spark)


@dataclass(frozen=True, slots=True)
class RecordWhyCommand:
    spark_id: SparkId
    text: str | None = None
    voice_media_id: str | None = None


class RecordWhyUseCase:
    """PRD 12 - the "why" layer.

    "Toy -> Age 3" is metadata. "I never had something like this growing up and would've
    loved it" is the thing worth keeping. Both are optional; only one is irreplaceable.
    """

    def __init__(
        self,
        *,
        sparks: SparkRepository,
        events: EventPublisher,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._sparks = sparks
        self._events = events
        self._clock = clock
        self._uow = uow

    def execute(self, command: RecordWhyCommand) -> Result[Spark, DomainError]:
        found = self._sparks.get(command.spark_id)
        if found.is_err():
            return Err(found.unwrap_err())

        updated = found.unwrap().record_why(
            text=command.text,
            voice_media_id=command.voice_media_id,
            at=self._clock.now(),
        )
        if updated.is_err():
            return Err(updated.unwrap_err())

        return self._persist(updated.unwrap())

    def _persist(self, spark: Spark) -> Result[Spark, DomainError]:
        with self._uow:
            saved = self._sparks.save(spark)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(spark.pending_events, family_id=spark.family_id)
            self._uow.commit()
        return Ok(spark)


@dataclass(frozen=True, slots=True)
class OverrideFieldCommand:
    spark_id: SparkId
    field: str
    value: Any


class OverrideFieldUseCase:
    """PRD 13 - a human correction is final and is never re-inferred."""

    OVERRIDABLE = ("intent", "age_range", "category")

    def __init__(self, *, sparks: SparkRepository, events: EventPublisher, uow: UnitOfWork) -> None:
        self._sparks = sparks
        self._events = events
        self._uow = uow

    def execute(self, command: OverrideFieldCommand) -> Result[Spark, DomainError]:
        found = self._sparks.get(command.spark_id)
        if found.is_err():
            return Err(found.unwrap_err())
        spark = found.unwrap()

        match command.field:
            case "intent":
                if not isinstance(command.value, IntentType):
                    return self._bad_value("intent", "an IntentType")
                updated = spark.override_intent(command.value)
            case "age_range":
                if not isinstance(command.value, AgeRange):
                    return self._bad_value("age_range", "an AgeRange")
                updated = spark.override_age_range(command.value)
            case "category":
                if not isinstance(command.value, str):
                    return self._bad_value("category", "a string")
                updated = spark.override_category(command.value)
            case _:
                return Err(
                    DomainError(
                        ErrorCode.VALIDATION_FAILED,
                        f"{command.field!r} is not an overridable field",
                        {"overridable": list(self.OVERRIDABLE)},
                    )
                )

        if updated.is_err():
            return Err(updated.unwrap_err())

        spark = updated.unwrap()
        with self._uow:
            saved = self._sparks.save(spark)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(spark.pending_events, family_id=spark.family_id)
            self._uow.commit()
        return Ok(spark)

    def _bad_value(self, field: str, expected: str) -> Err[DomainError]:
        return Err(
            DomainError(
                ErrorCode.VALIDATION_FAILED, f"{field} must be {expected}", {"field": field}
            )
        )
