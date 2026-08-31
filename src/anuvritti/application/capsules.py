"""Sealed Capsules Application Services (TASK-813, PRD 35, PRD 8.5, PRD 8.8)."""

from __future__ import annotations

from dataclasses import dataclass

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    SparkRepository,
    UnitOfWork,
)
from anuvritti.domain.capsule import (
    Capsule,
    CapsuleItem,
    CapsuleKind,
)
from anuvritti.domain.values import SparkStatus
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, IdGenerator, MemberId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class SealAgeNCapsuleCommand:
    family_id: FamilyId
    child_id: ChildId
    author_id: MemberId
    target_age_years: int
    items: tuple[CapsuleItem, ...]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SealTheUnfinishedCommand:
    family_id: FamilyId
    child_id: ChildId
    author_id: MemberId
    target_age_years: int = 18
    note: str | None = None


SealUnfinishedCapsuleCommand = SealTheUnfinishedCommand


class CapsuleUseCase:
    """Orchestrates sealing age-based and unfinished capsules."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher | None = None,
        uow: UnitOfWork | None = None,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._clock = clock
        self._ids = ids
        self._events = events
        self._uow = uow
        self._capsules: dict[str, Capsule] = {}

    def seal_age_n_capsule(self, command: SealAgeNCapsuleCommand) -> Result[Capsule, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        now = self._clock.now()
        capsule_id = self._ids.new_id()
        capsule_res = Capsule.seal(
            capsule_id=capsule_id,
            family_id=command.family_id,
            child_id=command.child_id,
            author_id=command.author_id,
            kind=CapsuleKind.AGE_N,
            target_age_years=command.target_age_years,
            items=command.items,
            at=now,
        )
        if capsule_res.is_err():
            return capsule_res

        capsule = capsule_res.unwrap()
        self._capsules[capsule.id] = capsule
        if self._events:
            self._events.publish(capsule.pending_events, family_id=command.family_id)
        return Ok(capsule)

    def seal_the_unfinished(
        self, command: SealTheUnfinishedCommand
    ) -> Result[Capsule, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        sparks_res = self._sparks.list_for_family(command.family_id)
        if sparks_res.is_err():
            return Err(sparks_res.unwrap_err())

        # Compile only sparks with a recorded why and no moment (unlived)
        items: list[CapsuleItem] = []
        for spark in sparks_res.unwrap():
            if spark.subject_child_id != command.child_id:
                continue
            if spark.status.is_lived or spark.status is SparkStatus.ARCHIVED:
                continue
            if spark.why is None or (not spark.why.text and not spark.why.voice_media_id):
                continue

            why_text = spark.why.text if spark.why.text else "Spoken why"
            items.append(
                CapsuleItem(
                    item_id=str(spark.id),
                    title=spark.title,
                    why=why_text,
                    media_id=str(spark.why.voice_media_id) if spark.why.voice_media_id else None,
                )
            )

        if not items:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "No unlived sparks with recorded whys found to compile",
                )
            )

        now = self._clock.now()
        capsule_id = self._ids.new_id()
        capsule_res = Capsule.seal(
            capsule_id=capsule_id,
            family_id=command.family_id,
            child_id=command.child_id,
            author_id=command.author_id,
            kind=CapsuleKind.THE_UNFINISHED,
            target_age_years=command.target_age_years,
            items=tuple(items),
            at=now,
        )
        if capsule_res.is_err():
            return capsule_res

        capsule = capsule_res.unwrap()
        self._capsules[capsule.id] = capsule
        if self._events:
            self._events.publish(capsule.pending_events, family_id=command.family_id)
        return Ok(capsule)

    def list_capsules_for_child(
        self, family_id: FamilyId, child_id: ChildId
    ) -> Result[list[Capsule], DomainError]:
        found = [
            cap
            for cap in self._capsules.values()
            if cap.family_id == family_id and cap.child_id == child_id
        ]
        return Ok(found)
