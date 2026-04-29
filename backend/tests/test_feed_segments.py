"""
Tests for GET /feed endpoint — returns segments (not clips), with proximity sort.
"""
import asyncio
import io
import types
import uuid
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend import config, db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH and DATA_DIR at a temporary directory; init schema."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    new_db_path = tmp_path / "newz.db"
    monkeypatch.setattr(db, "DB_PATH", new_db_path)
    monkeypatch.setattr(db, "CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    await db.init()
    return tmp_path


def _make_cluster(cluster_id: str | None = None):
    cid = cluster_id or uuid.uuid4().hex
    rng = np.random.default_rng(99)
    v = rng.random(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return types.SimpleNamespace(
        id=cid,
        centroid=v,
        centroid_lat=34.1377,
        centroid_lng=-118.1253,
        median_ts=1_000_000.0,
        member_count=2,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_feed_returns_segments_key(tmp_db, monkeypatch):
    """GET /feed must return {"segments": [...]} not {"clips": [...]}."""
    # Insert a cluster and segment directly via db helpers
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)
    await db.insert_segment(
        cluster_id=cluster.id,
        ordered_clip_ids=["clip-1", "clip-2"],
        caption="Test segment caption",
        location="Pasadena, CA",
        source_count=2,
    )

    # Import app after monkeypatching db so it uses the tmp db
    # Patch lifespan to skip real startup side-effects
    with patch("backend.app.db.init", new_callable=AsyncMock), \
         patch("backend.app.db.fetch_recent_segments",
               new_callable=AsyncMock,
               return_value=await db.fetch_recent_segments(limit=50)), \
         patch("backend.pipeline.cluster.rebuild_cache", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_marengo", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_sdk", new_callable=AsyncMock):

        from backend.app import app
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/feed")

    assert response.status_code == 200
    data = response.json()
    assert "segments" in data, f"Expected 'segments' key, got {list(data.keys())}"
    assert "clips" not in data, "Old 'clips' key must not be present in /feed response"
    assert len(data["segments"]) >= 1


@pytest.mark.asyncio
async def test_feed_with_lat_lng_returns_segments(tmp_db, monkeypatch):
    """GET /feed?lat=34.1&lng=-118.1 returns segments (proximity sort active)."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)
    await db.insert_segment(
        cluster_id=cluster.id,
        ordered_clip_ids=["clip-1"],
        caption="Proximity test",
        location="Pasadena, CA",
        source_count=1,
    )

    segs = await db.fetch_recent_segments(limit=50)

    with patch("backend.app.db.init", new_callable=AsyncMock), \
         patch("backend.app.db.fetch_recent_segments",
               new_callable=AsyncMock, return_value=segs), \
         patch("backend.pipeline.cluster.rebuild_cache", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_marengo", new_callable=AsyncMock), \
         patch("backend.app._pre_warm_sdk", new_callable=AsyncMock):

        from backend.app import app
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/feed?lat=34.1&lng=-118.1")

    assert response.status_code == 200
    data = response.json()
    assert "segments" in data
    assert len(data["segments"]) >= 1
