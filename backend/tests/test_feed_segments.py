"""Phase 11 MOD-08 — soft_flag visibility in /feed JSON.

Only Phase 11's MOD-08 round-trip test survives here. The v1.0 dispatcher-era
tests in this file were retired in PR #11 alongside db_sqlite.py.

Uses main's `fresh_db` fixture (postgres-only — skips locally when
`DATABASE_URL` is unset, runs against a Neon test branch in CI).
"""
import types
import uuid
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient


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


@pytest.mark.asyncio
async def test_feed_includes_soft_flag(fresh_db, monkeypatch):
    """Phase 11 MOD-08: every segment in /feed JSON carries a soft_flag boolean.

    Seeds two segments — one with soft_flag=True, one without — via
    db.insert_segment, fetches the recent segments via the real
    fetch_recent_segments path, hits /feed, and asserts that:
      1. Every segment dict contains a `soft_flag` key.
      2. `soft_flag` is a Python bool (json.true / json.false on the wire).
      3. The flagged segment surfaces soft_flag=True; the unflagged one is False.
    """
    db = fresh_db

    flagged_cluster = _make_cluster()
    await db.upsert_cluster(flagged_cluster)
    await db.insert_segment(
        cluster_id=flagged_cluster.id,
        ordered_clip_ids=["clip-flagged"],
        caption="Soft-flagged segment",
        location="Pasadena, CA",
        source_count=1,
        soft_flag=True,
    )

    plain_cluster = _make_cluster()
    await db.upsert_cluster(plain_cluster)
    await db.insert_segment(
        cluster_id=plain_cluster.id,
        ordered_clip_ids=["clip-plain"],
        caption="Plain segment",
        location="Pasadena, CA",
        source_count=1,
        # default soft_flag=False
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
        response = client.get("/feed")

    assert response.status_code == 200
    data = response.json()
    segments = data["segments"]
    assert len(segments) >= 2, f"test setup should have seeded 2 segments, got {len(segments)}"

    # MOD-08: every segment carries soft_flag as a bool.
    for seg in segments:
        assert "soft_flag" in seg, f"segment {seg.get('id')!r} missing soft_flag (MOD-08 violation)"
        assert isinstance(seg["soft_flag"], bool), (
            f"segment {seg.get('id')!r} soft_flag must be bool, got {type(seg['soft_flag']).__name__}"
        )

    # The seeded flagged cluster must surface soft_flag=True; plain cluster False.
    by_cluster = {s["cluster_id"]: s for s in segments}
    assert by_cluster[flagged_cluster.id]["soft_flag"] is True, (
        "flagged cluster's segment did not surface soft_flag=True"
    )
    assert by_cluster[plain_cluster.id]["soft_flag"] is False, (
        "plain cluster's segment did not surface soft_flag=False"
    )
