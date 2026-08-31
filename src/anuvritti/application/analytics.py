"""Family-Blind Operational Metrics (TASK-1406, PRD 44, PRD 46, PRD 53).

"Measurement that cannot become surveillance: counted on the device, reported family-blind,
and never able to name a child or a moment."

Metrics are strictly operational (system health, throughput, error budget). Telemetry payloads
are prohibited from containing personal identifiers, family IDs, child names, spark text,
transcripts, or media keys.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

FORBIDDEN_KEY_PATTERNS: Final[tuple[str, ...]] = (
    r"family_?id",
    r"child_?id",
    r"member_?id",
    r"user_?id",
    r"name",
    r"title",
    r"transcript",
    r"text",
    r"body",
    r"audio",
    r"voice",
    r"email",
    r"media_?id",
)


@dataclass(frozen=True, slots=True)
class OperationalMetric:
    """A coarse operational counter with zero personal or family identity."""

    event_name: str
    count: int
    recorded_at: datetime


class BlindAnalyticsUseCase:
    """Collects coarse operational counters without user surveillance."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock
        self._counters: dict[str, int] = defaultdict(int)
        self._history: list[OperationalMetric] = []

    def record_counter(
        self, event_name: str, increment: int = 1, metadata: dict[str, Any] | None = None
    ) -> Result[OperationalMetric, DomainError]:
        if not event_name.strip():
            return Err(
                DomainError(ErrorCode.VALIDATION_FAILED, "metric event name cannot be empty")
            )

        if metadata:
            # Audit metadata for privacy violations
            for key, val in metadata.items():
                for pat in FORBIDDEN_KEY_PATTERNS:
                    if re.search(pat, key, re.IGNORECASE):
                        return Err(
                            DomainError(
                                ErrorCode.PERMISSION_DENIED,
                                f"privacy violation: telemetry field '{key}' is forbidden",
                            )
                        )
                # Verify string values do not look like IDs or text
                if isinstance(val, str) and (
                    val.startswith(("fam-", "child-", "member-", "spark-")) or len(val) > 50
                ):
                    return Err(
                        DomainError(
                            ErrorCode.PERMISSION_DENIED,
                            "privacy violation: telemetry payload cannot contain "
                            "entities or content",
                        )
                    )

        now = self._clock.now()
        self._counters[event_name] += increment
        metric = OperationalMetric(
            event_name=event_name,
            count=self._counters[event_name],
            recorded_at=now,
        )
        self._history.append(metric)
        return Ok(metric)

    def get_counter(self, event_name: str) -> int:
        return self._counters.get(event_name, 0)
