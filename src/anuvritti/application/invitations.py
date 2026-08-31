"""Family Invitations (TASK-1402, PRD 26, PRD 27, PRD 51).

"A co-parent or grandparent joins by receiving something worth having, not by being asked
to create an account first."

Invitations carry a warm entry gift (e.g. an authentic spark or personal prompt) rather than
a bare registration form.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from anuvritti.application.ports import FamilyRepository, SparkRepository, UnitOfWork
from anuvritti.domain.family import Family, Member
from anuvritti.domain.values import MemberRole
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId, SparkId
from anuvritti.shared.result import Err, Ok, Result

DEFAULT_INVITATION_TTL_DAYS: Final = 14


@dataclass(frozen=True, slots=True)
class Invitation:
    """An issued token allowing an adult or grandparent to join a family."""

    token: str
    family_id: FamilyId
    inviter_id: MemberId
    invitee_name: str
    invitee_role: MemberRole
    created_at: datetime
    expires_at: datetime
    initial_spark_id: SparkId | None = None
    welcome_message: str | None = None


@dataclass(frozen=True, slots=True)
class CreateInvitationCommand:
    family_id: FamilyId
    inviter_id: MemberId
    invitee_name: str
    invitee_role: MemberRole
    initial_spark_id: SparkId | None = None
    welcome_message: str | None = None
    ttl_days: int = DEFAULT_INVITATION_TTL_DAYS


@dataclass(frozen=True, slots=True)
class AcceptInvitationCommand:
    token: str
    member_id: MemberId
    display_name: str | None = None


class InvitationUseCase:
    """Orchestrates issuing and accepting invitations into a family."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository | None = None,
        clock: Clock,
        uow: UnitOfWork | None = None,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._clock = clock
        self._uow = uow
        self._invitations: dict[str, Invitation] = {}

    def create_invitation(
        self, command: CreateInvitationCommand
    ) -> Result[Invitation, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        family = family_res.unwrap()
        inviter_res = family.member(command.inviter_id)
        if inviter_res.is_err():
            return Err(inviter_res.unwrap_err())

        if not command.invitee_name.strip():
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "invitee name cannot be blank"))

        now = self._clock.now()
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            token=token,
            family_id=family.id,
            inviter_id=command.inviter_id,
            invitee_name=command.invitee_name.strip(),
            invitee_role=command.invitee_role,
            created_at=now,
            expires_at=now + timedelta(days=command.ttl_days),
            initial_spark_id=command.initial_spark_id,
            welcome_message=command.welcome_message,
        )

        self._invitations[token] = invitation
        return Ok(invitation)

    def get_invitation(self, token: str) -> Result[Invitation, DomainError]:
        invitation = self._invitations.get(token)
        if invitation is None:
            return Err(DomainError(ErrorCode.PERMISSION_DENIED, "invitation not found or expired"))

        now = self._clock.now()
        if now > invitation.expires_at:
            return Err(DomainError(ErrorCode.PERMISSION_DENIED, "invitation has expired"))

        return Ok(invitation)

    def accept_invitation(
        self, command: AcceptInvitationCommand
    ) -> Result[tuple[Family, Member], DomainError]:
        inv_res = self.get_invitation(command.token)
        if inv_res.is_err():
            return Err(inv_res.unwrap_err())

        invitation = inv_res.unwrap()

        family_res = self._families.get(invitation.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        family = family_res.unwrap()
        name = command.display_name or invitation.invitee_name
        new_member = Member(
            id=command.member_id,
            display_name=name,
            role=invitation.invitee_role,
        )

        add_res = family.add_member(new_member)
        if add_res.is_err():
            return Err(add_res.unwrap_err())

        updated_family = add_res.unwrap()
        save_res = self._families.save(updated_family)
        if save_res.is_err():
            return Err(save_res.unwrap_err())

        # Invalidate the token once claimed
        del self._invitations[command.token]
        return Ok((updated_family, new_member))
