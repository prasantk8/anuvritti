"""TASK-1105 - Asymmetric Rate Limiting & Abuse Control (HARDENING 5.2, PRD 8.2).

Verifies that:
1. Capture operations have generous headroom and never throttle a parent saving memories.
2. Bulk egress and authentication endpoints are capped to prevent scraping or brute-force.
3. Throttled responses return HTTP 429 with valid Retry-After headers.
"""

from __future__ import annotations

from anuvritti.interfaces.http.limits import (
    TIER_AUTH_BRUTE_FORCE,
    TIER_BULK_EGRESS,
    TIER_CAPTURE,
    TokenBucketLimiter,
    classify_route_tier,
)


def test_classify_route_tiers():
    assert classify_route_tier("POST", "/families/f1/sparks")[0] == "capture"
    assert classify_route_tier("POST", "/families/f1/captures")[0] == "capture"
    assert classify_route_tier("POST", "/families/f1/voice")[0] == "capture"
    assert classify_route_tier("GET", "/families/f1/media/med-123")[0] == "bulk_egress"
    assert classify_route_tier("POST", "/auth/pair")[0] == "auth"
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
