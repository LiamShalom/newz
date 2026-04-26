"""
Tests for backend/pipeline/compile.py — Phase 4.6 two-branch shape.

Branch A: orchestrator chain (angle-select → editor → publisher) → stitch chosen runs.
Branch B: describe-3-children → synth caption (title arrives once M5 lands).

These tests mock at the branch-helper boundary so the orchestrator subagent
chain doesn't actually execute. The legacy vision-caption-writer test scaffolding
(query() string-vs-AsyncIterable mock, extract_cluster_keyframes, _run_agents)
is gone — those code paths were deleted in M6.4.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from backend.pipeline.runs import Run


@pytest.mark.asyncio
async def test_compile_segment_happy_path(tmp_path):
    """Both branches succeed → stitch video_url + Branch-B caption land in segment."""
    cluster_id = "cluster-xyz"
    seg_state = {
        "id": "seg-abc",
        "cluster_id": cluster_id,
        "ordered_clip_ids": '["p1_run_0"]',
        "title": "",
        "caption": "",
        "location": "Pasadena, CA",
        "source_count": 1,
        "video_url": None,
        "created_at": 1.0,
    }

    captured: dict = {}

    async def fake_get_seg(cid):
        return dict(seg_state)

    async def fake_insert(**kwargs):
        captured.update(kwargs)
        seg_state["title"] = kwargs.get("title", seg_state["title"])
        seg_state["caption"] = kwargs.get("caption", seg_state["caption"])
        seg_state["video_url"] = kwargs.get("video_url", seg_state["video_url"])
        return "seg-abc"

    async def fake_set_inflight(cid, val, ttl_seconds=None):
        return True

    async def fake_orchestrator(cid):
        return "seg-abc"

    fake_runs = [
        Run(id="p1_run_0", parent_id="p1", parent_path=str(tmp_path / "p1.mp4"),
            start_offset_sec=0.0, end_offset_sec=3.0,
            member_child_ids=["p1_child_0"],
            vec=np.zeros(512, dtype=np.float32)),
    ]
    (tmp_path / "p1.mp4").write_bytes(b"fake")

    async def fake_compute_runs(cid):
        return fake_runs

    async def fake_stitch(refs, out):
        Path(out).write_bytes(b"stitched")
        return out

    async def fake_caption(cid):
        return {"caption": "Two contributors filmed people gathering.",
                "location": "Pasadena, CA",
                "source": "vision"}

    with patch("backend.pipeline.compile._run_orchestrator_chain", side_effect=fake_orchestrator), \
         patch("backend.pipeline.compile.compute_runs_for_cluster", side_effect=fake_compute_runs), \
         patch("backend.pipeline.compile.stitch_clips", side_effect=fake_stitch), \
         patch("backend.pipeline.compile._branch_caption", side_effect=fake_caption), \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events, \
         patch("backend.pipeline.compile.config") as mock_config:

        mock_config.DATA_DIR = tmp_path
        (tmp_path / "clips").mkdir(exist_ok=True)
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = AsyncMock(side_effect=fake_insert)
        mock_db.set_compile_in_flight = AsyncMock(side_effect=fake_set_inflight)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment(cluster_id)

    assert captured.get("caption", "").startswith("Two contributors")
    video_url = captured.get("video_url", "")
    assert isinstance(video_url, str) and video_url.endswith("_compiled.mp4")
    # ordered_clip_ids should round-trip the run_ids unchanged.
    assert captured.get("ordered_clip_ids") == ["p1_run_0"]


@pytest.mark.asyncio
async def test_compile_segment_branch_a_failure_uses_fallback(tmp_path):
    """Branch A raises → _save_fallback_segment runs; Branch B caption still applied if vision."""
    cluster_id = "cluster-branch-a-fails"

    async def failing_branch_a(cid):
        raise RuntimeError("orchestrator blew up")

    async def fake_caption(cid):
        return {"caption": "fallback-caption",
                "location": "Pasadena, CA",
                "source": "vision"}

    async def fake_set_inflight(cid, val, ttl_seconds=None):
        return True

    fallback_id = "seg-fallback"

    with patch("backend.pipeline.compile._run_orchestrator_chain", side_effect=failing_branch_a), \
         patch("backend.pipeline.compile._branch_caption", side_effect=fake_caption), \
         patch("backend.pipeline.compile._save_fallback_segment",
               new_callable=AsyncMock, return_value=fallback_id) as mock_fallback, \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.get_segment_for_cluster = AsyncMock(return_value=None)
        mock_db.insert_segment = AsyncMock(return_value=fallback_id)
        mock_db.set_compile_in_flight = AsyncMock(side_effect=fake_set_inflight)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment(cluster_id)

        mock_fallback.assert_awaited_once()
        # The first arg should be the cluster_id; second arg may be None.
        call = mock_fallback.await_args
        assert call.args[0] == cluster_id
        broadcast_types = [c.args[0]["type"] for c in mock_events.broadcast.await_args_list]
        pub = next(c for c in mock_events.broadcast.await_args_list
                   if c.args[0]["type"] == "segment_published")
        assert pub.args[0]["segment_id"] == fallback_id


@pytest.mark.asyncio
async def test_no_multi_angle_template_in_fallback_paths():
    """_save_fallback_segment must NOT emit the forbidden cluster-framing template,
    and must pass title="" so the new schema row is well-formed.
    """
    captured: dict = {}
    fake_clips = [
        {"id": "c1", "path": "/tmp/c1.mp4", "lat": 34.1, "lng": -118.1, "ts": 1_700_000_000.0},
        {"id": "c2", "path": "/tmp/c2.mp4", "lat": 34.11, "lng": -118.11, "ts": 1_700_000_010.0},
    ]

    async def fake_insert_segment(**kwargs):
        captured.update(kwargs)
        return "seg-fallback-test"

    with patch("backend.pipeline.compile.db") as mock_db:
        mock_db.get_segment_for_cluster = AsyncMock(return_value=None)
        mock_db.fetch_cluster_clips = AsyncMock(return_value=fake_clips)
        mock_db.insert_segment = AsyncMock(side_effect=fake_insert_segment)

        from backend.pipeline.compile import _save_fallback_segment
        seg_id = await _save_fallback_segment("cluster-fallback-test")

        assert seg_id == "seg-fallback-test"
        caption = captured.get("caption", "")
        assert "multi-angle" not in caption.lower(), (
            f"forbidden template appeared in fallback caption: {caption!r}"
        )
        assert "Pasadena" in caption
        assert "contributor" in caption.lower()
        # Schema check: title key must be present (even if empty).
        assert "title" in captured
