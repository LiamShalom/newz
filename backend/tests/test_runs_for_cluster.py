"""Tests for compute_runs_for_cluster — DB-backed run computation."""
from unittest.mock import patch

import numpy as np
import pytest

from backend.pipeline.runs import compute_runs_for_cluster


def _unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


@pytest.mark.asyncio
async def test_compute_runs_for_cluster_groups_by_parent():
    a = _unit(1)

    fake_rows = [
        # parent p1 (no offsets, parent_id is None on parent rows)
        {"id": "p1", "parent_id": None, "parent_path": "/x/p1.mp4",
         "start_offset_sec": None, "end_offset_sec": None,
         "lat": 0, "lng": 0, "ts": 0, "path": "/x/p1.mp4"},
        # children of p1
        {"id": "p1_child_0", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 0.0, "end_offset_sec": 3.0,
         "lat": 0, "lng": 0, "ts": 0, "path": ""},
        {"id": "p1_child_3", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 3.0, "end_offset_sec": 6.0,
         "lat": 0, "lng": 0, "ts": 0, "path": ""},
    ]
    fake_vecs = {"p1_child_0": a, "p1_child_3": a, "p1": a}

    async def fake_fetch(cluster_id):
        return fake_rows

    async def fake_get_embedding(clip_id):
        return fake_vecs.get(clip_id)

    with patch("backend.pipeline.runs.db.fetch_cluster_clips_with_children",
               side_effect=fake_fetch), \
         patch("backend.pipeline.runs.db.get_embedding",
               side_effect=fake_get_embedding):
        runs = await compute_runs_for_cluster("cluster-x")

    assert len(runs) == 1
    assert runs[0].id == "p1_run_0"
    assert runs[0].parent_id == "p1"
    assert runs[0].member_child_ids == ["p1_child_0", "p1_child_3"]


@pytest.mark.asyncio
async def test_compute_runs_synthesizes_run_for_childless_parent():
    a = _unit(2)
    fake_rows = [
        {"id": "p2", "parent_id": None, "parent_path": "/x/p2.mp4",
         "start_offset_sec": None, "end_offset_sec": None,
         "lat": 0, "lng": 0, "ts": 0, "path": "/x/p2.mp4"},
    ]
    fake_vecs = {"p2": a}

    async def fake_fetch(cluster_id):
        return fake_rows

    async def fake_get_embedding(clip_id):
        return fake_vecs.get(clip_id)

    with patch("backend.pipeline.runs.db.fetch_cluster_clips_with_children",
               side_effect=fake_fetch), \
         patch("backend.pipeline.runs.db.get_embedding",
               side_effect=fake_get_embedding):
        runs = await compute_runs_for_cluster("cluster-y")
    assert len(runs) == 1
    assert runs[0].id == "p2_run_0"
    assert runs[0].parent_id == "p2"
    assert runs[0].member_child_ids == []
    assert runs[0].parent_path == "/x/p2.mp4"
