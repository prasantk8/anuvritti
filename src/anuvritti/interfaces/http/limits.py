"""Asymmetric Rate Limiting & Abuse Control (HARDENING 5.2, PRD 8.2, TASK-1105).

Asymmetric Rate Limiting Rules:
1. Capture Invariant: Saving a moment (`POST /sparks`, `POST /little-things`, `POST /voice`)
   is NEVER throttled during normal family life (burst allowance >= 120/min).
2. Bulk Egress Protection: Bulk media reads (`GET /media/*`) are capped
   (30 requests/min) to prevent compromised tokens from dumping an entire family archive.
3. Authentication Brute-Force Guard: Token pairing and bootstrap attempts are strictly
   rate-limited (10 attempts/min per IP) to prevent credential stuffing.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable


@dataclass
class RateLimitRule:
    max_requests: int
    window_seconds: int
    burst_capacity: int


# Rate limit tiers per route pattern
TIER_CAPTURE = RateLimitRule(max_requests=120, window_seconds=60, burst_capacity=60)
TIER_BULK_EGRESS = RateLimitRule(max_requests=30, window_seconds=60, burst_capacity=10)
TIER_AUTH_BRUTE_FORCE = RateLimitRule(max_requests=10, window_seconds=60, burst_capacity=5)
TIER_DEFAULT = RateLimitRule(max_requests=60, window_seconds=60, burst_capacity=20)


def classify_route_tier(method: str, path: str) -> tuple[str, RateLimitRule]:
    method = method.upper()
    if method in ("POST", "PUT") and any(
        kw in path
        for kw in (
            "/sparks",
            "/little-things",
            "/right-now",
            "/voice",
            "/media",
            "/why",
            "/done",
            "/override",
            "/captures",
        )
    ):
        return ("capture", TIER_CAPTURE)
    if method == "GET" and "/media/" in path:
        return ("bulk_egress", TIER_BULK_EGRESS)
    if (
        method == "POST"
        and any(kw in path for kw in ("/families", "/pairing/claim", "/pairing/codes"))
    ) or any(kw in path for kw in ("/auth/pair", "/auth/token", "/auth/claim", "/pairing")):
        return ("auth", TIER_AUTH_BRUTE_FORCE)
    return ("default", TIER_DEFAULT)


class TokenBucketLimiter:
    """In-memory sliding-window token bucket rate limiter."""

    def __init__(self, now_fn: Callable[[], float] = time.time) -> None:
        self._now = now_fn
        # key -> list of timestamp floats
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, rule: RateLimitRule) -> tuple[bool, int, int]:
        """Check if request is permitted under rule.

        Returns: (allowed, remaining, retry_after_seconds)
        """
        now = self._now()
        window_start = now - rule.window_seconds
        # Clean timestamps older than window
        timestamps = [ts for ts in self._buckets[key] if ts > window_start]
        self._buckets[key] = timestamps

        if len(timestamps) < rule.max_requests:
            timestamps.append(now)
            remaining = rule.max_requests - len(timestamps)
            return True, remaining, 0

        # Over limit
        oldest = timestamps[0] if timestamps else now
        retry_after = max(1, int(oldest + rule.window_seconds - now))
        return False, 0, retry_after

    def reset(self) -> None:
        self._buckets.clear()


def install_rate_limiter(
    app: FastAPI, limiter: TokenBucketLimiter | None = None
) -> TokenBucketLimiter:
    """Attach asymmetric rate limiting middleware to FastAPI app."""
    active_limiter = limiter or TokenBucketLimiter()
    app.state.limiter = active_limiter

    @app.middleware("http")
    async def rate_limit_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        exempt_paths = ("/metrics", "/ready", "/health", "/v1/openapi.json", "/openapi.json")
        if request.url.path in exempt_paths:
            return await call_next(request)

        # Determine client identifier (token hash or client IP)
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        client_key = (
            f"token:{hash(token)}"
            if token
            else f"ip:{request.client.host if request.client else 'unknown'}"
        )

        tier_name, rule = classify_route_tier(request.method, request.url.path)
        rate_key = f"{client_key}:{tier_name}"

        allowed, remaining, retry_after = active_limiter.is_allowed(rate_key, rule)

        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": {
                        "code": "TOO_MANY_REQUESTS",
                        "message": "Rate limit exceeded. Please wait before retrying.",
                        "details": {"retry_after": retry_after, "tier": tier_name},
                    }
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    return active_limiter
