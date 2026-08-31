"""TASK-1403 - Entitlements where nothing already saved is ever held hostage.

PRD 57, PRD 47, PRD 45.

"If a family stops paying, the archive stays readable and exportable forever."
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.domain.entitlement import (
    EntitlementPlan,
    EntitlementStatus,
    FamilyEntitlement,
)
from anuvritti.shared.identity import FamilyId, MemberId


@pytest.mark.parametrize(
    "status",
    [
        EntitlementStatus.ACTIVE,
        EntitlementStatus.EXPIRED,
        EntitlementStatus.CANCELLED,
        EntitlementStatus.PAST_DUE,
        EntitlementStatus.TRIAL,
    ],
)
@pytest.mark.parametrize(
    "plan",
    [
        EntitlementPlan.FREE,
        EntitlementPlan.ANNUAL_ARCHIVE,
        EntitlementPlan.LIFETIME_LEGACY,
        EntitlementPlan.GIFTED_MEMBERSHIP,
    ],
)
def test_memories_are_never_held_hostage_regardless_of_plan_or_status(
    plan: EntitlementPlan, status: EntitlementStatus
) -> None:
    """An archive can ALWAYS be read, searched, exported, and fixity-checked."""
    entitlement = FamilyEntitlement(
        family_id=FamilyId("fam-123"),
        plan=plan,
        status=status,
        expires_at=datetime.now(UTC),
    )

    # Core non-negotiable rights
    assert entitlement.can_read is True
    assert entitlement.can_search is True
    assert entitlement.can_export is True
    assert entitlement.can_verify_fixity is True


def test_free_tier_limits_only_new_capture_not_existing_memories() -> None:
    entitlement = FamilyEntitlement(
        family_id=FamilyId("fam-123"),
        plan=EntitlementPlan.FREE,
        status=EntitlementStatus.ACTIVE,
        max_sparks=100,
    )

    assert entitlement.can_capture_new_spark(current_spark_count=50) is True
    assert entitlement.can_capture_new_spark(current_spark_count=100) is False
    assert entitlement.can_capture_new_spark(current_spark_count=150) is False

    # Read and export are NEVER degraded
    assert entitlement.can_read is True
    assert entitlement.can_export is True


def test_gifted_membership_preserves_rights_for_family() -> None:
    entitlement = FamilyEntitlement(
        family_id=FamilyId("fam-123"),
        plan=EntitlementPlan.GIFTED_MEMBERSHIP,
        status=EntitlementStatus.ACTIVE,
        sponsor_id=MemberId("grandparent-456"),
    )

    assert entitlement.can_capture_new_spark(1000) is True
    assert entitlement.can_compile_full_films() is True
    assert entitlement.sponsor_id == MemberId("grandparent-456")
