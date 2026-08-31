"""TASK-1402 - The invitation flow for co-parents and grandparents.

PRD 26, PRD 27, PRD 51.
"""

from __future__ import annotations

from datetime import UTC, datetime

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteFamilyRepository
from anuvritti.application.invitations import (
    AcceptInvitationCommand,
    CreateInvitationCommand,
    InvitationUseCase,
)
from anuvritti.domain.family import Family, Member
from anuvritti.domain.values import MemberRole
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import FamilyId, MemberId, SparkId


def test_coparent_invitation_flow() -> None:
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    conn = connect(":memory:")
    migrate(conn)
    families = SqliteFamilyRepository(conn)

    family_id = FamilyId("fam-inv-1")
    founder_id = MemberId("founder-1")

    family = Family(
        id=family_id,
        name="The Mehtas",
        members=(Member(id=founder_id, role=MemberRole.PARENT, display_name="Dev"),),
        children=(),
        created_at=now,
    )
    families.save(family)

    use_case = InvitationUseCase(families=families, clock=clock)

    # 1. Founder creates invitation for co-parent with a welcome spark
    create_cmd = CreateInvitationCommand(
        family_id=family_id,
        inviter_id=founder_id,
        invitee_name="Pooja",
        invitee_role=MemberRole.CO_PARENT,
        initial_spark_id=SparkId("spark-first-steps"),
        welcome_message="Look at this moment from yesterday!",
    )

    create_res = use_case.create_invitation(create_cmd)
    assert create_res.is_ok()
    invitation = create_res.unwrap()
    assert invitation.invitee_name == "Pooja"
    assert invitation.invitee_role == MemberRole.CO_PARENT
    assert invitation.welcome_message == "Look at this moment from yesterday!"

    # 2. Invite token inspectable before acceptance
    inspect_res = use_case.get_invitation(invitation.token)
    assert inspect_res.is_ok()
    assert inspect_res.unwrap().family_id == family_id

    # 3. Co-parent accepts invitation
    coparent_id = MemberId("coparent-pooja")
    accept_cmd = AcceptInvitationCommand(
        token=invitation.token,
        member_id=coparent_id,
    )

    accept_res = use_case.accept_invitation(accept_cmd)
    assert accept_res.is_ok()
    updated_family, new_member = accept_res.unwrap()

    assert new_member.id == coparent_id
    assert new_member.role == MemberRole.CO_PARENT
    assert len(updated_family.members) == 2

    # 4. Token cannot be reused
    reuse_res = use_case.accept_invitation(accept_cmd)
    assert reuse_res.is_err()
