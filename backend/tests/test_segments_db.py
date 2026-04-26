"""
Tests for Phase 4 db.py segment helpers:
  - insert_segment (round-trip, conflict update)
  - set_compile_in_flight (CAS atomicity)
  - is_compile_in_flight (TTL expiry)
  - fetch_cluster_clips (ordering by ts ASC)
"""
import asyncio
import io
import time
import types
import uuid

import numpy as np
import pytest
import pytest_asyncio
from fastapi import UploadFile

from backend import config, db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH and DATA_DIR at a temporary directory; init the schema."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    new_db_path = tmp_path / "newz.db"
    monkeypatch.setattr(db, "DB_PATH", new_db_path)
    monkeypatch.setattr(db, "CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    await db.init()
    return tmp_path


def _make_cluster(cluster_id: str | None = None):
    cid = cluster_id or uuid.uuid4().hex
    rng = np.random.default_rng(42)
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


async def _insert_test_clip(tmp_path, lat=34.1, lng=-118.1, ts=1_000_000.0):
    """Insert a dummy clip and return its clip_id."""
    content = b"fake-video-bytes"
    # FastAPI 0.115 derives content_type from headers, not a direct attribute setter.
    upload = UploadFile(
        filename="test.mp4",
        file=io.BytesIO(content),
        headers={"content-type": "video/mp4"},
    )
    clip_id = await db.insert_clip(upload, lat, lng, ts, session_id=None)
    return clip_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_segment_round_trip(tmp_db):
    """insert_segment persists data; fetch_recent_segments returns it with decoded list."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    seg_id = await db.insert_segment(
        cluster_id=cluster.id,
        ordered_clip_ids=["clip-a", "clip-b"],
        caption="Test caption",
        location="Pasadena, CA",
        source_count=2,
    )
    assert seg_id is not None
    assert isinstance(seg_id, str)

    rows = await db.fetch_recent_segments(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["cluster_id"] == cluster.id
    assert isinstance(row["ordered_clip_ids"], list), "ordered_clip_ids must be decoded to list"
    assert row["ordered_clip_ids"] == ["clip-a", "clip-b"]
    assert row["caption"] == "Test caption"
    assert row["source_count"] == 2


@pytest.mark.asyncio
async def test_insert_segment_conflict_updates_existing(tmp_db):
    """Second insert for same cluster_id updates the row; only one segment remains."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    await db.insert_segment(
        cluster_id=cluster.id,
        ordered_clip_ids=["clip-1"],
        caption="Original caption",
        location="Pasadena, CA",
        source_count=1,
    )

    await db.insert_segment(
        cluster_id=cluster.id,
        ordered_clip_ids=["clip-1", "clip-2"],
        caption="Updated caption",
        location="Pasadena, CA",
        source_count=2,
    )

    rows = await db.fetch_recent_segments(limit=10)
    assert len(rows) == 1, "ON CONFLICT(cluster_id) must update, not insert a second row"
    assert rows[0]["caption"] == "Updated caption"
    assert rows[0]["ordered_clip_ids"] == ["clip-1", "clip-2"]


@pytest.mark.asyncio
async def test_set_compile_in_flight_cas_returns_true_once(tmp_db):
    """Concurrent set_compile_in_flight(True) must return True for exactly one caller."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    results = await asyncio.gather(
        db.set_compile_in_flight(cluster.id, True, ttl_seconds=30.0),
        db.set_compile_in_flight(cluster.id, True, ttl_seconds=30.0),
    )

    true_count = sum(1 for r in results if r is True)
    false_count = sum(1 for r in results if r is False)
    assert true_count == 1, f"Exactly one caller should acquire the lock, got {results}"
    assert false_count == 1, f"Second caller should get False, got {results}"


@pytest.mark.asyncio
async def test_is_compile_in_flight_expires_after_ttl(tmp_db):
    """is_compile_in_flight returns False after ttl expires."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    acquired = await db.set_compile_in_flight(cluster.id, True, ttl_seconds=0.05)
    assert acquired is True

    # Verify it's in-flight before TTL expires
    assert await db.is_compile_in_flight(cluster.id, ttl_seconds=0.05) is True

    # Wait for TTL to expire
    await asyncio.sleep(0.1)

    # Should now report as expired
    assert await db.is_compile_in_flight(cluster.id, ttl_seconds=0.05) is False


@pytest.mark.asyncio
async def test_fetch_cluster_clips_ordered_by_ts(tmp_db):
    """fetch_cluster_clips returns clips sorted by ts ASC regardless of insertion order."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    # Insert clips with ts out of order: 300, 100, 200
    clip_id_300 = await _insert_test_clip(tmp_db, ts=300.0)
    clip_id_100 = await _insert_test_clip(tmp_db, ts=100.0)
    clip_id_200 = await _insert_test_clip(tmp_db, ts=200.0)

    # Assign all to the cluster
    await db.assign_clip_to_cluster(clip_id_300, cluster.id)
    await db.assign_clip_to_cluster(clip_id_100, cluster.id)
    await db.assign_clip_to_cluster(clip_id_200, cluster.id)

    clips = await db.fetch_cluster_clips(cluster.id)
    assert len(clips) == 3
    ts_values = [c["ts"] for c in clips]
    assert ts_values == sorted(ts_values), f"Expected ASC order, got {ts_values}"
    assert ts_values[0] == 100.0
    assert ts_values[1] == 200.0
    assert ts_values[2] == 300.0


@pytest.mark.asyncio
async def test_insert_segment_persists_title(tmp_db):
    """insert_segment stores title; get_segment_for_cluster returns it."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    seg_id = await db.insert_segment(
        cluster_id=cluster.id,
        ordered_clip_ids=["p1_run_0"],
        title="Test Title",
        caption="Test Caption",
        location="Pasadena, CA",
        source_count=1,
    )
    assert seg_id is not None

    seg = await db.get_segment_for_cluster(cluster.id)
    assert seg is not None
    assert seg["title"] == "Test Title"
    assert seg["caption"] == "Test Caption"
