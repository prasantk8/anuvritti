"""TASK-1409 - Support path that cannot read the family's archive.

PRD 44, PRD 47.
"""

from __future__ import annotations

from datetime import UTC, datetime

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteFamilyRepository
from anuvritti.application.support import (
    BlindSupportUseCase,
    CreateSupportTicketCommand,
)
from anuvritti.domain.family import Family, Member
from anuvritti.domain.values import MemberRole
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import FamilyId, MemberId


def test_support_ticketing_and_diagnostics_without_vault_access() -> None:
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    conn = connect(":memory:")
    migrate(conn)
    families = SqliteFamilyRepository(conn)

    family_id = FamilyId("fam-support-1")
    parent_id = MemberId("parent-1")

    family = Family(
        id=family_id,
        name="The Patels",
        members=(Member(id=parent_id, role=MemberRole.PARENT, display_name="Rohan"),),
        children=(),
        created_at=now,
    )
    families.save(family)

    use_case = BlindSupportUseCase(families=families, clock=clock)

    # 1. Family creates a support inquiry
    cmd = CreateSupportTicketCommand(
        family_id=family_id,
        member_id=parent_id,
        contact_email="rohan@example.com",
        subject="Syncing issue on secondary device",
        message="My phone is showing pending uploads.",
    )

    res = use_case.create_ticket(cmd)
    assert res.is_ok()
    ticket = res.unwrap()
    assert ticket.ticket_id.startswith("TICK-")
    assert ticket.status == "open"

    # 2. Support overview provides operational signals without content leak
    overview_res = use_case.get_technical_overview(family_id)
    assert overview_res.is_ok()
    overview = overview_res.unwrap()
    assert overview.member_count == 1
    assert overview.children_count == 0
    assert overview.is_healthy is True

    # Assert overview payload contains no spark text, voice transcripts or keys
    for field_name in overview.__slots__:
        val = getattr(overview, field_name)
        assert not isinstance(val, (dict, list, str)) or field_name in ("family_id",)
