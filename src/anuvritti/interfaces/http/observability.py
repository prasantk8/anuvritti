"""Observability (PRD 53, 63.4, TASK-1103).

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
from anuvritti.interfaces.http.telemetry import REDMetrics, normalize_route

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from anuvritti.interfaces.http.container import Container

log = get_logger("access")

Metrics = REDMetrics


def install_observability(app: FastAPI, box: Container) -> None:
    """Add request correlation, structured access logs, and the operational endpoints."""
    metrics = REDMetrics()
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
            if route is not None and hasattr(route, "path"):
                normalized = normalize_route(route.path)
            elif response.status_code == 404:
                normalized = "/unmatched"
            else:
                normalized = normalize_route(request.url.path)
            metrics.observe(request.method, normalized, response.status_code, duration_ms)
            # Path template, never the populated path: a URL with an id in it is data.
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "route": normalized,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health", include_in_schema=False)
    def health() -> Response:
        return JSONResponse(content={"status": "ok"})

    @app.get("/health/ping", include_in_schema=False)
    def liveness_ping() -> Response:
        return PlainTextResponse(content="pong\n")

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
            content=metrics.render_prometheus(dict(counts)),
            media_type="text/plain; version=0.0.4",
        )
