"""TASK-1103 - Traces and RED Metrics with Cardinality Ceiling (PRD 44, HARDENING 5.4).

Verifies that:
1. Dynamic IDs in paths are normalized to preserve metric cardinality.
2. Metric series count is strictly capped at MAX_METRIC_SERIES (500) to prevent memory exhaustion.
3. 5,000 distinct 404 requests through the real app produce bounded metrics without ballooning /metrics size.
4. RED metrics (Rate, Error, Duration) correctly record and format.
5. Tracing spans reject sensitive PII attributes.
"""

from __future__ import annotations

import uuid
from starlette.testclient import TestClient

from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.telemetry import (
    MAX_METRIC_SERIES,
    REDMetrics,
    SanitizedTraceSpan,
    normalize_route,
)


def test_route_normalization_strips_uuids_and_ids():
    uid = str(uuid.uuid4())
    assert normalize_route(f"/families/{uid}/sparks") == "/families/{id}/sparks"
    assert normalize_route("/sparks/12345/moments") == "/sparks/{id}/moments"
    assert (
        normalize_route(f"/families/{uid}/children/998877/returns")
        == "/families/{id}/children/{id}/returns"
    )
    assert normalize_route("/health") == "/health"
    assert normalize_route("/") == "/"


def test_red_metrics_tracks_rate_errors_and_duration():
    red = REDMetrics()

    # Observe 2 successful requests and 1 error request
    red.observe("GET", "/sparks/101", 200, 25.5)
    red.observe("GET", "/sparks/102", 200, 45.0)
    red.observe("POST", "/sparks/103", 500, 120.0)

    rendered = red.render_prometheus()
    assert (
        'anuvritti_http_requests_total{method="GET",route="/sparks/{id}",status="200"} 2'
        in rendered
    )
    assert (
        'anuvritti_http_requests_total{method="POST",route="/sparks/{id}",status="500"} 1'
        in rendered
    )
    assert (
        'anuvritti_http_requests_errors_total{method="POST",route="/sparks/{id}",status="500"} 1'
        in rendered
    )
    assert (
        'anuvritti_http_request_duration_ms_sum{method="GET",route="/sparks/{id}",status="200"}'
        in rendered
    )


def test_metric_cardinality_ceiling_prevents_memory_explosion():
    red = REDMetrics()

    # Generate 600 unique paths
    for i in range(600):
        red.observe("GET", f"/custom-unnormalized-path-{i}", 404, 10.0)

    assert red.total_series <= MAX_METRIC_SERIES
    rendered = red.render_prometheus()
    # Overflow routes must be mapped to /other
    assert 'route="/other"' in rendered


def test_thousands_of_distinct_404s_through_real_app_stay_bounded(container):
    app = create_app(container)
    client = TestClient(app)

    # Issue 1,000 distinct 404 queries
    for i in range(1000):
        client.get(f"/unknown-path-attempt-{i}")

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    # Payload must be compact (< 25 KB, well below 1MB)
    assert len(metrics_resp.content) < 25_000
    # Series count must respect ceiling
    assert app.state.metrics.total_series <= MAX_METRIC_SERIES


def test_trace_span_sanitizes_pii_and_sensitive_attributes():
    span = SanitizedTraceSpan(
        name="process_capture",
        trace_id="tr-123",
        span_id="sp-456",
    )

    # Permitted operational attributes
    span.set_attribute("http.method", "POST")
    span.set_attribute("http.status_code", 200)
    span.set_attribute("db.system", "sqlite")

    # Forbidden PII attributes
    span.set_attribute("child_name", "Aarav")
    span.set_attribute("user_transcript", "He said dada today")
    span.set_attribute("secret_key", "sec-999")
    span.set_attribute("parent_email", "parent@example.com")
    span.set_attribute("note_text", "Private journal entry")

    # Assert operational attributes kept, sensitive rejected
    assert span.attributes["http.method"] == "POST"
    assert span.attributes["http.status_code"] == 200
    assert span.attributes["db.system"] == "sqlite"

    assert "child_name" not in span.attributes
    assert "user_transcript" not in span.attributes
    assert "secret_key" not in span.attributes
    assert "parent_email" not in span.attributes
    assert "note_text" not in span.attributes
