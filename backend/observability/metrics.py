"""Phase 8 Prometheus metrics — module-level Counter/Histogram globals
+ pure-ASGI MetricsMiddleware + /metrics endpoint factory.

D-17 label policy: bounded labels only. NO clip_id, NO session_hash,
NO raw paths, NO GPS-derived values. The Phase 13 audit gate verifies this.

Pitfall 3: metric globals defined ONCE at module top — recreating Counter/
Histogram per-request raises `Duplicated timeseries in CollectorRegistry`.

Pitfall 4: route label reads request.scope["route"].path (templated form),
NOT request.url.path (raw — would explode cardinality with IDs).
"""

import hmac
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    REGISTRY,
    generate_latest,
)

from .. import config


# D-17 — bounded labels only. NO clip_id, NO session_hash, NO raw paths.

REQUEST_COUNT = Counter(
    "newz_http_requests_total",
    "Total HTTP requests",
    labelnames=("route", "method", "status_class"),
)

REQUEST_DURATION = Histogram(
    "newz_http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=("route", "method", "status_class"),
    # Default buckets are reasonable for a web API. Override only if Phase 13 needs.
)

STAGE_DURATION = Histogram(
    "newz_pipeline_stage_duration_seconds",
    "Pipeline stage duration in seconds",
    labelnames=("stage",),         # ingest|embed|cluster|compile|stitch
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)


def _status_class(code: int) -> str:
    """D-17: bounded status label. Returns '2xx', '3xx', '4xx', '5xx'."""
    return f"{code // 100}xx"


class MetricsMiddleware:
    """Pure ASGI middleware. Records request count + duration per
    (route, method, status_class). Pure ASGI only — see Pitfall 1.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_holder: dict = {"code": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            elapsed = time.perf_counter() - start
            # Pitfall 4 — read templated route from scope, not raw path.
            route_obj = scope.get("route")
            route = getattr(route_obj, "path", "<unmatched>") if route_obj else "<unmatched>"
            method = scope.get("method", "UNKNOWN")
            status_class = _status_class(status_holder["code"])
            REQUEST_COUNT.labels(route=route, method=method, status_class=status_class).inc()
            REQUEST_DURATION.labels(
                route=route, method=method, status_class=status_class
            ).observe(elapsed)


def make_metrics_endpoint():
    """D-09/D-10: returns a FastAPI route handler that mirrors /admin/reset auth.

    503 if config.ADMIN_TOKEN == "" (endpoint disabled).
    401 if X-Admin-Token header missing or mismatched.
    200 with Prometheus text format otherwise.

    WR-03: reads `config.ADMIN_TOKEN` per-request (NOT captured at factory call
    time). This mirrors /admin/reset behavior verbatim and survives in-process
    config reload (tests monkeypatching config.ADMIN_TOKEN, live-reload dev loops).

    CR-01: uses hmac.compare_digest for constant-time equality — defends the
    admin token against timing-side-channel attacks.
    """
    from fastapi import Header, HTTPException, Response

    async def metrics(
        x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    ) -> Response:
        admin_token = config.ADMIN_TOKEN  # WR-03 — read per-request
        if not admin_token:
            raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
        # CR-01 — constant-time compare. `not x_admin_token` short-circuit is
        # safe because the token presence (not its value) is not a secret.
        if not x_admin_token or not hmac.compare_digest(x_admin_token, admin_token):
            raise HTTPException(status_code=401, detail="invalid admin token")
        return Response(
            content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST
        )

    return metrics
