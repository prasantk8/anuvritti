"""The Clock port.

Time is an input, never an ambient global. The Return Engine's whole job is reasoning about
elapsed months, so time must be injectable and freezable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    """Production clock. Always timezone-aware UTC."""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()


class FrozenClock:
    """Test clock. Time only moves when a test says so."""

    __slots__ = ("_now",)

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.date()

    def advance(self, **delta: float) -> None:
        self._now = self._now + timedelta(**delta)
