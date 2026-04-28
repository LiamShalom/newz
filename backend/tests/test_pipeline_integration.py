"""
Integration tests for pipeline wiring (Task 3):
  - run_pipeline chains embed_worker -> cluster_worker
  - lifespan rebuild_cache repopulates CLUSTERS from sqlite
"""

import asyncio
import io
import types
import uuid
from unittest.mock import patch

import aiosqlite
import numpy as np
import pytest
import pytest_asyncio
from fastapi import UploadFile

from backend import config, db
from backend.pipeline import cluster as cluster_mod
from backend.pipeline import embed as embed_mod
from backend.pipeline.run import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deterministic_unit_vec(key: str) -> np.ndarray:
    seed = int.from_bytes(key.encode("utf-8")[:8], "big") % (2**32)
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


def _stub_call_marengo(parent_vec_override: np.ndarray | None = None):
    """Drop-in replacement for embed._call_marengo. Returns a deterministic
    parent + 3 children at 0-3s, 3-6s, 6-9s without hitting Twelve Labs.

    parent_vec_override forces the same parent vector across calls so two clips
    can be coerced into one cluster (used by the multi-parent compile gate test).
    """
    def _stub(clip_path: str, clip_id: str):
        if parent_vec_override is not None and clip_id != "__prewarm__":
            parent_vec = parent_vec_override.copy()
        else:
            parent_vec = _deterministic_unit_vec(clip_id)
        children: list[dict] = []
        for i in range(3):
            cv = _deterministic_unit_vec(f"{clip_id}_child_{i * 3}")
            children.append({
                "start_offset_sec": float(i * 3),
                "end_offset_sec": float(i * 3 + 3),
                "vec": cv,
            })
        return parent_vec, children, 0
    return _stub


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
    monkeypatch.setattr(embed_mod, "_call_marengo", _stub_call_marengo())
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
    monkeypatch.setattr(embed_mod, "_call_marengo", _stub_call_marengo())
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


# ---------------------------------------------------------------------------
# Test 4 (Pivot 2 negative gate): solo-parent cluster — even with N children —
# must NEVER trigger compile_segment.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_solo_parent_cluster_does_not_trigger_compile(tmp_db, monkeypatch):
    """Pivot 2 gate: a single-uploader cluster — even with N children — must NEVER compile.

    Also asserts Pivot 1: child rows have cluster_id=NULL after run_pipeline.
    """
    monkeypatch.setattr(embed_mod, "_call_marengo", _stub_call_marengo())

    compile_calls: list[str] = []

    async def fake_compile(cluster_id: str) -> None:
        compile_calls.append(cluster_id)

    # Patch compile_segment AT THE IMPORT SITE inside run.py
    with patch("backend.pipeline.run.compile_segment", side_effect=fake_compile):
        clip_id = await _insert_fake_clip(tmp_db)
        await run_pipeline(clip_id)
        # Yield once so any stray asyncio.create_task can run
        await asyncio.sleep(0)

    # Cluster created
    assert len(cluster_mod.CLUSTERS) == 1
    cluster_id = next(iter(cluster_mod.CLUSTERS))
    cluster = cluster_mod.CLUSTERS[cluster_id]
    assert cluster.member_count == 1, (
        f"member_count must be 1 (one parent), got {cluster.member_count}. "
        "If this is 3 or 5, you're still counting children."
    )

    # Compile MUST NOT have been called
    assert compile_calls == [], (
        f"compile_segment was called for solo-parent cluster: {compile_calls}. "
        "Pivot 2 gate failed — multi-angle = the pitch."
    )

    # Children exist in DB but carry NO cluster_id (Pivot 1)
    children = await db.get_children_by_parent(clip_id)
    assert len(children) >= 1, "expected mock to insert at least 1 child"
    async with aiosqlite.connect(db.DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM clips "
            "WHERE parent_id IS NOT NULL AND cluster_id IS NOT NULL"
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 0, (
        f"{row[0]} child row(s) carry a cluster_id — Pivot 1 violated. "
        "Children must have cluster_id=NULL."
    )


# ---------------------------------------------------------------------------
# Test 5 (Pivot 2 positive gate): two parent uploads in same cluster -> compile
# fires exactly once.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_parents_triggers_compile(tmp_db, monkeypatch):
    """Pivot 2 gate (positive): two parent uploads in same cluster -> compile fires exactly once."""
    # Force both uploads into the same cluster by stubbing _call_marengo to return
    # the SAME parent vector for both clips. Children remain deterministic per
    # child_id so they don't collide — only the parent must match for clustering.
    fixed_parent = np.ones(512, dtype=np.float32)
    fixed_parent /= np.linalg.norm(fixed_parent)
    monkeypatch.setattr(
        embed_mod, "_call_marengo", _stub_call_marengo(parent_vec_override=fixed_parent)
    )

    compile_calls: list[str] = []

    async def fake_compile(cluster_id: str) -> None:
        compile_calls.append(cluster_id)

    with patch("backend.pipeline.run.compile_segment", side_effect=fake_compile):
        # Same lat/lng/ts so GPS+time gates pass; parent vec match so visual floor passes
        clip_a = await _insert_fake_clip(tmp_db, lat=34.1, lng=-118.1, ts=1_000_000.0)
        await run_pipeline(clip_a)
        clip_b = await _insert_fake_clip(tmp_db, lat=34.1, lng=-118.1, ts=1_000_010.0)
        await run_pipeline(clip_b)
        await asyncio.sleep(0)

    # Single cluster of size 2
    assert len(cluster_mod.CLUSTERS) == 1, f"expected 1 cluster, got {len(cluster_mod.CLUSTERS)}"
    cluster_id = next(iter(cluster_mod.CLUSTERS))
    assert cluster_mod.CLUSTERS[cluster_id].member_count == 2

    # Distinct-parent count from DB matches
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    assert parent_count == 2, f"expected 2 distinct parents, got {parent_count}"

    # Compile fired exactly once for this cluster
    assert compile_calls == [cluster_id], (
        f"expected compile_segment called once with {cluster_id}, got {compile_calls}"
    )
