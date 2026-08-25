"""TASK-202 - the Family aggregate.

PRD 45: a parent capturing a memory *about* a child does not automatically own that
child's story. Owner and subject are separate concepts here, and stay separate.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.values import MemberRole, Visibility
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId

TODAY = date(2026, 8, 25)


def _family() -> Family:
    return Family(
        id=FamilyId("fam-1"),
        name="Our family",
        members=(Member(MemberId("mem-papa"), "Papa", MemberRole.PARENT),),
        children=(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _child(dob: date = date(2022, 6, 1)) -> ChildProfile:
    return ChildProfile(ChildId("ch-1"), MemberId("mem-son"), "Aarav", dob)


class TestChildProfile:
    def test_age_is_computed_from_the_date_of_birth(self):
        assert _child(date(2022, 6, 1)).age_years(TODAY) == 4

    def test_age_does_not_round_up_before_the_birthday(self):
        assert _child(date(2022, 9, 1)).age_years(TODAY) == 3

    def test_age_increments_on_the_birthday_itself(self):
        assert _child(date(2022, 8, 25)).age_years(TODAY) == 4

    def test_a_newborn_is_zero(self):
        assert _child(date(2026, 8, 1)).age_years(TODAY) == 0

    def test_a_future_date_of_birth_is_rejected(self):
        with pytest.raises(ValueError, match="future"):
            ChildProfile(ChildId("ch-1"), MemberId("m"), "Unborn", date(2030, 1, 1)).age_years(
                TODAY
            )

    def test_a_blank_name_is_rejected(self):
        with pytest.raises(ValueError, match="name"):
            ChildProfile(ChildId("ch-1"), MemberId("m"), "  ", date(2022, 1, 1))

    def test_leap_day_birthdays_do_not_crash(self):
        leap_child = ChildProfile(ChildId("c"), MemberId("m"), "Leap", date(2024, 2, 29))
        assert leap_child.age_years(date(2026, 2, 28)) == 1
        assert leap_child.age_years(date(2026, 3, 1)) == 2


class TestFamilyMembership:
    def test_a_family_must_have_at_least_one_member(self):
        with pytest.raises(ValueError, match="member"):
            Family(FamilyId("f"), "Empty", (), (), datetime(2026, 1, 1, tzinfo=UTC))

    def test_finds_a_member_by_id(self):
        assert _family().member(MemberId("mem-papa")).unwrap().display_name == "Papa"

    def test_an_unknown_member_is_an_error_not_an_exception(self):
        err = _family().member(MemberId("nobody")).unwrap_err()
        assert err.code is ErrorCode.MEMBER_NOT_FOUND

    def test_adding_a_member_returns_a_new_family(self):
        original = _family()
        grown = original.with_member(Member(MemberId("mem-mum"), "Mum", MemberRole.CO_PARENT))
        assert len(grown.members) == 2
        assert len(original.members) == 1, "the aggregate must be immutable"

    def test_a_duplicate_member_id_is_rejected(self):
        err = _family().add_member(Member(MemberId("mem-papa"), "Impostor", MemberRole.PARENT))
        assert err.unwrap_err().code is ErrorCode.CONFLICT

    def test_finds_a_child_by_id(self):
        family = _family().with_child(_child())
        assert family.child(ChildId("ch-1")).unwrap().display_name == "Aarav"

    def test_an_unknown_child_is_an_error(self):
        assert _family().child(ChildId("nope")).unwrap_err().code is ErrorCode.CHILD_NOT_FOUND

    def test_a_duplicate_child_id_is_rejected(self):
        family = _family().with_child(_child())
        assert family.add_child(_child()).unwrap_err().code is ErrorCode.CONFLICT


class TestPermissions:
    def test_a_parent_may_capture_for_a_child(self):
        family = _family().with_child(_child())
        assert family.can_capture_for(MemberId("mem-papa"), ChildId("ch-1")).is_ok()

    def test_a_grandparent_may_not_capture_on_a_childs_behalf(self):
        """PRD 26/45 - contribution is not the same as guardianship."""
        family = (
            _family()
            .with_member(Member(MemberId("mem-nana"), "Nana", MemberRole.GRANDPARENT))
            .with_child(_child())
        )
        err = family.can_capture_for(MemberId("mem-nana"), ChildId("ch-1")).unwrap_err()
        assert err.code is ErrorCode.PERMISSION_DENIED

    def test_capturing_for_an_unknown_child_fails(self):
        assert (
            _family().can_capture_for(MemberId("mem-papa"), ChildId("ghost")).unwrap_err().code
            is ErrorCode.CHILD_NOT_FOUND
        )

    def test_capturing_as_an_unknown_member_fails(self):
        family = _family().with_child(_child())
        assert (
            family.can_capture_for(MemberId("stranger"), ChildId("ch-1")).unwrap_err().code
            is ErrorCode.MEMBER_NOT_FOUND
        )

    def test_a_member_may_capture_without_naming_a_child(self):
        """Not every Spark is about a child - some are for the family, or for later."""
        assert _family().can_capture_for(MemberId("mem-papa"), None).is_ok()

    def test_visibility_is_checked_against_the_members_role(self):
        family = _family().with_member(Member(MemberId("mem-kid"), "Aarav", MemberRole.CHILD))
        assert family.can_view(MemberId("mem-papa"), Visibility.PRIVATE).is_ok()
        assert family.can_view(MemberId("mem-kid"), Visibility.PRIVATE).is_err()
        assert family.can_view(MemberId("mem-kid"), Visibility.CHILD_VISIBLE).is_ok()

    def test_viewing_as_an_unknown_member_is_denied(self):
        assert (
            _family().can_view(MemberId("stranger"), Visibility.FAMILY).unwrap_err().code
            is ErrorCode.MEMBER_NOT_FOUND
        )


class TestChildDataRights:
    def test_a_child_profile_is_linked_to_its_own_member_identity(self):
        """PRD 45 - the child is a person in the model from day one, not a row on a parent."""
        assert _child().member_id == MemberId("mem-son")

    def test_the_owner_of_a_capture_is_never_implicitly_the_subject(self):
        family = _family().with_child(_child())
        child_profile = family.child(ChildId("ch-1")).unwrap()
        assert child_profile.member_id != MemberId("mem-papa")
