"""Domain aggregates for Sealed Capsules (TASK-813, PRD 35, PRD 8.5, PRD 8.8).

Two kinds of capsules:
1. Age N Capsule: letters, grandparent messages, year film sealed until a birthday.
2. The Unfinished: Sparks with a recorded why and no Moment, addressed to the child
   at an age the parent chooses, narrated only by those whys.

Crucially: The parent sees "sealed" and never a list of tasks or debts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from anuvritti.domain.events import DomainEvent
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId
from anuvritti.shared.result import Err, Ok, Result


class CapsuleKind(StrEnum):
    AGE_N = "AGE_N"
    THE_UNFINISHED = "THE_UNFINISHED"


class CapsuleStatus(StrEnum):
    SEALED = "SEALED"
    OPENED = "OPENED"


@dataclass(frozen=True, slots=True)
class CapsuleItem:
    item_id: str
    title: str
    why: str | None = None
    media_id: str | None = None


@dataclass(frozen=True, slots=True)
class CapsuleSealed(DomainEvent):
    family_id: str
    child_id: str
    capsule_id: str
    kind: str
    target_age_years: int

    def payload(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "child_id": self.child_id,
            "capsule_id": self.capsule_id,
            "kind": self.kind,
            "target_age_years": self.target_age_years,
        }


@dataclass(frozen=True, slots=True)
class Capsule:
    id: str
    family_id: FamilyId
    child_id: ChildId
    author_id: MemberId
    kind: CapsuleKind
    target_age_years: int
    sealed_at: datetime
    items: tuple[CapsuleItem, ...]
    status: CapsuleStatus = CapsuleStatus.SEALED
    pending_events: tuple[DomainEvent, ...] = ()

    @classmethod
    def seal(
        cls,
        *,
        capsule_id: str,
        family_id: FamilyId,
        child_id: ChildId,
        author_id: MemberId,
        kind: CapsuleKind,
        target_age_years: int,
        items: tuple[CapsuleItem, ...],
        at: datetime,
    ) -> Result[Capsule, DomainError]:
        if target_age_years < 1:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "target age must be positive"))
        if not items:
            return Err(
                DomainError(ErrorCode.VALIDATION_FAILED, "a capsule must contain at least one item")
            )

        return Ok(
            cls(
                id=capsule_id,
                family_id=family_id,
                child_id=child_id,
                author_id=author_id,
                kind=kind,
                target_age_years=target_age_years,
                sealed_at=at,
                items=items,
                status=CapsuleStatus.SEALED,
                pending_events=(
                    CapsuleSealed(
                        aggregate_id=capsule_id,
                        occurred_at=at,
                        family_id=str(family_id),
                        child_id=str(child_id),
                        capsule_id=capsule_id,
                        kind=kind.value,
                        target_age_years=target_age_years,
                    ),
                ),
            )
        )

    @property
    def parent_view(self) -> str:
        """What the parent sees: 'Sealed for age N' — never an unlived task list."""
        return f"Sealed until age {self.target_age_years}"
