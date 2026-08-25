"""Worth Bringing Back (PRD 14, 48 F6).

    "Saving is not the core value. Returning is."

Two use cases: ask what may have become relevant, and answer. The answers are exactly the
three the PRD names - maybe later, let's do it, not relevant anymore - and each one is
honoured literally. "Maybe later" buys real quiet; "not relevant anymore" is permanent.
A product that keeps asking after being told no is the product PRD 8.5 forbids.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    SparkRepository,
    UnitOfWork,
)
from anuvritti.domain.return_engine import ReturnContext, ReturnEngine, Suggestion
from anuvritti.domain.spark import Spark
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId
from anuvritti.shared.result import Err, Ok, Result


class SuggestionResponse(StrEnum):
    """The only three answers. There is deliberately no "remind me tomorrow"."""

    MAYBE_LATER = "maybe_later"
    LETS_DO_IT = "lets_do_it"
    NOT_RELEVANT_ANYMORE = "not_relevant_anymore"


@dataclass(frozen=True, slots=True)
class WorthBringingBackQuery:
    family_id: FamilyId
    actor_id: MemberId
    child_id: ChildId | None = None


class GetWorthBringingBackUseCase:
    """Ask what may have become relevant. Returning nothing is a good answer."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        engine: ReturnEngine,
        events: EventPublisher,
        clock: Clock,
        uow: UnitOfWork,
        max_suggestions_per_day: int = 3,
        threshold: float = 0.45,
        maturation_horizon_days: int = 180,
        min_days_before_return: int = 7,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._engine = engine
        self._events = events
        self._clock = clock
        self._uow = uow
        self._max = max_suggestions_per_day
        self._threshold = threshold
        self._horizon = maturation_horizon_days
        self._min_days = min_days_before_return

    def execute(self, query: WorthBringingBackQuery) -> Result[Sequence[Suggestion], DomainError]:
        family_result = self._families.get(query.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())
        family = family_result.unwrap()

        actor_result = family.member(query.actor_id)
        if actor_result.is_err():
            return Err(actor_result.unwrap_err())
        actor = actor_result.unwrap()

        today = self._clock.today()
        context = ReturnContext(
            now=self._clock.now(),
            child_ages={str(c.id): c.age_years(today) for c in family.children},
            child_names={str(c.id): c.display_name for c in family.children},
            max_suggestions=self._max,
            threshold=self._threshold,
            maturation_horizon_days=self._horizon,
            min_days_before_return=self._min_days,
        )

        candidates = self._sparks.list_returnable(query.family_id)
        if candidates.is_err():
            return Err(candidates.unwrap_err())

        eligible = [
            spark
            for spark in candidates.unwrap()
            if spark.visibility.is_visible_to(actor.role)
            and (query.child_id is None or spark.subject_child_id == query.child_id)
        ]

        suggestions = self._engine.select(eligible, context)

        # Surfacing is a state change: it is what makes the novelty decay real, and what
        # keeps the anti-metric in PRD 53 (notification volume) countable.
        with self._uow:
            for suggestion in suggestions:
                marked = suggestion.spark.mark_suggested(
                    context.now, score=suggestion.score, reason_key=suggestion.reason_key
                )
                if marked.is_err():  # pragma: no cover - engine filters these already
                    continue
                spark = marked.unwrap()
                saved = self._sparks.save(spark)
                if saved.is_err():
                    self._uow.rollback()
                    return Err(saved.unwrap_err())
                self._events.publish(spark.pending_events, family_id=query.family_id)
            self._uow.commit()

        return Ok(suggestions)


@dataclass(frozen=True, slots=True)
class RespondToSuggestionCommand:
    spark_id: SparkId
    response: SuggestionResponse


class RespondToSuggestionUseCase:
    """Take the answer literally. That is the whole feature."""

    def __init__(
        self,
        *,
        sparks: SparkRepository,
        events: EventPublisher,
        clock: Clock,
        uow: UnitOfWork,
        snooze_cooldown_days: int = 30,
    ) -> None:
        self._sparks = sparks
        self._events = events
        self._clock = clock
        self._uow = uow
        self._cooldown = snooze_cooldown_days

    def execute(self, command: RespondToSuggestionCommand) -> Result[Spark, DomainError]:
        found = self._sparks.get(command.spark_id)
        if found.is_err():
            return Err(found.unwrap_err())
        spark = found.unwrap()

        match command.response:
            case SuggestionResponse.MAYBE_LATER:
                # Real quiet, not a snooze button. PRD 8.5.
                updated = spark.snooze(until=self._clock.now() + timedelta(days=self._cooldown))
            case SuggestionResponse.LETS_DO_IT:
                updated = spark.plan()
            case SuggestionResponse.NOT_RELEVANT_ANYMORE:
                updated = spark.archive()

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
