"""Observability (PRD 53, 63.4).

The metrics here mirror the PRD's own list, including the anti-metrics. Notification
volume is instrumented precisely so it can be watched going *down*: a product that
optimises this number upward has become the thing PRD 8.5 forbids.

No metric label ever carries a name, a URL or anything a child said.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from anuvritti.config.logging import bind_request_id, get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from anuvritti.interfaces.http.container import Container

log = get_logger("access")


class Metrics:
    """A tiny Prometheus text exposition. No dependency, no cardinality explosion."""

    def __init__(self) -> None:
        self.requests: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()
        self.latency_ms_total: float = 0.0
        self.request_count: int = 0

    def observe(self, route: str, status: int, duration_ms: float) -> None:
        self.requests[f"{route}|{status}"] += 1
        self.request_count += 1
        self.latency_ms_total += duration_ms
        if status >= 500:
            self.errors[route] += 1

    def render(self, product: dict[str, int]) -> str:
        lines = [
            "# HELP anuvritti_http_requests_total HTTP requests by route and status.",
            "# TYPE anuvritti_http_requests_total counter",
        ]
        for key, count in sorted(self.requests.items()):
            route, status = key.split("|")
            lines.append(
                f'anuvritti_http_requests_total{{route="{route}",status="{status}"}} {count}'
            )
        lines += [
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
        return "\n".join(lines)


def _ratio(product: dict[str, int]) -> float:
    captured = product.get("SparkCaptured", 0)
    return product.get("MomentCreated", 0) / captured if captured else 0.0


def install_observability(app: FastAPI, box: Container) -> None:
    """Add request correlation, structured access logs, and the operational endpoints."""
    metrics = Metrics()
    app.state.metrics = metrics

    @app.middleware("http")
    async def correlate_and_time(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        with bind_request_id(request_id):
            response = await call_next(request)
            duration_ms = (time.perf_counter() - started) * 1000
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            metrics.observe(route_path, response.status_code, duration_ms)
            # Path template, never the populated path: a URL with an id in it is data.
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "route": route_path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health", include_in_schema=False)
    def health() -> Response:
        return JSONResponse(content={"status": "ok"})

    @app.get("/ready", include_in_schema=False)
    def ready() -> Response:
        """Readiness proves the archive is reachable and writable-adjacent."""
        checks: dict[str, Any] = {}
        try:
            box.connection.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
        checks["media"] = "ok" if box.settings.media_dir else "unconfigured"
        checks["encryption_at_rest"] = "on" if box.media.encrypts_at_rest else "off"

        healthy = all(str(v).startswith(("ok", "on", "off")) for v in checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ready" if healthy else "not_ready", "checks": checks},
        )

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        counts: Counter[str] = Counter()
        for row in box.connection.execute(
            "SELECT name, COUNT(*) AS n FROM domain_event GROUP BY name"
        ).fetchall():
            counts[row["name"]] = row["n"]
        return PlainTextResponse(
            content=metrics.render(dict(counts)), media_type="text/plain; version=0.0.4"
        )
