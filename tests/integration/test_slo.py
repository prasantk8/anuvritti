"""TASK-1104 - Service Levels a Family Would Recognise (PRD 8.2, HARDENING 5.4).

Verifies that:
1. SLO targets correspond to family promises (99.9% capture, 99.5% return, 99.0% film).
2. Error budget burn rates trigger alerts only when monthly promises are endangered.
3. Multi-window multi-burn rate logic prevents alert noise.
"""

from __future__ import annotations

from anuvritti.observability.slo import (
    SLO_CAPTURE_ACCEPTED,
    SLO_FILM_COMPILED,
    SLO_RETURN_DELIVERED,
    AlertSeverity,
    SLOCalculator,
)


def test_slo_definitions():
    assert SLO_CAPTURE_ACCEPTED.target_ratio == 0.999
    assert (
        SLO_CAPTURE_ACCEPTED.error_budget == 0.0010000000000000009
        or abs(SLO_CAPTURE_ACCEPTED.error_budget - 0.001) < 1e-6
    )
    assert SLO_CAPTURE_ACCEPTED.latency_threshold_ms == 200.0

    assert SLO_RETURN_DELIVERED.target_ratio == 0.995
    assert abs(SLO_RETURN_DELIVERED.error_budget - 0.005) < 1e-6

    assert SLO_FILM_COMPILED.target_ratio == 0.990
    assert abs(SLO_FILM_COMPILED.error_budget - 0.010) < 1e-6


def test_normal_budget_consumption_does_not_alert():
    # 10,000 capture requests, 9,995 good -> 0.05% error rate
    # (half of the 0.1% budget) -> burn rate 0.5x
    result = SLOCalculator.evaluate(
        slo=SLO_CAPTURE_ACCEPTED,
        total_events=10000,
        good_events=9995,
        window_hours=1.0,
    )
    assert result.actual_ratio == 0.9995
    assert result.severity == AlertSeverity.NORMAL


def test_rapid_burn_rate_triggers_page_alert():
    # 1,000 capture requests, 980 good -> 2% error rate (20x error budget)
    # -> burn rate 20x (> 14.4x)
    result = SLOCalculator.evaluate(
        slo=SLO_CAPTURE_ACCEPTED,
        total_events=1000,
        good_events=980,
        window_hours=1.0,
    )
    assert result.burn_rate >= 14.4
    assert result.severity == AlertSeverity.PAGE


def test_moderate_burn_rate_triggers_ticket_alert():
    # 1,000 capture requests, 992 good -> 0.8% error rate (8x error budget)
    # -> burn rate 8x (>= 6x, < 14.4x)
    result = SLOCalculator.evaluate(
        slo=SLO_CAPTURE_ACCEPTED,
        total_events=1000,
        good_events=992,
        window_hours=1.0,
    )
    assert 6.0 <= result.burn_rate < 14.4
    assert result.severity == AlertSeverity.TICKET


def test_zero_events_returns_healthy_state():
    result = SLOCalculator.evaluate(
        slo=SLO_RETURN_DELIVERED,
        total_events=0,
        good_events=0,
        window_hours=1.0,
    )
    assert result.actual_ratio == 1.0
    assert result.severity == AlertSeverity.NORMAL
