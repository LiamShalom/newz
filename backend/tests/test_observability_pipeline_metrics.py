"""Stage timing integration tests — STAGE_DURATION samples flow through /metrics.

Locks T-08-15 (cardinality drift) by scanning /metrics output for stage values
outside the D-17 enum {ingest, embed, cluster, compile, stitch}.

Locks the OBS-04 success criterion (pipeline-stage histograms) by sending a
real POST /clips and confirming a STAGE_DURATION{stage="ingest"} histogram
sample appears in /metrics afterwards.
"""
import importlib
import io
import re
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend import config


# D-17 — locked enum of allowed stage label values.
ALLOWED_STAGES = {"ingest", "embed", "cluster", "compile", "stitch"}


def _boot_app():
    """Boot backend.app under mocked lifespan side-effects.

    Mirror of backend/tests/test_observability_metrics.py._boot_app — forces a
    fresh re-import so the /metrics route handler closure captures the CURRENT
    value of config.ADMIN_TOKEN. The factory `make_metrics_endpoint(...)`
    reads the value at app-import time; sticky module cache from a previous
    test would otherwise lock in the first-seen ADMIN_TOKEN.
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


def test_stage_duration_metric_registered_with_stage_label(client_with_token):
    """STAGE_DURATION exposes a single 'stage' label (D-17)."""
    from backend.observability.metrics import STAGE_DURATION
    assert STAGE_DURATION._labelnames == ("stage",)


def test_metrics_output_only_uses_allowed_stage_values(client_with_token):
    """T-08-15 — every stage="..." in /metrics output must be in the D-17 enum.

    Defends against typos like stage="ingestion" or stage="embed_v2" silently
    polluting Prometheus cardinality. Empty set is fine (no false positive
    if no stage samples have been recorded yet in this test session).
    """
    # Hit a known route so /metrics has request samples; not strictly required
    # to populate stage samples, but exercises the middleware path.
    client_with_token.get("/health")
    resp = client_with_token.get(
        "/metrics", headers={"X-Admin-Token": "secret-token"}
    )
    assert resp.status_code == 200
    body = resp.text
    stage_values = set(re.findall(r'stage="([^"]+)"', body))
    unexpected = stage_values - ALLOWED_STAGES
    assert not unexpected, (
        f"unexpected stage values in /metrics: {unexpected} "
        f"(D-17 enum forbids these)"
    )


def test_ingest_stage_emits_sample_on_clip_post(client_with_token, tmp_path, monkeypatch):
    """A successful POST /clips records a STAGE_DURATION{stage='ingest'} sample.

    Mocks db.insert_clip + run_pipeline + events.broadcast to keep this test
    isolated from real sqlite/Marengo. The real value is asserting the
    `STAGE_DURATION.labels(stage="ingest").time()` wrap actually fires when
    the route handler executes.
    """
    # Point DATA_DIR at tmp + create the clips dir
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)

    async def _fake_insert_clip(*args, **kwargs):
        return "fake-clip-id"

    async def _fake_broadcast(*args, **kwargs):
        return None

    # Patch on backend.app's view of `db` and `events` (imported via `from . import db, events`).
    monkeypatch.setattr("backend.app.db.insert_clip", _fake_insert_clip)
    monkeypatch.setattr("backend.app.events.broadcast", _fake_broadcast)
    monkeypatch.setattr("backend.app.run_pipeline", AsyncMock(return_value=None))

    files = {"file": ("test.mp4", io.BytesIO(b"fakecontent"), "video/mp4")}
    data = {"lat": "34.1", "lng": "-118.1", "ts": "1700000000.0"}
    resp = client_with_token.post(
        "/clips", files=files, data=data,
        headers={"X-Session-Id": "test-session"},
    )
    # Route is declared status_code=202
    assert resp.status_code == 202, f"unexpected status: {resp.status_code} body={resp.text}"

    scrape = client_with_token.get(
        "/metrics", headers={"X-Admin-Token": "secret-token"}
    )
    body = scrape.text
    # Histogram exposition format: newz_pipeline_stage_duration_seconds_count{stage="ingest"} <N>
    assert re.search(
        r'newz_pipeline_stage_duration_seconds_count\{[^}]*stage="ingest"',
        body,
    ), f'no ingest histogram count line in /metrics output:\n{body[:800]}'
