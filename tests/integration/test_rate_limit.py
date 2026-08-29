"""TASK-1105 - Asymmetric Rate Limiting & Abuse Control (HARDENING 5.2, PRD 8.2).

Verifies that:
1. Capture operations have generous headroom and never throttle a parent saving memories.
2. Bulk egress and authentication endpoints are capped to prevent scraping or brute-force.
3. Throttled responses return HTTP 429 with valid Retry-After headers and strict error envelope.
4. Active rate limiter is mounted in FastAPI pipeline and enforced on real requests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.interfaces.http.limits import (
    TIER_AUTH_BRUTE_FORCE,
    TIER_BULK_EGRESS,
    TIER_CAPTURE,
    TokenBucketLimiter,
    classify_route_tier,
)
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator


def test_classify_route_tiers():
    assert classify_route_tier("POST", "/v1/sparks")[0] == "capture"
    assert classify_route_tier("POST", "/v1/little-things")[0] == "capture"
    assert classify_route_tier("POST", "/v1/right-now")[0] == "capture"
    assert classify_route_tier("POST", "/v1/voice")[0] == "capture"
    assert classify_route_tier("POST", "/v1/media")[0] == "capture"
    assert classify_route_tier("GET", "/v1/media/med-123")[0] == "bulk_egress"
    assert classify_route_tier("POST", "/v1/pairing/claim")[0] == "auth"
    assert classify_route_tier("POST", "/v1/families")[0] == "auth"
    assert classify_route_tier("GET", "/health")[0] == "default"


def test_capture_allows_high_frequency_bursts():
    current_time = 1000.0
    limiter = TokenBucketLimiter(now_fn=lambda: current_time)

    # Simulate parent rapid-fire uploading 60 photos/sparks within 1 minute
    for _ in range(60):
        allowed, remaining, retry_after = limiter.is_allowed("parent-token:capture", TIER_CAPTURE)
        assert allowed is True
        assert retry_after == 0

    assert remaining == TIER_CAPTURE.max_requests - 60


def test_bulk_egress_throttles_after_limit():
    current_time = 1000.0
    limiter = TokenBucketLimiter(now_fn=lambda: current_time)

    # 30 allowed requests
    for _ in range(TIER_BULK_EGRESS.max_requests):
        allowed, _, _ = limiter.is_allowed("bad-token:bulk_egress", TIER_BULK_EGRESS)
        assert allowed is True

    # 31st request must be rejected
    allowed, remaining, retry_after = limiter.is_allowed("bad-token:bulk_egress", TIER_BULK_EGRESS)
    assert allowed is False
    assert remaining == 0
    assert retry_after > 0


def test_auth_brute_force_throttles_after_10_attempts():
    current_time = 1000.0
    limiter = TokenBucketLimiter(now_fn=lambda: current_time)

    for _ in range(10):
        allowed, _, _ = limiter.is_allowed("attacker-ip:auth", TIER_AUTH_BRUTE_FORCE)
        assert allowed is True

    # 11th attempt is blocked
    allowed, _, retry_after = limiter.is_allowed("attacker-ip:auth", TIER_AUTH_BRUTE_FORCE)
    assert allowed is False
    assert retry_after == 60


def test_sliding_window_resets_after_elapsed_time():
    current_time = 1000.0
    limiter = TokenBucketLimiter(now_fn=lambda: current_time)

    # Exhaust bulk egress limit
    for _ in range(TIER_BULK_EGRESS.max_requests):
        limiter.is_allowed("token-1:bulk_egress", TIER_BULK_EGRESS)

    # Advance time past 60-second window
    current_time += 61.0

    # Request is allowed again
    allowed, remaining, _ = limiter.is_allowed("token-1:bulk_egress", TIER_BULK_EGRESS)
    assert allowed is True
    assert remaining == TIER_BULK_EGRESS.max_requests - 1


def test_mounted_rate_limiter_enforces_429_with_error_envelope(tmp_path: Path):
    clock = FrozenClock(datetime(2026, 8, 25, 9, 0, tzinfo=UTC))
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "ratelimit_test.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("id"))
    app = create_app(settings, container=container)
    client = TestClient(app)

    # Make 10 pairing claim attempts (the limit for auth tier)
    for _ in range(10):
        resp = client.post(
            "/v1/pairing/claim",
            json={"code": "BAD-CODE", "device_name": "attacker"},
        )
        assert "X-RateLimit-Remaining" in resp.headers

    # 11th request must be throttled with HTTP 429
    throttled = client.post(
        "/v1/pairing/claim",
        json={"code": "BAD-CODE", "device_name": "attacker"},
    )
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers
    body = throttled.json()
    assert body == {
        "error": {
            "code": "TOO_MANY_REQUESTS",
            "message": "Rate limit exceeded. Please wait before retrying.",
            "details": {"retry_after": int(throttled.headers["Retry-After"]), "tier": "auth"},
        }
    }
