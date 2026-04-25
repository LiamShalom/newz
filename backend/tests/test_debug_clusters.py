"""
Tests for GET /debug/clusters route (CLU-09).

Covers:
    1. Empty CLUSTERS returns envelope with empty list (no 404)
    2. Populated CLUSTERS returns per-member score breakdown with correct fields
    3. Member with missing embedding is silently skipped (no 500)
"""

import io
import uuid

import numpy as np
import pytest
import pytest_asyncio
from fastapi import UploadFile
from fastapi.testclient import TestClient

from backend import config, db
from backend.pipeline import cluster as cluster_mod
from backend.pipeline.cluster import ClusterCache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    """Point DB at tmp_path; init schema."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    new_db_path = tmp_path / "newz.db"
    monkeypatch.setattr(db, "DB_PATH", new_db_path)
    monkeypatch.setattr(db, "CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    await db.init()
    return tmp_path


@pytest.fixture(autouse=True)
def clear_clusters():
    """Reset module-level CLUSTERS dict before each test."""
    cluster_mod.CLUSTERS.clear()
    yield
    cluster_mod.CLUSTERS.clear()


def _unit_vec(seed: int = 0, dims: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(dims).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


async def _insert_fake_clip(tmp_path, lat=34.1377, lng=-118.1253, ts=1_000_000.0) -> str:
    content = b"fakemp4bytes"
    fake_file = UploadFile(
        filename="test.mp4",
        file=io.BytesIO(content),
        headers={"content-type": "video/mp4"},
    )
    return await db.insert_clip(fake_file, lat=lat, lng=lng, ts=ts, session_id=None)


# ---------------------------------------------------------------------------
# Test 1: Empty CLUSTERS returns envelope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_debug_clusters_empty_returns_envelope(tmp_db):
    """When CLUSTERS is empty, GET /debug/clusters returns 200 with the locked JSON envelope."""
    cluster_mod.CLUSTERS.clear()

    from backend.app import app
    with TestClient(app) as client:
        r = client.get("/debug/clusters")

    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()

    # Check required top-level keys exist
    for key in ("threshold", "weights", "gps_radius_m", "time_window_s", "clusters"):
        assert key in body, f"missing key {key!r} in response: {body}"

    assert body["clusters"] == [], f"expected empty list, got {body['clusters']}"
    assert body["weights"] == {"visual": 0.55, "gps": 0.30, "time": 0.15}, (
        f"unexpected weights: {body['weights']}"
    )
    assert abs(body["threshold"] - 0.55) < 1e-6, f"unexpected threshold: {body['threshold']}"
    assert abs(body["gps_radius_m"] - 200.0) < 1e-6, (
        f"unexpected gps_radius_m: {body['gps_radius_m']}"
    )
    assert abs(body["time_window_s"] - 600.0) < 1e-6, (
        f"unexpected time_window_s: {body['time_window_s']}"
    )


# ---------------------------------------------------------------------------
# Test 2: Populated CLUSTERS returns member breakdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_debug_clusters_returns_member_breakdown(tmp_db):
    """Populated cluster: GET /debug/clusters returns per-member score breakdown with correct values."""
    lat, lng, ts = 34.1377, -118.1253, 1_000_000.0
    clip_id = await _insert_fake_clip(tmp_db, lat=lat, lng=lng, ts=ts)

    # Use a known unit vec
    v1 = _unit_vec(seed=42)
    await db.store_embedding(clip_id, v1, latency_ms=100)

    # Build a ClusterCache matching the clip exactly
    cluster = ClusterCache(
        id=uuid.uuid4().hex,
        centroid=v1.copy(),
        centroid_lat=lat,
        centroid_lng=lng,
        median_ts=ts,
        member_count=1,
        member_ids=[clip_id],
    )
    cluster_mod.CLUSTERS[cluster.id] = cluster

    from backend.app import app
    with TestClient(app) as client:
        r = client.get("/debug/clusters")

    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    clusters = body["clusters"]
    assert len(clusters) == 1, f"expected 1 cluster, got {len(clusters)}"
    c = clusters[0]
    assert c["member_count"] == 1, f"expected member_count=1, got {c['member_count']}"

    members = c["members"]
    assert len(members) == 1, f"expected 1 member, got {len(members)}"
    m = members[0]

    assert m["clip_id"] == clip_id
    assert abs(m["visual"] - 1.0) < 0.001, f"visual={m['visual']} expected ~1.0"
    assert abs(m["gps"] - 1.0) < 0.001, f"gps={m['gps']} expected ~1.0"
    assert abs(m["time"] - 1.0) < 0.001, f"time={m['time']} expected ~1.0"
    assert abs(m["composite"] - 1.0) < 0.001, f"composite={m['composite']} expected ~1.0"
    assert m["gps_available"] is True, f"gps_available should be True"
    assert m["gps_distance_m"] is not None
    assert abs(m["gps_distance_m"]) < 0.5, f"gps_distance_m={m['gps_distance_m']} expected ~0.0"
    assert abs(m["time_delta_s"]) < 0.1, f"time_delta_s={m['time_delta_s']} expected ~0.0"


# ---------------------------------------------------------------------------
# Test 3: Member with missing embedding is silently skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_debug_clusters_skips_member_with_missing_embedding(tmp_db):
    """If a member clip's embedding is not in DB, it is silently skipped — no 500."""
    clip_id = await _insert_fake_clip(tmp_db)
    # Intentionally do NOT call db.store_embedding — the embedding is missing

    cluster = ClusterCache(
        id=uuid.uuid4().hex,
        centroid=_unit_vec(seed=7),
        centroid_lat=34.1377,
        centroid_lng=-118.1253,
        median_ts=1_000_000.0,
        member_count=1,
        member_ids=[clip_id],
    )
    cluster_mod.CLUSTERS[cluster.id] = cluster

    from backend.app import app
    with TestClient(app) as client:
        r = client.get("/debug/clusters")

    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert len(body["clusters"]) == 1, f"expected 1 cluster, got {len(body['clusters'])}"
    # Member with missing embedding silently skipped
    assert body["clusters"][0]["members"] == [], (
        f"expected empty members (skipped), got {body['clusters'][0]['members']}"
    )
