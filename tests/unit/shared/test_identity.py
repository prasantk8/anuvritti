"""TASK-102 - typed identifiers and the Clock port."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from anuvritti.shared.clock import FrozenClock, SystemClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MemberId,
    MomentId,
    SparkId,
    Uuid7IdGenerator,
)


class TestTypedIds:
    def test_ids_of_different_types_are_never_equal(self):
        assert SparkId("x") != MomentId("x")

    def test_id_rejects_empty_value(self):
        with pytest.raises(ValueError, match="empty"):
            SparkId("")

    def test_id_stringifies_to_its_raw_value(self):
        assert str(FamilyId("fam-1")) == "fam-1"

    def test_ids_are_hashable(self):
        assert len({MemberId("a"), MemberId("a"), ChildId("a")}) == 2


class TestIdGenerator:
    def test_generates_unique_ids(self):
        gen = Uuid7IdGenerator()
        assert len({gen.new_id() for _ in range(500)}) == 500

    def test_ids_are_lexicographically_time_ordered(self):
        """Time-ordered ids keep the family archive naturally chronological."""
        gen = Uuid7IdGenerator()
        ids = [gen.new_id() for _ in range(50)]
        assert ids == sorted(ids)


class TestClock:
    def test_system_clock_is_timezone_aware_utc(self):
        assert SystemClock().now().tzinfo is UTC

    def test_frozen_clock_does_not_move(self):
        t = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
        clock = FrozenClock(t)
        assert clock.now() == t == clock.now()

    def test_frozen_clock_can_advance(self):
        clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
        clock.advance(days=90)
        assert clock.now() == datetime(2026, 4, 1, tzinfo=UTC)

    def test_today_returns_a_date(self):
        clock = FrozenClock(datetime(2026, 8, 25, 23, 30, tzinfo=UTC))
        assert clock.today() == date(2026, 8, 25)

    def test_frozen_clock_rejects_naive_datetimes(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            FrozenClock(datetime(2026, 1, 1))
