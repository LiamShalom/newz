"""Tests for backend/pipeline/compile.py::_resolve_run_ids_to_stitch_refs."""
from unittest.mock import patch

import numpy as np
import pytest

from backend.pipeline import compile as compile_mod
from backend.pipeline.runs import Run


@pytest.mark.asyncio
async def test_resolve_run_ids_to_stitch_refs():
    fake_runs = [
        Run(id="p1_run_0", parent_id="p1", parent_path="/x/p1.mp4",
            start_offset_sec=0.0, end_offset_sec=6.0,
            member_child_ids=["p1_child_0", "p1_child_3"],
            vec=np.zeros(512, dtype=np.float32)),
        Run(id="p2_run_0", parent_id="p2", parent_path="/x/p2.mp4",
            start_offset_sec=0.0, end_offset_sec=0.0,  # childless-parent sentinel
            member_child_ids=[],
            vec=np.zeros(512, dtype=np.float32)),
    ]

    async def fake_compute(cluster_id):
        return fake_runs

    with patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        refs = await compile_mod._resolve_run_ids_to_stitch_refs(
            "c1", ["p2_run_0", "p1_run_0"]  # editor reorder
        )
    # Phase 10: refs gain `headers` (None in local mode) and `run_id` keys.
    assert refs == [
        {"path": "/x/p2.mp4", "start_offset_sec": 0.0, "end_offset_sec": None,
         "headers": None, "run_id": "p2_run_0"},
        {"path": "/x/p1.mp4", "start_offset_sec": 0.0, "end_offset_sec": 6.0,
         "headers": None, "run_id": "p1_run_0"},
    ]


@pytest.mark.asyncio
async def test_resolve_run_ids_skips_unknown():
    fake_runs = [
        Run(id="p1_run_0", parent_id="p1", parent_path="/x/p1.mp4",
            start_offset_sec=0.0, end_offset_sec=3.0,
            member_child_ids=["p1_child_0"],
            vec=np.zeros(512, dtype=np.float32)),
    ]

    async def fake_compute(cluster_id):
        return fake_runs

    with patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        refs = await compile_mod._resolve_run_ids_to_stitch_refs(
            "c1", ["p1_run_0", "missing_run_0"]
        )
    assert len(refs) == 1
    assert refs[0]["path"] == "/x/p1.mp4"
