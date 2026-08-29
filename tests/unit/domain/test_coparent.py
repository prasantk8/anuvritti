"""TASK-902 - Co-parent: a second adult with equal standing, not a guest account (PRD 26, PRD 51).

Tests verifying that CO_PARENT holds equal standing and identical administrative and
archival rights as PARENT.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.values import MemberRole, Visibility
from anuvritti.shared.identity import ChildId, FamilyId, MemberId


@pytest.fixture
def family():
    papa_id = MemberId("mem-papa")
    mama_id = MemberId("mem-mama")
    grandma_id = MemberId("mem-grandma")
    child_id = ChildId("child-leo")

    return Family(
        id=FamilyId("fam-001"),
        name="The Family",
        members=(
            Member(papa_id, "Papa", MemberRole.PARENT),
            Member(mama_id, "Mama", MemberRole.CO_PARENT),
            Member(grandma_id, "Grandma", MemberRole.GRANDPARENT),
        ),
        children=(ChildProfile(child_id, papa_id, "Leo", date(2022, 5, 14)),),
        created_at=datetime(2022, 5, 14, 10, 0, tzinfo=UTC),
    )


def test_coparent_and_parent_have_identical_role_capabilities():
    parent_role = MemberRole.PARENT
    coparent_role = MemberRole.CO_PARENT

    assert parent_role.is_parent is True
    assert coparent_role.is_parent is True

    assert parent_role.can_capture_for_child is True
    assert coparent_role.can_capture_for_child is True

    assert parent_role.can_administer is True
    assert coparent_role.can_administer is True


def test_coparent_has_full_capture_standing_for_child(family):
    mama_id = MemberId("mem-mama")
    child_id = ChildId("child-leo")

    # Co-parent can capture for child
    res = family.can_capture_for(mama_id, child_id)
    assert res.is_ok()


def test_coparent_has_full_administrative_and_film_compilation_standing(family):
    papa_id = MemberId("mem-papa")
    mama_id = MemberId("mem-mama")
    grandma_id = MemberId("mem-grandma")

    # Both Papa (PARENT) and Mama (CO_PARENT) hold administrative standing
    assert family.can_administer(papa_id).is_ok()
    assert family.can_administer(mama_id).is_ok()

    # Both Papa and Mama can compile commemorative films
    assert family.can_compile_film(papa_id).is_ok()
    assert family.can_compile_film(mama_id).is_ok()

    # Grandparents and children do not hold parental administration standing
    assert family.can_administer(grandma_id).is_err()
    assert family.can_administer(grandma_id).unwrap_err().code.value == "PERMISSION_DENIED"


def test_coparent_and_parent_see_all_visibilities_identically(family):
    papa_id = MemberId("mem-papa")
    mama_id = MemberId("mem-mama")
    grandma_id = MemberId("mem-grandma")

    for vis in (Visibility.PRIVATE, Visibility.FAMILY, Visibility.CHILD_VISIBLE):
        assert family.can_view(papa_id, vis).is_ok()
        assert family.can_view(mama_id, vis).is_ok()

    # Grandparent cannot see PRIVATE content
    assert family.can_view(grandma_id, Visibility.PRIVATE).is_err()
    # Grandparent CAN see FAMILY and CHILD_VISIBLE content
    assert family.can_view(grandma_id, Visibility.FAMILY).is_ok()
    assert family.can_view(grandma_id, Visibility.CHILD_VISIBLE).is_ok()
