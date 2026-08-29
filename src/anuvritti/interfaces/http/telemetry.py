"""Telemetry and RED Metrics with Cardinality Ceiling (TASK-1103, PRD 44, HARDENING 5.4).

Guarantees:
1. Hard Cardinality Ceiling: Max distinct metric series ceiling (500) prevents memory exhaustion.
2. Strict Label Whitelist: Only bounded, operational labels (route_template, status).
3. Zero-PII Invariant: Forbids child names, IDs, transcripts, IPs, or filenames in metrics/traces.
4. RED Metrics: Request Rate, Error Rate, and Duration latency distributions.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

# Pattern matching UUIDs, integer IDs, and hex hashes
ID_PATTERN = re.compile(
    r"/(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{16,64}|\d+)"
)

FORBIDDEN_LABEL_KEYS = {
    "child_id",
    "family_id",
    "user_id",
    "ip",
    "client_ip",
    "name",
    "child_name",
    "transcript",
    "filename",
    "token",
    "authorization",
    "content",
}

FORBIDDEN_SPAN_ATTR_PATTERNS = [
    "name",
    "child",
    "transcript",
    "token",
    "secret",
    "key",
    "text",
    "note",
    "body",
    "content",
    "email",
]

MAX_METRIC_SERIES = 500


def normalize_route(path: str) -> str:
    """Strip dynamic runtime IDs from path to ensure route template cardinality is bounded."""
    if not path or path == "/":
        return "/"
    # Replace ID segments with generic {id}
    normalized = ID_PATTERN.sub("/{id}", path)
    # Collapse multiple slashes
    return re.sub(r"/+", "/", normalized)


@dataclass
class REDMetrics:
    """Prometheus-compatible RED (Rate, Errors, Duration) metrics accumulator with cardinality ceiling."""

    requests: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    duration_sum_ms: dict[str, float] = field(default_factory=dict)
    duration_count: dict[str, int] = field(default_factory=dict)
    # Histogram buckets in milliseconds: 10ms, 50ms, 100ms, 250ms, 500ms, 1000ms, 2500ms, 5000ms
    duration_buckets: dict[str, dict[float, int]] = field(default_factory=dict)
    total_series: int = 0
    latency_ms_total: float = 0.0
    request_count: int = 0

    BUCKET_LE = (10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0)

    def observe(
        self,
        route_or_method: str,
        status_or_path: int | str,
        duration_or_status: float | int,
        duration_ms: float | None = None,
    ) -> None:
        if duration_ms is not None:
            # Called as observe(method, path, status, duration)
            raw_path = str(status_or_path)
            status = int(duration_or_status)
            dur = float(duration_ms)
        else:
            # Called as observe(route, status, duration)
            raw_path = str(route_or_method)
            status = int(status_or_path)
            dur = float(duration_or_status)

        route = normalize_route(raw_path)
        status_str = str(status)
        key = f"{route}|{status_str}"

        if key not in self.requests:
            if self.total_series >= MAX_METRIC_SERIES:
                route = "/other"
                key = f"{route}|{status_str}"
            else:
                self.total_series += 1

        self.requests[key] = self.requests.get(key, 0) + 1
        self.request_count += 1
        self.latency_ms_total += dur
        self.duration_sum_ms[key] = self.duration_sum_ms.get(key, 0.0) + dur
        self.duration_count[key] = self.duration_count.get(key, 0) + 1

        if status >= 400:
            self.errors[route] = self.errors.get(route, 0) + 1

        if key not in self.duration_buckets:
            self.duration_buckets[key] = dict.fromkeys(self.BUCKET_LE, 0)

        for le in self.BUCKET_LE:
            if dur <= le:
                self.duration_buckets[key][le] += 1

    @staticmethod
    def _labels(key: str, **extra: str) -> str:
        """`route|status` back into a Prometheus label set."""
        route, status = key.split("|")
        pairs = {"route": route, "status": status, **extra}
        return "{" + ",".join(f'{k}="{v}"' for k, v in pairs.items()) + "}"

    def render(self, product: dict[str, int] | None = None) -> str:
        return self.render_prometheus(product)

    def render_prometheus(self, product_counts: dict[str, int] | None = None) -> str:
        product = product_counts or {}
        lines = [
            "# HELP anuvritti_http_requests_total HTTP requests by route and status.",
            "# TYPE anuvritti_http_requests_total counter",
        ]
        for key, count in sorted(self.requests.items()):
            lines.append(f"anuvritti_http_requests_total{self._labels(key)} {count}")

        lines.extend(
            [
                "",
                "# HELP anuvritti_http_requests_errors_total Total failed HTTP requests (4xx and 5xx).",
                "# TYPE anuvritti_http_requests_errors_total counter",
            ]
        )
        for route, count in sorted(self.errors.items()):
            lines.append(f'anuvritti_http_requests_errors_total{{route="{route}"}} {count}')

        lines.extend(
            [
                "",
                "# HELP anuvritti_http_request_duration_ms HTTP request latency in milliseconds.",
                "# TYPE anuvritti_http_request_duration_ms histogram",
            ]
        )
        for key, buckets in sorted(self.duration_buckets.items()):
            for le, count in sorted(buckets.items()):
                labels = self._labels(key, le=str(le))
                lines.append(f"anuvritti_http_request_duration_ms_bucket{labels} {count}")
            sum_ms = self.duration_sum_ms.get(key, 0.0)
            cnt = self.duration_count.get(key, 0)
            lines.append(f"anuvritti_http_request_duration_ms_sum{self._labels(key)} {sum_ms:.3f}")
            lines.append(f"anuvritti_http_request_duration_ms_count{self._labels(key)} {cnt}")

        lines.extend(
            [
                "",
                "# HELP anuvritti_http_request_duration_ms_sum Total request time.",
                "# TYPE anuvritti_http_request_duration_ms_sum counter",
                f"anuvritti_http_request_duration_ms_sum {self.latency_ms_total:.3f}",
                "# HELP anuvritti_http_requests_handled Requests handled.",
                "# TYPE anuvritti_http_requests_handled counter",
                f"anuvritti_http_requests_handled {self.request_count}",
                "",
                "# --- product metrics (PRD 53) ---",
                "# HELP anuvritti_sparks_captured_total Intentions captured.",
                "# TYPE anuvritti_sparks_captured_total counter",
                f"anuvritti_sparks_captured_total {product.get('SparkCaptured', 0)}",
                "# HELP anuvritti_moments_created_total Intentions that became real experiences.",
                "# TYPE anuvritti_moments_created_total counter",
                f"anuvritti_moments_created_total {product.get('MomentCreated', 0)}",
                "# HELP anuvritti_intent_to_moment_ratio The primary north star (PRD 53).",
                "# TYPE anuvritti_intent_to_moment_ratio gauge",
                f"anuvritti_intent_to_moment_ratio {_ratio(product):.4f}",
                "",
                "# --- anti-metrics (PRD 53): these are watched going DOWN ---",
                "# HELP anuvritti_suggestions_emitted_total Times the product interrupted a family.",
                "# TYPE anuvritti_suggestions_emitted_total counter",
                f"anuvritti_suggestions_emitted_total {product.get('SparkSuggested', 0)}",
                "# HELP anuvritti_suggestions_declined_total Suggestions the family did not want.",
                "# TYPE anuvritti_suggestions_declined_total counter",
                f"anuvritti_suggestions_declined_total {product.get('SparkArchived', 0)}",
                "",
            ]
        )

        return "\n".join(lines)


def _ratio(product: dict[str, int]) -> float:
    captured = product.get("SparkCaptured", 0)
    return product.get("MomentCreated", 0) / captured if captured else 0.0


@dataclass
class SanitizedTraceSpan:
    """Trace span with strict PII filtering and attribute allowlisting."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def set_attribute(self, key: str, value: Any) -> None:
        key_lower = key.lower()
        # Reject forbidden label keys or pattern matches
        if key_lower in FORBIDDEN_LABEL_KEYS or any(
            pat in key_lower for pat in FORBIDDEN_SPAN_ATTR_PATTERNS
        ):
            # Suppress sensitive attribute
            return
        self.attributes[key] = value

    def finish(self) -> None:
        self.end_time = time.time()
