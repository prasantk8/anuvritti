"""TASK-1404 - Integration test for the Gift Path.

PRD 57, PRD 27, PRD 45.
"""

from __future__ import annotations

from datetime import UTC, datetime

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteFamilyRepository
from anuvritti.application.billing import GiftSubscriptionCommand, GiftSubscriptionUseCase
from anuvritti.domain.entitlement import EntitlementPlan, EntitlementStatus
from anuvritti.domain.family import Family, Member
from anuvritti.domain.values import MemberRole
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import FamilyId, MemberId


def test_grandparent_can_gift_subscription_without_gaining_ownership() -> None:
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    conn = connect(":memory:")
    migrate(conn)
    families = SqliteFamilyRepository(conn)

    family_id = FamilyId("fam-gift-1")
    parent_id = MemberId("parent-1")
    grandparent_id = MemberId("gp-1")

    family = Family(
        id=family_id,
        name="The Bhatts",
        members=(Member(id=parent_id, role=MemberRole.PARENT, display_name="Aarav's Papa"),),
        children=(),
        created_at=now,
    )
    families.save(family)

    use_case = GiftSubscriptionUseCase(families=families, clock=clock)

    # Initial state is free
    initial_entitlement = use_case.get_entitlement(family_id)
    assert initial_entitlement.plan == EntitlementPlan.FREE

    # Grandparent gifts 12 months of archive storage
    cmd = GiftSubscriptionCommand(
        family_id=family_id,
        sponsor_id=grandparent_id,
        sponsor_email="dada@example.com",
        plan=EntitlementPlan.GIFTED_MEMBERSHIP,
        duration_months=12,
    )

    res = use_case.execute(cmd)
    assert res.is_ok()
    entitlement = res.unwrap()

    assert entitlement.plan == EntitlementPlan.GIFTED_MEMBERSHIP
    assert entitlement.status == EntitlementStatus.ACTIVE
    assert entitlement.sponsor_id == grandparent_id
    assert entitlement.can_capture_new_spark(1000) is True
    assert entitlement.can_compile_full_films() is True
    assert entitlement.can_read is True
    assert entitlement.can_export is True

    # Crucial security assertion: Family membership did not change
    reloaded_family = families.get(family_id).unwrap()
    member_ids = [m.id for m in reloaded_family.members]
    assert grandparent_id not in member_ids
