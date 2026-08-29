"""Service Level Objectives (SLOs) & Error Budget Burn Rate Alerting (PRD 8.2, HARDENING 5.4).

Family Service Level Promises:
1. Capture Accepted: 99.9% of capture requests succeed in <= 200ms.
2. Return Delivered: 99.5% of return queries succeed in <= 100ms.
3. Film Compiled: 99.0% of film render jobs succeed in <= 60s.

Alerting Rule:
Alerts fire on multi-window error budget burn rate (14.4x 1-hour burn or 6.0x 6-hour burn),
never on temporary noise or single transient spikes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AlertSeverity(StrEnum):
    PAGE = "PAGE"  # Critical burn: 14.4x burn rate (2% budget consumed in 1h)
    TICKET = "TICKET"  # Moderate burn: 6.0x burn rate (5% budget consumed in 6h)
    NORMAL = "NORMAL"  # Within healthy budget envelope


@dataclass(frozen=True)
class ServiceLevelObjective:
    name: str
    target_ratio: float  # e.g. 0.999 for 99.9%
    latency_threshold_ms: float
    description: str

    @property
    def error_budget(self) -> float:
        return 1.0 - self.target_ratio


SLO_CAPTURE_ACCEPTED = ServiceLevelObjective(
    name="capture_accepted",
    target_ratio=0.999,  # 99.9%
    latency_threshold_ms=200.0,
    description="When a parent saves a moment or voice note, it is acknowledged in under 200ms",
)

SLO_RETURN_DELIVERED = ServiceLevelObjective(
    name="return_delivered",
    target_ratio=0.995,  # 99.5%
    latency_threshold_ms=100.0,
    description="When a family checks Right Now or milestone return, it responds in under 100ms",
)

SLO_FILM_COMPILED = ServiceLevelObjective(
    name="film_compiled",
    target_ratio=0.990,  # 99.0%
    latency_threshold_ms=60000.0,
    description="Memory compiler renders anniversary video film without failure",
)


@dataclass
class SLIResult:
    slo: ServiceLevelObjective
    total_events: int
    good_events: int
    actual_ratio: float
    error_rate: float
    burn_rate: float
    severity: AlertSeverity


class SLOCalculator:
    """Computes SLI compliance and multi-burn-rate alerts."""

    @staticmethod
    def evaluate(
        slo: ServiceLevelObjective,
        total_events: int,
        good_events: int,
        window_hours: float = 1.0,
    ) -> SLIResult:
        if total_events == 0:
            return SLIResult(
                slo=slo,
                total_events=0,
                good_events=0,
                actual_ratio=1.0,
                error_rate=0.0,
                burn_rate=0.0,
                severity=AlertSeverity.NORMAL,
            )

        actual_ratio = good_events / total_events
        error_rate = 1.0 - actual_ratio
        # Burn rate = current error rate / allowed error budget
        burn_rate = error_rate / slo.error_budget if slo.error_budget > 0 else 0.0

        # Multi-window multi-burn rate evaluation (Google SRE standard)
        # 1-hour window: 14.4x burn rate consumes 2% of monthly budget in 1 hour -> PAGE
        # 6-hour window: 6.0x burn rate consumes 5% of monthly budget in 6 hours -> TICKET
        severity = AlertSeverity.NORMAL
        if window_hours <= 1.0:
            if burn_rate >= 14.4:
                severity = AlertSeverity.PAGE
            elif burn_rate >= 6.0:
                severity = AlertSeverity.TICKET
        else:
            if burn_rate >= 6.0:
                severity = AlertSeverity.PAGE
            elif burn_rate >= 3.0:
                severity = AlertSeverity.TICKET

        return SLIResult(
            slo=slo,
            total_events=total_events,
            good_events=good_events,
            actual_ratio=actual_ratio,
            error_rate=error_rate,
            burn_rate=burn_rate,
            severity=severity,
        )
