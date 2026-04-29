"""Integration tests for XFFStrip + RequestIDAndContextvarsBind middleware.

These tests prove the central PRIV-01/PRIV-02 contracts:
- XFF + alts are stripped before route handlers see them
- structlog contextvars bound in middleware are visible inside route handlers
  (this is the canonical proof that pure-ASGI middleware works correctly,
   per RESEARCH.md Pitfall 1 — the stdlib base-middleware approach silently
   breaks this contract)
"""
import hashlib
import json
import logging
import re
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from fastapi import Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse


def _boot_app_with_debug_routes():
    """Boot backend.app under mocks; install test-only debug routes that
    echo request.headers and current contextvars. Returns (app, client)."""
    with patch("backend.app.db.init", new_callable=AsyncMock), \
         patch("backend.pipeline.cluster.rebuild_cache", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_marengo", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_sdk", new_callable=AsyncMock):
        from backend.app import app

        async def echo_headers(request: Request):
            # dict comprehension preserves all headers seen by the handler
            return JSONResponse({"headers": dict(request.headers)})

        async def echo_contextvars(request: Request):
            return JSONResponse({
                "contextvars": dict(structlog.contextvars.get_contextvars()),
            })

        # Register debug routes if not already present (test isolation safe)
        existing = {getattr(r, "path", None) for r in app.routes}
        if "/test/echo-headers" not in existing:
            app.add_api_route("/test/echo-headers", echo_headers, methods=["GET"])
        if "/test/echo-contextvars" not in existing:
            app.add_api_route("/test/echo-contextvars", echo_contextvars, methods=["GET"])

        return app, TestClient(app, raise_server_exceptions=True)


FORBIDDEN_HEADERS = [
    "X-Forwarded-For",
    "X-Real-IP",
    "Forwarded",
    "True-Client-IP",
    "CF-Connecting-IP",
    "X-Client-IP",
]


def test_xff_stripped_before_route_handler():
    _, client = _boot_app_with_debug_routes()
    resp = client.get("/test/echo-headers", headers={"X-Forwarded-For": "1.2.3.4"})
    assert resp.status_code == 200
    body = resp.json()
    echoed = {k.lower() for k in body["headers"].keys()}
    assert "x-forwarded-for" not in echoed
    assert "1.2.3.4" not in resp.text


@pytest.mark.parametrize("header", FORBIDDEN_HEADERS)
def test_xff_strips_all_forbidden_variants(header):
    _, client = _boot_app_with_debug_routes()
    resp = client.get("/test/echo-headers", headers={header: "9.9.9.9"})
    assert resp.status_code == 200
    echoed = {k.lower() for k in resp.json()["headers"].keys()}
    assert header.lower() not in echoed, f"{header} not stripped"
    assert "9.9.9.9" not in resp.text


def test_request_id_bound_in_context():
    _, client = _boot_app_with_debug_routes()
    resp = client.get("/test/echo-contextvars")
    assert resp.status_code == 200
    ctx = resp.json()["contextvars"]
    assert "request_id" in ctx
    # UUID4.hex is 32 lowercase hex chars
    assert re.fullmatch(r"[0-9a-f]{32}", ctx["request_id"]), ctx["request_id"]


def test_session_hash_bound_when_x_session_id_header_present():
    _, client = _boot_app_with_debug_routes()
    session_uuid = "test-session-uuid-known"
    expected = hashlib.sha256(session_uuid.encode("utf-8")).hexdigest()
    resp = client.get("/test/echo-contextvars",
                      headers={"X-Session-Id": session_uuid})
    ctx = resp.json()["contextvars"]
    assert ctx.get("session_hash") == expected
    # PRIV-02 invariant — raw uuid never bound
    assert "session_uuid" not in ctx
    assert session_uuid not in json.dumps(ctx)


def test_session_uuid_never_appears_in_logs(caplog):
    # Even with X-Session-Id present, the raw UUID must NEVER appear in
    # any log output (PRIV-02 contract — only the sha256 hash is bound).
    _, client = _boot_app_with_debug_routes()
    secret = "do-not-log-this-uuid-XYZ"
    with caplog.at_level(logging.INFO):
        client.get("/test/echo-contextvars", headers={"X-Session-Id": secret})
    for record in caplog.records:
        assert secret not in record.getMessage()
        for k, v in (record.__dict__ or {}).items():
            if isinstance(v, str):
                assert secret not in v, f"raw uuid leaked via log attr {k}"


def test_contextvars_cleared_after_request():
    _, client = _boot_app_with_debug_routes()
    # First request — bind a session_hash
    r1 = client.get("/test/echo-contextvars",
                    headers={"X-Session-Id": "first-session"})
    h1 = r1.json()["contextvars"].get("session_hash")
    assert h1 is not None
    # Second request — no X-Session-Id; session_hash MUST not leak from r1
    r2 = client.get("/test/echo-contextvars")
    ctx2 = r2.json()["contextvars"]
    assert "session_hash" not in ctx2 or ctx2["session_hash"] != h1


def test_middleware_order_xff_outermost_then_request_id_then_metrics_then_cors():
    # FastAPI applies middleware in REVERSE-add-order.
    # In `app.user_middleware`, later-added comes FIRST in the list.
    # We added in code order: CORS, Metrics, RequestID, XFFStrip.
    # So `user_middleware[0]` should be XFFStrip (outermost = runs first).
    from backend.app import app
    names = [m.cls.__name__ for m in app.user_middleware]
    # Trim to the four we care about
    for required in ("XFFStrip", "RequestIDAndContextvarsBind",
                     "MetricsMiddleware", "CORSMiddleware"):
        assert required in names, f"{required} not registered"
    assert names.index("XFFStrip") < names.index("RequestIDAndContextvarsBind"), \
        "XFFStrip must be outermost (D-12)"
    assert names.index("RequestIDAndContextvarsBind") < names.index("MetricsMiddleware"), \
        "RequestIDAndContextvarsBind must wrap MetricsMiddleware (D-12)"
    assert names.index("MetricsMiddleware") < names.index("CORSMiddleware"), \
        "MetricsMiddleware must wrap CORSMiddleware (D-12)"
