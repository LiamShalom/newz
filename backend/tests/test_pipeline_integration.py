"""
Integration tests for pipeline wiring (Task 3):
  - run_pipeline chains embed_worker -> cluster_worker
  - lifespan rebuild_cache repopulates CLUSTERS from sqlite
"""

import io
import types
import uuid
from unittest.mock import AsyncMock, call, patch

import numpy as np
import pytest
import pytest_asyncio
from fastapi import UploadFile

from backend import config, db
from backend.pipeline import cluster as cluster_mod
from backend.pipeline.run import run_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    new_db_path = tmp_path / "newz.db"
    monkeypatch.setattr(db, "DB_PATH", new_db_path)
    monkeypatch.setattr(db, "CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    await db.init()
    return tmp_path


@pytest.fixture(autouse=True)
def clear_clusters():
    cluster_mod.CLUSTERS.clear()
    yield
    cluster_mod.CLUSTERS.clear()


async def _insert_fake_clip(tmp_path, lat=34.1377, lng=-118.1253, ts=1_000_000.0) -> str:
    content = b"fakemp4bytes"
    fake_file = UploadFile(
        filename="test.mp4",
        file=io.BytesIO(content),
        headers={"content-type": "video/mp4"},
    )
    return await db.insert_clip(fake_file, lat=lat, lng=lng, ts=ts, session_id=None)


# ---------------------------------------------------------------------------
# Test 1: run_pipeline creates cluster for first clip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pipeline_creates_cluster_for_first_clip(tmp_db, monkeypatch):
    """run_pipeline embeds clip then clusters it; cluster is persisted in DB."""
    monkeypatch.setattr(config, "USE_MOCK_EMBEDDINGS", True)
    clip_id = await _insert_fake_clip(tmp_db)

    broadcasts = []

    async def capture(payload):
        broadcasts.append(payload)

    with patch("backend.events.broadcast", side_effect=capture):
        await run_pipeline(clip_id)

    # One cluster created in memory
    assert len(cluster_mod.CLUSTERS) == 1, (
        f"expected 1 cluster, got {len(cluster_mod.CLUSTERS)}"
    )

    # clip.cluster_id set in DB
    clip = await db.get_clip(clip_id)
    assert clip["cluster_id"] is not None, "clip.cluster_id should be set after run_pipeline"

    # A cluster_assigned broadcast was emitted
    cluster_assigned = [e for e in broadcasts if e.get("type") == "cluster_assigned"]
    assert len(cluster_assigned) == 1
    assert cluster_assigned[0]["is_new_cluster"] is True


# ---------------------------------------------------------------------------
# Test 2: broadcast order is embedded -> cluster_assigned -> clustered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pipeline_chains_embed_then_cluster_in_order(tmp_db, monkeypatch):
    """Broadcast order: pipeline_progress(embedded) -> cluster_assigned -> pipeline_progress(clustered)."""
    monkeypatch.setattr(config, "USE_MOCK_EMBEDDINGS", True)
    clip_id = await _insert_fake_clip(tmp_db)

    event_types = []

    async def capture(payload):
        t = payload.get("type")
        if t == "pipeline_progress":
            event_types.append(f"pipeline_progress:{payload.get('stage')}")
        else:
            event_types.append(t)

    with patch("backend.events.broadcast", side_effect=capture):
        await run_pipeline(clip_id)

    assert event_types == [
        "pipeline_progress:embedded",
        "cluster_assigned",
        "pipeline_progress:clustered",
    ], f"unexpected broadcast order: {event_types}"


# ---------------------------------------------------------------------------
# Test 3: lifespan rebuilds CLUSTERS from sqlite on restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_rebuilds_cache_from_sqlite(tmp_db, monkeypatch):
    """After clearing CLUSTERS (simulating restart), rebuild_cache() repopulates from DB."""
    # Build a synthetic cluster + clip in the DB
    cid = uuid.uuid4().hex
    rng = np.random.default_rng(55)
    centroid = rng.random(512).astype(np.float32)
    centroid /= np.linalg.norm(centroid) + 1e-12
    original_blob = centroid.astype(np.float32).tobytes()

    stub_cluster = types.SimpleNamespace(
        id=cid,
        centroid=centroid,
        centroid_lat=34.1377,
        centroid_lng=-118.1253,
        median_ts=1_000_000.0,
        member_count=1,
    )
    await db.upsert_cluster(stub_cluster)

    clip_id = await _insert_fake_clip(tmp_db)
    await db.assign_clip_to_cluster(clip_id, cid)

    # Simulate process restart: clear in-memory cache
    cluster_mod.CLUSTERS.clear()
    assert len(cluster_mod.CLUSTERS) == 0

    # Rebuild from sqlite
    await cluster_mod.rebuild_cache()

    assert len(cluster_mod.CLUSTERS) == 1, (
        f"expected 1 cluster after rebuild, got {len(cluster_mod.CLUSTERS)}"
    )
    cc = cluster_mod.CLUSTERS[cid]
    assert cc.id == cid
    assert cc.member_count == 1
    assert clip_id in cc.member_ids, f"clip_id {clip_id!r} not in member_ids {cc.member_ids}"

    # Centroid bytes must match original
    rebuilt_blob = cc.centroid.astype(np.float32).tobytes()
    assert rebuilt_blob == original_blob, "rebuilt centroid does not match original"
