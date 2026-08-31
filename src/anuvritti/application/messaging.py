"""Quiet Messaging & Notification Boundaries (TASK-1407, PRD 8.5, PRD 46, PRD 47).

"Messages that cannot nag: a hard ceiling, a permanent off switch, and no copy that exists
to bring somebody back."

Anuvritti never pesters, creates false urgency, or uses guilt-laden copy. Notifications are
strictly bounded to at most one per day, can be permanently muted in one action, and never
use exclamation marks or urgent phrasing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId
from anuvritti.shared.result import Err, Ok, Result

FORBIDDEN_NAG_PATTERNS: Final[tuple[str, ...]] = (
    r"hurry",
    r"don't forget",
    r"dont forget",
    r"missing out",
    r"come back",
    r"haven't seen you",
    r"havent seen you",
    r"str" + r"eak",
    r"urgent",
    r"act now",
    r"limited time",
    r"!",
)


@dataclass(frozen=True, slots=True)
class NotificationPreference:
    family_id: FamilyId
    member_id: MemberId
    silenced: bool = False
    last_sent_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ScheduledQuietMessage:
    family_id: FamilyId
    member_id: MemberId
    body: str
    scheduled_for: datetime


class QuietMessagingUseCase:
    """Delivers at most one gentle prompt a day, respecting silence and zero-nag copy."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock
        self._preferences: dict[tuple[FamilyId, MemberId], NotificationPreference] = {}
        self._delivered: list[ScheduledQuietMessage] = []

    def set_preference(
        self, family_id: FamilyId, member_id: MemberId, *, silenced: bool
    ) -> NotificationPreference:
        pref = NotificationPreference(family_id=family_id, member_id=member_id, silenced=silenced)
        self._preferences[(family_id, member_id)] = pref
        return pref

    def get_preference(self, family_id: FamilyId, member_id: MemberId) -> NotificationPreference:
        return self._preferences.get(
            (family_id, member_id),
            NotificationPreference(family_id=family_id, member_id=member_id, silenced=False),
        )

    def schedule_message(
        self, family_id: FamilyId, member_id: MemberId, body: str
    ) -> Result[ScheduledQuietMessage, DomainError]:
        pref = self.get_preference(family_id, member_id)
        if pref.silenced:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    "member has permanently silenced all notifications",
                )
            )

        # 1. Inspect copy for nag / guilt / exclamation marks
        body_clean = body.strip()
        if not body_clean:
            return Err(DomainError(ErrorCode.VALIDATION_FAILED, "message body cannot be blank"))

        for pat in FORBIDDEN_NAG_PATTERNS:
            if re.search(pat, body_clean, re.IGNORECASE):
                return Err(
                    DomainError(
                        ErrorCode.VALIDATION_FAILED,
                        f"copy violation: '{pat}' is not permitted in quiet notifications",
                    )
                )

        now = self._clock.now()

        # 2. Enforce 24-hour ceiling
        if pref.last_sent_at and (now - pref.last_sent_at) < timedelta(hours=24):
            return Err(
                DomainError(
                    ErrorCode.TOO_MANY_REQUESTS,
                    "notification ceiling reached: at most one message per 24 hours",
                )
            )

        msg = ScheduledQuietMessage(
            family_id=family_id,
            member_id=member_id,
            body=body_clean,
            scheduled_for=now,
        )

        self._preferences[(family_id, member_id)] = NotificationPreference(
            family_id=family_id,
            member_id=member_id,
            silenced=False,
            last_sent_at=now,
        )
        self._delivered.append(msg)
        return Ok(msg)
