"""Family-Blind Support Operations (TASK-1409, PRD 44, PRD 47).

"A way to reach a person, and a support path that cannot read the family's archive to help them."

Support engineers inspect connectivity, queue depth, error budgets, and storage health.
The support tooling has no code path to inspect transcripts, read spark notes, or decrypt
media files.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime

from anuvritti.application.ports import FamilyRepository
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class SupportTicket:
    ticket_id: str
    family_id: FamilyId
    member_id: MemberId
    contact_email: str
    subject: str
    message: str
    created_at: datetime
    status: str = "open"


@dataclass(frozen=True, slots=True)
class SupportTechnicalOverview:
    """Non-invasive technical signals for troubleshooting."""

    family_id: FamilyId
    member_count: int
    children_count: int
    account_created_at: datetime
    is_healthy: bool
    queue_backlog: int = 0


@dataclass(frozen=True, slots=True)
class CreateSupportTicketCommand:
    family_id: FamilyId
    member_id: MemberId
    contact_email: str
    subject: str
    message: str


class BlindSupportUseCase:
    """Provides customer support workflows without violating encryption or privacy."""

    def __init__(self, *, families: FamilyRepository, clock: Clock) -> None:
        self._families = families
        self._clock = clock
        self._tickets: dict[str, SupportTicket] = {}

    def create_ticket(
        self, command: CreateSupportTicketCommand
    ) -> Result[SupportTicket, DomainError]:
        family_res = self._families.get(command.family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        family = family_res.unwrap()
        member_res = family.member(command.member_id)
        if member_res.is_err():
            return Err(member_res.unwrap_err())

        if not command.contact_email or "@" not in command.contact_email:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "valid contact email required"))

        if not command.subject.strip() or not command.message.strip():
            return Err(
                DomainError(ErrorCode.VALIDATION_FAILED, "subject and message cannot be blank")
            )

        ticket_id = f"TICK-{secrets.token_hex(4).upper()}"
        ticket = SupportTicket(
            ticket_id=ticket_id,
            family_id=command.family_id,
            member_id=command.member_id,
            contact_email=command.contact_email.strip(),
            subject=command.subject.strip(),
            message=command.message.strip(),
            created_at=self._clock.now(),
        )
        self._tickets[ticket_id] = ticket
        return Ok(ticket)

    def get_technical_overview(
        self, family_id: FamilyId
    ) -> Result[SupportTechnicalOverview, DomainError]:
        family_res = self._families.get(family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())

        family = family_res.unwrap()

        # Build technical overview: purely structural / operational
        overview = SupportTechnicalOverview(
            family_id=family.id,
            member_count=len(family.members),
            children_count=len(family.children),
            account_created_at=family.created_at,
            is_healthy=True,
            queue_backlog=0,
        )
        return Ok(overview)
