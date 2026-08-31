"""TASK-1407 - Messages that cannot nag.

PRD 8.5, PRD 46, PRD 47.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.application.messaging import QuietMessagingUseCase
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId


def test_enforces_one_message_per_day_ceiling() -> None:
    now = datetime(2026, 8, 31, 10, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    messaging = QuietMessagingUseCase(clock=clock)

    family_id = FamilyId("fam-quiet-1")
    member_id = MemberId("mem-papa")

    # First message succeeds
    res1 = messaging.schedule_message(
        family_id, member_id, "Aarav walked today. Would you like to record a note?"
    )
    assert res1.is_ok()

    # Second message within 24 hours fails cleanly
    clock.advance(hours=6)
    res2 = messaging.schedule_message(family_id, member_id, "Another quiet note")
    assert res2.is_err()
    assert res2.unwrap_err().code == ErrorCode.TOO_MANY_REQUESTS

    # After 24 hours, sending is permitted again
    clock.advance(hours=19)
    res3 = messaging.schedule_message(family_id, member_id, "Another quiet note")
    assert res3.is_ok()


def test_permanent_one_tap_silence_respected() -> None:
    now = datetime(2026, 8, 31, 10, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    messaging = QuietMessagingUseCase(clock=clock)

    family_id = FamilyId("fam-quiet-1")
    member_id = MemberId("mem-papa")

    # Mute notifications
    messaging.set_preference(family_id, member_id, silenced=True)

    res = messaging.schedule_message(family_id, member_id, "Gentle thought")
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.PERMISSION_DENIED


@pytest.mark.parametrize(
    "manipulative_copy",
    [
        "Hurry up and record!",
        "Don't forget to save today's spark!",
        "You are missing out on memories!",
        "Come back to the app!",
        "Keep your 7-day streak alive!",
        "Important update!",
    ],
)
def test_rejects_manipulative_nagging_or_urgent_copy(manipulative_copy: str) -> None:
    now = datetime(2026, 8, 31, 10, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    messaging = QuietMessagingUseCase(clock=clock)

    family_id = FamilyId("fam-quiet-1")
    member_id = MemberId("mem-papa")

    res = messaging.schedule_message(family_id, member_id, manipulative_copy)
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.VALIDATION_FAILED
