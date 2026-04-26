"""Tests for backend/pipeline/compile_tools.py get_cluster_runs surface."""
import json
from unittest.mock import patch

import numpy as np
import pytest

from backend.pipeline.compile_tools import get_cluster_runs
from backend.pipeline.runs import Run


@pytest.mark.asyncio
async def test_get_cluster_runs_serializes_runs():
    fake_runs = [
        Run(
            id="p1_run_0", parent_id="p1", parent_path="/x/p1.mp4",
            start_offset_sec=0.0, end_offset_sec=6.0,
            member_child_ids=["p1_child_0", "p1_child_3"],
            vec=np.zeros(512, dtype=np.float32),
        ),
    ]
    fake_parent = {"id": "p1", "lat": 34.1, "lng": -118.1, "ts": 1700000000.0}

    async def fake_compute(cluster_id):
        return fake_runs

    async def fake_get_clip(clip_id):
        return fake_parent

    with patch("backend.pipeline.compile_tools.compute_runs_for_cluster",
               side_effect=fake_compute), \
         patch("backend.pipeline.compile_tools.db.get_clip",
               side_effect=fake_get_clip):
        # The @tool decorator wraps get_cluster_runs into an SdkMcpTool object.
        # We need to call its underlying handler. Try both shapes for robustness.
        handler = getattr(get_cluster_runs, "handler", None) or get_cluster_runs
        result = await handler({"cluster_id": "cluster-x"})

    payload = json.loads(result["content"][0]["text"])
    assert isinstance(payload, list)
    assert len(payload) == 1
    r = payload[0]
    assert r["id"] == "p1_run_0"
    assert r["parent_id"] == "p1"
    assert r["start_offset_sec"] == 0.0
    assert r["end_offset_sec"] == 6.0
    assert r["duration_sec"] == 6.0
    assert r["lat"] == 34.1
    assert r["lng"] == -118.1
    assert r["ts"] == 1700000000.0
    assert r["member_child_ids"] == ["p1_child_0", "p1_child_3"]
    assert "vec" not in r  # never leak embeddings into LLM context
