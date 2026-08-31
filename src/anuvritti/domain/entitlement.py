"""Entitlements & Archive Invariants (TASK-1403, PRD 57, PRD 47, PRD 45).

"If a family stops paying, the archive stays readable and exportable forever."

No financial transaction or subscription lifecycle event may ever revoke a family's ability
to access, search, download, or export their memories. Entitlements only regulate new capture
capacity and compute-intensive rendering beyond the free tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from anuvritti.shared.identity import FamilyId, MemberId


class EntitlementStatus(StrEnum):
    ACTIVE = "active"
    TRIAL = "trial"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"


class EntitlementPlan(StrEnum):
    FREE = "free"
    ANNUAL_ARCHIVE = "annual_archive"
    LIFETIME_LEGACY = "lifetime_legacy"
    GIFTED_MEMBERSHIP = "gifted_membership"


DEFAULT_FREE_SPARK_LIMIT: Final = 500


@dataclass(frozen=True, slots=True)
class FamilyEntitlement:
    """The subscription and feature entitlement state for a family.

    CONSTITUTIONAL INVARIANT:
    `can_read`, `can_search`, `can_export`, and `can_verify_fixity` ALWAYS return True,
    regardless of subscription status, billing failures, or account age.
    """

    family_id: FamilyId
    plan: EntitlementPlan = EntitlementPlan.FREE
    status: EntitlementStatus = EntitlementStatus.ACTIVE
    expires_at: datetime | None = None
    sponsor_id: MemberId | str | None = None
    max_sparks: int | None = DEFAULT_FREE_SPARK_LIMIT

    @property
    def can_read(self) -> bool:
        """PRD 57: What was already saved is never held hostage."""
        return True

    @property
    def can_search(self) -> bool:
        """Search is a core retrieval capability for already-saved data."""
        return True

    @property
    def can_export(self) -> bool:
        """PRD 47: Export is an absolute constitutional right."""
        return True

    @property
    def can_verify_fixity(self) -> bool:
        """Fixity and integrity proofs are always available."""
        return True

    def can_capture_new_spark(self, current_spark_count: int) -> bool:
        """Whether the family can capture additional new sparks."""
        if self.plan in (
            EntitlementPlan.ANNUAL_ARCHIVE,
            EntitlementPlan.LIFETIME_LEGACY,
            EntitlementPlan.GIFTED_MEMBERSHIP,
        ) and self.status in (EntitlementStatus.ACTIVE, EntitlementStatus.TRIAL):
            return True
        if self.max_sparks is None:
            return True
        return current_spark_count < self.max_sparks

    def can_compile_full_films(self) -> bool:
        """Full multi-year film compilation entitlement."""
        return self.plan in (
            EntitlementPlan.ANNUAL_ARCHIVE,
            EntitlementPlan.LIFETIME_LEGACY,
            EntitlementPlan.GIFTED_MEMBERSHIP,
        ) and self.status in (EntitlementStatus.ACTIVE, EntitlementStatus.TRIAL)
