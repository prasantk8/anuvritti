"""TASK-1406 - Family-blind operational metrics.

PRD 44, PRD 46, PRD 53.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.application.analytics import BlindAnalyticsUseCase
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode


def test_records_clean_operational_counters() -> None:
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    analytics = BlindAnalyticsUseCase(clock=clock)

    res = analytics.record_counter("sparks_captured_total", 1, metadata={"source": "audio"})
    assert res.is_ok()
    metric = res.unwrap()
    assert metric.event_name == "sparks_captured_total"
    assert metric.count == 1
    assert analytics.get_counter("sparks_captured_total") == 1


@pytest.mark.parametrize(
    "forbidden_key,val",
    [
        ("family_id", "fam-123"),
        ("child_id", "child-456"),
        ("member_id", "mem-789"),
        ("user_id", "usr-1"),
        ("title", "Aarav walked today"),
        ("transcript", "He said dada!"),
        ("text", "Some memory text"),
        ("audio_media_id", "med-abc"),
    ],
)
def test_refuses_any_payload_with_identifying_or_content_data(forbidden_key: str, val: str) -> None:
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    analytics = BlindAnalyticsUseCase(clock=clock)

    res = analytics.record_counter("error_occurred", 1, metadata={forbidden_key: val})
    assert res.is_err()
    err = res.unwrap_err()
    assert err.code == ErrorCode.PERMISSION_DENIED
    assert "privacy violation" in err.message
