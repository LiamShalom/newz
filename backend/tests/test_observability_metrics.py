"""Integration tests for /metrics endpoint — auth (verbatim mirror of /admin/reset),
Prometheus text format, route-template label policy, forbidden-label policy."""
import importlib
import re
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend import config


def _boot_app():
    """Boot backend.app under mocked lifespan side-effects.

    Forces a fresh re-import of backend.app so the /metrics route handler
    closure captures the CURRENT value of config.ADMIN_TOKEN (the factory
    `make_metrics_endpoint(config.ADMIN_TOKEN)` reads the value at app-import
    time). Without the reload, sticky module cache from a previous test
    would lock in the first-seen ADMIN_TOKEN value.
    """
    with patch("backend.app.db.init", new_callable=AsyncMock), \
         patch("backend.pipeline.cluster.rebuild_cache", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_marengo", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_sdk", new_callable=AsyncMock):
        import backend.app as backend_app
        backend_app = importlib.reload(backend_app)
        return TestClient(backend_app.app, raise_server_exceptions=True)


@pytest.fixture
def client_with_token(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "secret-token")
    return _boot_app()


@pytest.fixture
def client_no_token(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    return _boot_app()


def test_metrics_returns_503_when_admin_token_unset(client_no_token):
    # The route is constructed at import time bound to config.ADMIN_TOKEN's
    # current value. _boot_app reloads backend.app AFTER monkeypatch sets
    # ADMIN_TOKEN="", so the route handler closure sees "".
    resp = client_no_token.get("/metrics")
    assert resp.status_code == 503


def test_metrics_returns_401_without_token(client_with_token):
    resp = client_with_token.get("/metrics")
    assert resp.status_code == 401


def test_metrics_returns_401_with_wrong_token(client_with_token):
    resp = client_with_token.get("/metrics", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_metrics_returns_prometheus_text_format(client_with_token):
    resp = client_with_token.get("/metrics", headers={"X-Admin-Token": "secret-token"})
    assert resp.status_code == 200
    ctype = resp.headers.get("content-type", "")
    assert ctype.startswith("text/plain")
    assert "version=" in ctype
    # The Counter / Histogram metric names from observability/metrics.py
    body = resp.text
    assert "newz_http_requests_total" in body
    assert "newz_http_request_duration_seconds" in body
    assert "newz_pipeline_stage_duration_seconds" in body


def test_metrics_route_label_uses_template_not_raw(client_with_token):
    # Generate request traffic on a known-route (/health), then scrape /metrics.
    for _ in range(3):
        client_with_token.get("/health")
    resp = client_with_token.get("/metrics", headers={"X-Admin-Token": "secret-token"})
    body = resp.text
    # Templated route appears as a label value
    assert 'route="/health"' in body or 'route="/metrics"' in body or 'route="<unmatched>"' in body
    # Forbidden label keys (D-17) must NEVER appear
    for forbidden in ("clip_id=", "session_uuid=", "session_hash="):
        assert forbidden not in body, f"forbidden label {forbidden} present in /metrics output"


def test_metrics_only_bounded_label_keys(client_with_token):
    # Hit a known route so REQUEST_COUNT has at least one labelled time series
    client_with_token.get("/health")
    resp = client_with_token.get("/metrics", headers={"X-Admin-Token": "secret-token"})
    body = resp.text
    # The four allowed label keys (D-17): route, method, status_class, stage
    # Anything else (cardinality risk) is forbidden.
    # Scan label clauses ONLY for the newz_* metrics we own. Built-in
    # prometheus-client metrics (python_info, process_*, python_gc_*) have
    # static low-cardinality labels (major/minor/version/implementation/etc.)
    # that are not cardinality risks and are out of scope for D-17 enforcement.
    line_pattern = re.compile(r'^(newz_[a-z0-9_]+)\{([^}]*)\}')
    seen_keys = set()
    for line in body.splitlines():
        m = line_pattern.match(line)
        if not m:
            continue
        clause = m.group(2)
        for kv in clause.split(","):
            if "=" in kv:
                key = kv.strip().split("=", 1)[0]
                seen_keys.add(key)
    allowed = {"route", "method", "status_class", "stage", "le", "quantile"}
    # `le` and `quantile` are stdlib Prometheus histogram bucket / summary labels — allowed.
    unexpected = seen_keys - allowed
    assert not unexpected, f"unexpected metric labels on newz_* metrics (cardinality risk): {unexpected}"
