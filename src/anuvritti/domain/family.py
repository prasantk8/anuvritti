"""The Family aggregate.

PRD 45 draws a line this module is responsible for holding: the person who captured
something and the person it is *about* are different people, with different rights.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from anuvritti.domain.values import MemberRole, Visibility
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class Member:
    """Someone who participates in the family archive."""

    id: MemberId
    display_name: str
    role: MemberRole

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("member display_name cannot be blank")


@dataclass(frozen=True, slots=True)
class ChildProfile:
    """A child, modelled as a person with their own identity (PRD 45)."""

    id: ChildId
    member_id: MemberId
    display_name: str
    date_of_birth: date

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("child display_name cannot be blank")

    def age_years(self, on: date) -> int:
        """Completed years of life on the given date."""
        if self.date_of_birth > on:
            raise ValueError("date_of_birth is in the future")
        had_birthday = (on.month, on.day) >= (self.date_of_birth.month, self.date_of_birth.day)
        return on.year - self.date_of_birth.year - (0 if had_birthday else 1)


@dataclass(frozen=True, slots=True)
class Family:
    """The aggregate root for membership, children and access decisions."""

    id: FamilyId
    name: str
    members: tuple[Member, ...]
    children: tuple[ChildProfile, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError("a family must have at least one member")

    # ---------------------------------------------------------------- lookup
    def member(self, member_id: MemberId) -> Result[Member, DomainError]:
        for candidate in self.members:
            if candidate.id == member_id:
                return Ok(candidate)
        return Err(DomainError(ErrorCode.MEMBER_NOT_FOUND, f"no member {member_id}"))

    def child(self, child_id: ChildId) -> Result[ChildProfile, DomainError]:
        for candidate in self.children:
            if candidate.id == child_id:
                return Ok(candidate)
        return Err(DomainError(ErrorCode.CHILD_NOT_FOUND, f"no child {child_id}"))

    # ---------------------------------------------------------------- growth
    def add_member(self, member: Member) -> Result[Family, DomainError]:
        if self.member(member.id).is_ok():
            return Err(DomainError(ErrorCode.CONFLICT, f"member {member.id} already exists"))
        return Ok(self.with_member(member))

    def with_member(self, member: Member) -> Family:
        return replace(self, members=(*self.members, member))

    def add_child(self, child: ChildProfile) -> Result[Family, DomainError]:
        if self.child(child.id).is_ok():
            return Err(DomainError(ErrorCode.CONFLICT, f"child {child.id} already exists"))
        return Ok(self.with_child(child))

    def with_child(self, child: ChildProfile) -> Family:
        return replace(self, children=(*self.children, child))

    # ----------------------------------------------------------- permissions
    def can_capture_for(
        self, member_id: MemberId, child_id: ChildId | None
    ) -> Result[None, DomainError]:
        """May this member save something on this child's behalf? (PRD 26, 45)"""
        member_result = self.member(member_id)
        if member_result.is_err():
            return Err(member_result.unwrap_err())
        if child_id is None:
            return Ok(None)
        child_result = self.child(child_id)
        if child_result.is_err():
            return Err(child_result.unwrap_err())
        if not member_result.unwrap().role.can_capture_for_child:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    f"role {member_result.unwrap().role} may not capture for a child",
                    {"member_id": str(member_id), "child_id": str(child_id)},
                )
            )
        return Ok(None)

    def can_view(self, member_id: MemberId, visibility: Visibility) -> Result[None, DomainError]:
        member_result = self.member(member_id)
        if member_result.is_err():
            return Err(member_result.unwrap_err())
        if not visibility.is_visible_to(member_result.unwrap().role):
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    f"{visibility} content is not visible to {member_result.unwrap().role}",
                )
            )
        return Ok(None)

    def can_administer(self, member_id: MemberId) -> Result[None, DomainError]:
        """Equal standing check for parents and co-parents (PRD 26, PRD 51)."""
        member_result = self.member(member_id)
        if member_result.is_err():
            return Err(member_result.unwrap_err())
        if not member_result.unwrap().role.can_administer:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    f"role {member_result.unwrap().role} does not have parental "
                    "administrative standing",
                    {"member_id": str(member_id)},
                )
            )
        return Ok(None)

    def can_compile_film(self, member_id: MemberId) -> Result[None, DomainError]:
        """Parents and co-parents hold equal authority to compile commemorative films."""
        return self.can_administer(member_id)
