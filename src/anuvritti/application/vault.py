"""The Safe Vault (PRD 48 F5).

    "Everything captured should remain searchable ... No complex folder management."

So there is no folder tree, no tagging chore and no filing system. Retrieval works off
what the thing is, who it is for, and what the parent meant to do with it - the three
things the capture already knows. Visibility is applied before results are returned, so a
search can never become a way around the permission model (PRD 44, 45).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from anuvritti.application.ports import FamilyRepository, SparkRepository
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, SparkStatus
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId
from anuvritti.shared.result import Err, Ok, Result

DEFAULT_LIMIT: Final = 25


@dataclass(frozen=True, slots=True)
class SearchVaultQuery:
    family_id: FamilyId
    actor_id: MemberId
    text: str | None = None
    intent: IntentType | None = None
    child_id: ChildId | None = None
    age_years: int | None = None
    status: SparkStatus | None = None
    use_child_age: bool = False
    limit: int = DEFAULT_LIMIT


class SearchVaultUseCase:
    """Find the thing you half-remember saving."""

    MAX_LIMIT: Final = 100

    def __init__(
        self, *, families: FamilyRepository, sparks: SparkRepository, clock: Clock
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._clock = clock

    def execute(self, query: SearchVaultQuery) -> Result[Sequence[Spark], DomainError]:
        if query.limit < 1:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "limit must be at least 1"))

        family_result = self._families.get(query.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())
        family = family_result.unwrap()

        actor_result = family.member(query.actor_id)
        if actor_result.is_err():
            return Err(actor_result.unwrap_err())
        actor = actor_result.unwrap()

        age_years = query.age_years
        if query.use_child_age and query.child_id is not None:
            # "things for him right now" - resolve the age rather than making the caller do it.
            child_result = family.child(query.child_id)
            if child_result.is_err():
                return Err(child_result.unwrap_err())
            age_years = child_result.unwrap().age_years(self._clock.today())

        found = self._sparks.search(
            query.family_id,
            text=query.text,
            intent=query.intent,
            child_id=query.child_id,
            age_years=age_years,
            status=query.status,
            limit=min(query.limit, self.MAX_LIMIT),
        )
        if found.is_err():
            return Err(found.unwrap_err())

        # Visibility is enforced here, not in the query, so no adapter can forget it.
        return Ok([s for s in found.unwrap() if s.visibility.is_visible_to(actor.role)])
