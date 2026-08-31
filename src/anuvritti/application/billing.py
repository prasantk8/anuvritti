"""Billing & Gifting Use Case (TASK-1404, PRD 57, PRD 27, PRD 45).

"A grandparent can pay for the legacy archive without becoming the owner of the child's record."

Financial sponsorship never confers administrative ownership, visibility rights, or editorial
control over a family's private moments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from anuvritti.application.ports import FamilyRepository
from anuvritti.domain.entitlement import (
    EntitlementPlan,
    EntitlementStatus,
    FamilyEntitlement,
)
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class GiftSubscriptionCommand:
    family_id: FamilyId
    sponsor_id: MemberId
    sponsor_email: str
    plan: EntitlementPlan = EntitlementPlan.GIFTED_MEMBERSHIP
    duration_months: int = 12


class GiftSubscriptionUseCase:
    """Enables grandparents or sponsors to gift legacy archive storage."""

    def __init__(self, *, families: FamilyRepository, clock: Clock) -> None:
        self._families = families
        self._clock = clock
        self._entitlements: dict[FamilyId, FamilyEntitlement] = {}

    def get_entitlement(self, family_id: FamilyId) -> FamilyEntitlement:
        return self._entitlements.get(
            family_id,
            FamilyEntitlement(family_id=family_id, plan=EntitlementPlan.FREE),
        )

    def execute(self, command: GiftSubscriptionCommand) -> Result[FamilyEntitlement, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        family = family_res.unwrap()

        # Sponsor email must be non-empty
        if not command.sponsor_email or "@" not in command.sponsor_email:
            return Err(
                DomainError(ErrorCode.VALIDATION_FAILED, "a valid sponsor email is required")
            )

        now = self._clock.now()
        expires_at = now + timedelta(days=30 * command.duration_months)

        entitlement = FamilyEntitlement(
            family_id=family.id,
            plan=command.plan,
            status=EntitlementStatus.ACTIVE,
            expires_at=expires_at,
            sponsor_id=command.sponsor_id,
            max_sparks=None,  # Unlimited capture
        )

        self._entitlements[family.id] = entitlement
        return Ok(entitlement)
