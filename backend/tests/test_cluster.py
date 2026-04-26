"""
Tests for backend/pipeline/cluster.py
Covers: haversine, score_against, update_centroid, cluster_worker create/join.
"""

import io
import uuid
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
import pytest_asyncio
from fastapi import UploadFile

from backend import config, db
from backend.pipeline import cluster as cluster_mod
from backend.pipeline.cluster import (
    ClusterCache,
    ScoreBreakdown,
    haversine_m,
    score_against,
    update_centroid,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    """Point DB at tmp_path; init schema; patch cluster module globals."""
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


def _make_cluster(seed: int = 0, lat=None, lng=None, ts=1_000_000.0) -> ClusterCache:
    return ClusterCache(
        id=uuid.uuid4().hex,
        centroid=_unit_vec(seed),
        centroid_lat=lat,
        centroid_lng=lng,
        median_ts=ts,
        member_count=1,
        member_ids=[],
    )


async def _insert_fake_clip(tmp_path, lat=34.1377, lng=-118.1253, ts=1_000_000.0) -> str:
    content = b"fakemp4bytes"
    fake_file = UploadFile(
        filename="test.mp4",
        file=io.BytesIO(content),
        headers={"content-type": "video/mp4"},
    )
    return await db.insert_clip(fake_file, lat=lat, lng=lng, ts=ts, session_id=None)


# ---------------------------------------------------------------------------
# 1. haversine sanity
# ---------------------------------------------------------------------------

def test_haversine_zero_distance_is_zero():
    """Same lat/lng returns 0.0 (within 1e-3 meters)."""
    d = haversine_m(34.1377, -118.1253, 34.1377, -118.1253)
    assert abs(d) < 1e-3, f"expected ~0, got {d}"


def test_haversine_caltech_to_jpl_known_distance():
    """Caltech (34.1377, -118.1253) to JPL (34.2010, -118.1714) ~8218m ±300m."""
    d = haversine_m(34.1377, -118.1253, 34.2010, -118.1714)
    assert 7900 <= d <= 8500, f"expected ~8218m, got {d:.1f}m"


# ---------------------------------------------------------------------------
# 2. score_against variants
# ---------------------------------------------------------------------------

def test_score_against_full_gps_match_returns_one():
    """Perfect match (same vec, lat/lng/ts): composite ≈ 1.0, gps_available=True."""
    vec = _unit_vec(0)
    cluster = ClusterCache(
        id="c1", centroid=vec,
        centroid_lat=34.1377, centroid_lng=-118.1253,
        median_ts=1_000_000.0, member_count=1,
    )
    sb = score_against(cluster, vec, lat=34.1377, lng=-118.1253, ts=1_000_000.0)
    assert sb.gps_available is True
    assert abs(sb.visual - 1.0) < 1e-4, f"visual={sb.visual}"
    assert abs(sb.gps - 1.0) < 1e-4, f"gps={sb.gps}"
    assert abs(sb.time - 1.0) < 1e-4, f"time={sb.time}"
    assert abs(sb.composite - 1.0) < 1e-3, f"composite={sb.composite}"


def test_score_against_no_gps_collapses_to_055cos_plus_015time():
    """When lat=None, lng=None and cluster also has None GPS: gps=0, formula = 0.55*cos + 0.15*time (un-renormalized)."""
    vec = _unit_vec(0)
    cluster = ClusterCache(
        id="c1", centroid=vec,
        centroid_lat=None, centroid_lng=None,
        median_ts=1_000_000.0, member_count=1,
    )
    sb = score_against(cluster, vec, lat=None, lng=None, ts=1_000_000.0)
    assert sb.gps_available is False
    assert sb.gps == 0.0
    expected_composite = 0.55 * sb.visual + 0.15 * sb.time
    assert abs(sb.composite - expected_composite) < 1e-6, (
        f"composite={sb.composite} expected={expected_composite}"
    )


def test_score_against_partial_gps_unavailable_when_one_side_missing():
    """Clip has lat/lng but cluster centroid has None: gps still collapses to 0.0."""
    vec = _unit_vec(0)
    cluster = ClusterCache(
        id="c1", centroid=vec,
        centroid_lat=None, centroid_lng=None,  # cluster has no GPS
        median_ts=1_000_000.0, member_count=1,
    )
    sb = score_against(cluster, vec, lat=34.1377, lng=-118.1253, ts=1_000_000.0)
    assert sb.gps_available is False
    assert sb.gps == 0.0, f"expected gps=0.0, got {sb.gps}"


# ---------------------------------------------------------------------------
# 3. update_centroid
# ---------------------------------------------------------------------------

def test_update_centroid_running_mean_renormalized():
    """Running mean of e1+e2 is re-normalized to unit length, returned as float32."""
    e1 = np.zeros(512, dtype=np.float32)
    e1[0] = 1.0  # unit vector along dim 0

    e2 = np.zeros(512, dtype=np.float32)
    e2[1] = 1.0  # unit vector along dim 1

    result = update_centroid(e1, e2, new_count=2)
    assert result.dtype == np.float32, f"dtype={result.dtype}"
    assert np.allclose(np.linalg.norm(result), 1.0, atol=1e-5), (
        f"norm={np.linalg.norm(result)}"
    )
    # Direction should be along (1,1,0,...) normalized
    expected_dir = np.zeros(512, dtype=np.float32)
    expected_dir[0] = 1.0
    expected_dir[1] = 1.0
    expected_dir /= np.linalg.norm(expected_dir)
    assert np.allclose(result, expected_dir, atol=1e-5), "direction mismatch"


# ---------------------------------------------------------------------------
# 4. cluster_worker create new cluster
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cluster_worker_creates_new_cluster_when_empty(tmp_db, monkeypatch):
    """Empty CLUSTERS: cluster_worker creates a new cluster, sets clip.cluster_id in DB."""
    monkeypatch.setattr(config, "USE_MOCK_EMBEDDINGS", True)

    clip_id = await _insert_fake_clip(tmp_db)
    mock_vec = _unit_vec(seed=99)

    with patch("backend.events.broadcast", new_callable=AsyncMock) as mock_broadcast:
        returned_id = await cluster_mod.cluster_worker(clip_id, mock_vec)

    # One cluster created
    assert len(cluster_mod.CLUSTERS) == 1, f"expected 1 cluster, got {len(cluster_mod.CLUSTERS)}"
    cid = list(cluster_mod.CLUSTERS.keys())[0]
    assert returned_id == cid

    cc = cluster_mod.CLUSTERS[cid]
    assert cc.member_count == 1
    assert clip_id in cc.member_ids

    # DB persisted
    clip = await db.get_clip(clip_id)
    assert clip["cluster_id"] == cid, f"clips.cluster_id not set: {clip['cluster_id']!r}"

    # Broadcast called with is_new_cluster=True
    mock_broadcast.assert_called_once()
    payload = mock_broadcast.call_args[0][0]
    assert payload["type"] == "cluster_assigned"
    assert payload["is_new_cluster"] is True


# ---------------------------------------------------------------------------
# 5. cluster_worker join existing cluster
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cluster_worker_joins_when_above_threshold(tmp_db, monkeypatch):
    """Two clips with identical vec/GPS/ts: second clip joins the first cluster.
    Final state: 1 cluster, member_count=2, second broadcast has is_new_cluster=False.
    """
    monkeypatch.setattr(config, "USE_MOCK_EMBEDDINGS", True)

    clip1 = await _insert_fake_clip(tmp_db, lat=34.1377, lng=-118.1253, ts=1_000_000.0)
    clip2 = await _insert_fake_clip(tmp_db, lat=34.1377, lng=-118.1253, ts=1_000_000.0)

    # Use the same deterministic vec for both clips (maximum similarity)
    vec = _unit_vec(seed=7)

    broadcasts = []

    async def capture_broadcast(payload):
        broadcasts.append(payload)

    with patch("backend.events.broadcast", side_effect=capture_broadcast):
        await cluster_mod.cluster_worker(clip1, vec)
        await cluster_mod.cluster_worker(clip2, vec)

    assert len(cluster_mod.CLUSTERS) == 1, (
        f"expected 1 cluster after join, got {len(cluster_mod.CLUSTERS)}"
    )
    cc = list(cluster_mod.CLUSTERS.values())[0]
    assert cc.member_count == 2, f"expected member_count=2, got {cc.member_count}"

    # Second broadcast must have is_new_cluster=False
    cluster_assigned_events = [e for e in broadcasts if e["type"] == "cluster_assigned"]
    assert len(cluster_assigned_events) == 2
    assert cluster_assigned_events[1]["is_new_cluster"] is False, (
        f"second cluster_assigned should be join, got: {cluster_assigned_events[1]}"
    )


# ---------------------------------------------------------------------------
# 6. count_distinct_parents_in_cluster (Pivot 2 helper)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_distinct_parents_in_cluster_ignores_children(tmp_db):
    """Pivot 2 helper: counts only parent (parent_id IS NULL) rows.

    Even if a child somehow gets a cluster_id, the helper still returns the
    parent count.
    """
    cid = uuid.uuid4().hex
    # Insert a parent in the cluster
    parent_id = await _insert_fake_clip(tmp_db)
    await db.assign_clip_to_cluster(parent_id, cid)
    # Insert children referencing the parent — DO NOT assign them to the cluster
    await db.insert_child_clip(
        parent_id=parent_id, start_offset_sec=0, end_offset_sec=3,
        lat=34.1, lng=-118.1, ts=1_000_000.0, session_id=None,
    )
    await db.insert_child_clip(
        parent_id=parent_id, start_offset_sec=3, end_offset_sec=6,
        lat=34.1, lng=-118.1, ts=1_000_000.0, session_id=None,
    )
    assert await db.count_distinct_parents_in_cluster(cid) == 1

    # Defensive: even if a child leaks a cluster_id, count stays at parent count
    children = await db.get_children_by_parent(parent_id)
    await db.assign_clip_to_cluster(children[0]["id"], cid)
    assert await db.count_distinct_parents_in_cluster(cid) == 1, \
        "helper must filter parent_id IS NULL"
