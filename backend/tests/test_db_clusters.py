"""
Tests for backend/db.py cluster helpers:
  - upsert_cluster
  - get_all_clusters
  - assign_clip_to_cluster
"""

import io
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


def _make_cluster(cluster_id: str | None = None, vec: np.ndarray | None = None):
    """Return a SimpleNamespace duck-typed as ClusterCache."""
    cid = cluster_id or uuid.uuid4().hex
    if vec is None:
        rng = np.random.default_rng(42)
        v = rng.random(512).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-12
    else:
        v = vec
    return types.SimpleNamespace(
        id=cid,
        centroid=v,
        centroid_lat=34.1377,
        centroid_lng=-118.1253,
        median_ts=1_000_000.0,
        member_count=1,
    )


async def _insert_fake_clip(tmp_path) -> str:
    """Insert a minimal fake clip and return its clip_id."""
    content = b"fakemp4bytes"
    # Pass content-type via headers dict so UploadFile.content_type is set correctly
    # (FastAPI 0.115 derives content_type from headers, not a direct attribute setter).
    fake_file = UploadFile(
        filename="test.mp4",
        file=io.BytesIO(content),
        headers={"content-type": "video/mp4"},
    )
    clip_id = await db.insert_clip(fake_file, lat=34.1377, lng=-118.1253, ts=1_000_000.0, session_id=None)
    return clip_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_then_get_all_clusters_roundtrip(tmp_db):
    """Upsert one cluster; get_all_clusters returns it with byte-identical centroid."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    rows = await db.get_all_clusters()
    assert len(rows) == 1, f"expected 1 cluster, got {len(rows)}"

    row = rows[0]
    assert row["id"] == cluster.id
    # Reconstitute centroid from BLOB and compare
    recovered = np.frombuffer(row["centroid"], dtype=np.float32).copy()
    assert np.array_equal(recovered, cluster.centroid), "centroid roundtrip mismatch"
    assert row["member_ids"] == [], f"expected empty member_ids, got {row['member_ids']}"


@pytest.mark.asyncio
async def test_upsert_idempotent_updates_existing_row(tmp_db):
    """Upserting the same cluster_id twice replaces the row (second centroid wins)."""
    cid = uuid.uuid4().hex
    rng = np.random.default_rng(1)
    vec1 = rng.random(512).astype(np.float32)
    vec1 /= np.linalg.norm(vec1) + 1e-12

    rng2 = np.random.default_rng(2)
    vec2 = rng2.random(512).astype(np.float32)
    vec2 /= np.linalg.norm(vec2) + 1e-12

    cluster1 = types.SimpleNamespace(
        id=cid, centroid=vec1, centroid_lat=34.0, centroid_lng=-118.0,
        median_ts=1_000_000.0, member_count=1
    )
    cluster2 = types.SimpleNamespace(
        id=cid, centroid=vec2, centroid_lat=34.1, centroid_lng=-118.1,
        median_ts=1_000_001.0, member_count=2
    )

    await db.upsert_cluster(cluster1)
    await db.upsert_cluster(cluster2)

    rows = await db.get_all_clusters()
    assert len(rows) == 1, "idempotent upsert should yield exactly one row"
    recovered = np.frombuffer(rows[0]["centroid"], dtype=np.float32).copy()
    assert np.array_equal(recovered, vec2), "second upsert should replace centroid"
    assert rows[0]["member_count"] == 2


@pytest.mark.asyncio
async def test_assign_clip_to_cluster_sets_column(tmp_db):
    """assign_clip_to_cluster sets clips.cluster_id; get_all_clusters includes it in member_ids."""
    cluster = _make_cluster()
    await db.upsert_cluster(cluster)

    clip_id = await _insert_fake_clip(tmp_db)
    await db.assign_clip_to_cluster(clip_id, cluster.id)

    rows = await db.get_all_clusters()
    assert len(rows) == 1
    assert clip_id in rows[0]["member_ids"], (
        f"expected {clip_id} in member_ids, got {rows[0]['member_ids']}"
    )


@pytest.mark.asyncio
async def test_get_all_clusters_empty_returns_empty_list(tmp_db):
    """Fresh DB with no clusters returns an empty list (not None, not an exception)."""
    result = await db.get_all_clusters()
    assert result == [], f"expected [], got {result!r}"
