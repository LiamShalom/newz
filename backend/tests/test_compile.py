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

    async def fake_trim(ref, out, *, run_id=None):
        Path(out).write_bytes(b"trimmed")
        return out

    async def fake_caption(cid):
        return {"caption": "Two contributors filmed people gathering.",
                "location": "Pasadena, CA",
                "source": "vision"}

    with patch("backend.pipeline.compile._run_orchestrator_chain", side_effect=fake_orchestrator), \
         patch("backend.pipeline.compile.compute_runs_for_cluster", side_effect=fake_compute_runs), \
         patch("backend.pipeline.compile.trim_window", side_effect=fake_trim), \
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
    # Per-run stitching: video_url is the first run's .mp4 (one file per run).
    video_url = captured.get("video_url", "")
    assert isinstance(video_url, str) and video_url.endswith("p1_run_0.mp4")
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

    async def fake_compute_runs(_cluster_id):
        # No runs available → fallback path uses parent IDs.
        return []

    with patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute_runs):
        mock_db.get_segment_for_cluster = AsyncMock(return_value=None)
        mock_db.fetch_cluster_clips = AsyncMock(return_value=fake_clips)
        mock_db.get_cluster = AsyncMock(return_value=None)
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


@pytest.mark.asyncio
async def test_enforce_parent_diversity_augments_when_only_one_parent_picked():
    """If angle-selector picks 2 runs from one parent while another parent has
    runs available, the deterministic guard should augment with the missing
    parent's earliest run."""
    from backend.pipeline.compile import _enforce_parent_diversity

    cluster_id = "c1"

    # Picked: 2 runs from p1 only. Cluster has p1 AND p2 with runs.
    seg_state = {
        "id": "seg-x",
        "cluster_id": cluster_id,
        "ordered_clip_ids": '["p1_run_0", "p1_run_1"]',
        "title": "",
        "caption": "",
        "location": "Pasadena, CA",
        "source_count": 1,
        "video_url": None,
    }

    fake_runs = [
        Run(id="p1_run_0", parent_id="p1", parent_path="/x/p1.mp4",
            start_offset_sec=0.0, end_offset_sec=6.0, member_child_ids=["p1_c0"],
            vec=np.zeros(512, dtype=np.float32)),
        Run(id="p1_run_1", parent_id="p1", parent_path="/x/p1.mp4",
            start_offset_sec=6.0, end_offset_sec=9.0, member_child_ids=["p1_c1"],
            vec=np.zeros(512, dtype=np.float32)),
        Run(id="p2_run_0", parent_id="p2", parent_path="/x/p2.mp4",
            start_offset_sec=0.0, end_offset_sec=6.0, member_child_ids=["p2_c0"],
            vec=np.zeros(512, dtype=np.float32)),
    ]
    captured: dict = {}

    async def fake_get_seg(cid):
        return dict(seg_state)

    async def fake_compute(cid):
        return fake_runs

    async def fake_insert(**kwargs):
        captured.update(kwargs)
        return seg_state["id"]

    with patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = AsyncMock(side_effect=fake_insert)
        await _enforce_parent_diversity(cluster_id, min_parents=2)

    # Augmented run should append p2_run_0; p1's two runs preserved in order.
    assert captured.get("ordered_clip_ids") == ["p1_run_0", "p1_run_1", "p2_run_0"]
    assert captured.get("source_count") == 2


@pytest.mark.asyncio
async def test_enforce_parent_diversity_noop_when_already_diverse():
    """If selection already has 2+ distinct parents, guard should not re-save."""
    from backend.pipeline.compile import _enforce_parent_diversity

    seg_state = {
        "id": "seg-x", "cluster_id": "c1",
        "ordered_clip_ids": '["p1_run_0", "p2_run_0"]',
        "title": "", "caption": "", "location": "Pasadena, CA",
        "source_count": 2, "video_url": None,
    }
    fake_runs = [
        Run(id="p1_run_0", parent_id="p1", parent_path="/x/p1.mp4",
            start_offset_sec=0.0, end_offset_sec=3.0, member_child_ids=["p1_c0"],
            vec=np.zeros(512, dtype=np.float32)),
        Run(id="p2_run_0", parent_id="p2", parent_path="/x/p2.mp4",
            start_offset_sec=0.0, end_offset_sec=3.0, member_child_ids=["p2_c0"],
            vec=np.zeros(512, dtype=np.float32)),
    ]

    async def fake_get_seg(cid):
        return dict(seg_state)

    async def fake_compute(cid):
        return fake_runs

    insert_mock = AsyncMock()

    with patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = insert_mock
        await _enforce_parent_diversity("c1", min_parents=2)

    insert_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# _enforce_runtime_budget — debug session montage-capped-at-2-clips (2026-05-01)
# ---------------------------------------------------------------------------


def _mk_run(run_id, parent_id, start, end, member_count=1):
    """Build a Run with a non-empty member_child_ids list so duration uses the
    end-start window. member_count parameterizes the synthetic vec length only;
    duration arithmetic is independent of it."""
    return Run(
        id=run_id,
        parent_id=parent_id,
        parent_path=f"/x/{parent_id}.mp4",
        start_offset_sec=float(start),
        end_offset_sec=float(end),
        member_child_ids=[f"{run_id}_c{i}" for i in range(max(1, member_count))],
        vec=np.zeros(512, dtype=np.float32),
    )


def _mk_synthetic_run(run_id, parent_id):
    """A synthetic full-parent run (member_child_ids=[]) — duration estimated."""
    return Run(
        id=run_id,
        parent_id=parent_id,
        parent_path=f"/x/{parent_id}.mp4",
        start_offset_sec=0.0,
        end_offset_sec=0.0,
        member_child_ids=[],
        vec=np.zeros(512, dtype=np.float32),
    )


@pytest.mark.asyncio
async def test_enforce_runtime_budget_extends_two_pick_to_fill_budget():
    """Angle-selector picked 2 runs (~6s total) but cluster has 4 more eligible
    runs across distinct parents. Guard should append additions in chronological
    order until the 20s budget is roughly filled."""
    from backend.pipeline.compile import _enforce_runtime_budget

    seg_state = {
        "id": "seg-rt-1", "cluster_id": "c1",
        "ordered_clip_ids": '["p1_run_0", "p2_run_0"]',
        "title": "", "caption": "", "location": "Pasadena, CA",
        "source_count": 2, "video_url": None,
    }
    # 6 runs across 6 parents, each 3s long (typical run with MAX_RUN_MEMBERS=2).
    # Picked covers the first 2 (6s); extension should add ~4 more to reach ~18s.
    fake_runs = [
        _mk_run("p1_run_0", "p1", 0.0, 3.0),
        _mk_run("p2_run_0", "p2", 0.0, 3.0),
        _mk_run("p3_run_0", "p3", 1.0, 4.0),
        _mk_run("p4_run_0", "p4", 2.0, 5.0),
        _mk_run("p5_run_0", "p5", 3.0, 6.0),
        _mk_run("p6_run_0", "p6", 4.0, 7.0),
    ]
    captured: dict = {}

    async def fake_get_seg(cid):
        return dict(seg_state)

    async def fake_compute(cid):
        return fake_runs

    async def fake_insert(**kwargs):
        captured.update(kwargs)
        return seg_state["id"]

    with patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = AsyncMock(side_effect=fake_insert)
        await _enforce_runtime_budget("c1", target_seconds=20.0)

    picked_after = captured.get("ordered_clip_ids")
    assert picked_after is not None, "guard should have re-saved the segment row"
    assert picked_after[:2] == ["p1_run_0", "p2_run_0"], "original picks preserved"
    assert len(picked_after) > 2, "guard must extend beyond the 2-pick cap"
    # Each run is 3s; 6 runs × 3s = 18s, fits under 20s budget.
    assert len(picked_after) >= 5, (
        f"expected 5+ runs to roughly fill 20s budget, got {len(picked_after)}: {picked_after}"
    )
    # Distinct parents preserved/extended.
    distinct_parents = len({rid.rsplit("_run_", 1)[0] for rid in picked_after})
    assert distinct_parents >= 2
    assert captured.get("source_count") == distinct_parents


@pytest.mark.asyncio
async def test_enforce_runtime_budget_noop_when_no_eligible_candidates():
    """Picked already covers every available run → no-op (no re-save)."""
    from backend.pipeline.compile import _enforce_runtime_budget

    seg_state = {
        "id": "seg-rt-2", "cluster_id": "c1",
        "ordered_clip_ids": '["p1_run_0", "p2_run_0"]',
        "title": "", "caption": "", "location": "Pasadena, CA",
        "source_count": 2, "video_url": None,
    }
    # Cluster has exactly 2 runs — both already picked. Nothing to extend with.
    fake_runs = [
        _mk_run("p1_run_0", "p1", 0.0, 3.0),
        _mk_run("p2_run_0", "p2", 0.0, 3.0),
    ]

    async def fake_get_seg(cid):
        return dict(seg_state)

    async def fake_compute(cid):
        return fake_runs

    insert_mock = AsyncMock()
    with patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = insert_mock
        await _enforce_runtime_budget("c1", target_seconds=20.0)

    insert_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_enforce_runtime_budget_trims_when_over_budget_preserves_two_parents():
    """Picked totals 30s across 5 runs from 5 parents → trim trailing runs
    while preserving ≥2 distinct parents."""
    from backend.pipeline.compile import _enforce_runtime_budget

    # 5 runs × 6s = 30s — over the 20s budget.
    seg_state = {
        "id": "seg-rt-3", "cluster_id": "c1",
        "ordered_clip_ids": (
            '["p1_run_0", "p2_run_0", "p3_run_0", "p4_run_0", "p5_run_0"]'
        ),
        "title": "", "caption": "", "location": "Pasadena, CA",
        "source_count": 5, "video_url": None,
    }
    fake_runs = [
        _mk_run("p1_run_0", "p1", 0.0, 6.0),
        _mk_run("p2_run_0", "p2", 0.0, 6.0),
        _mk_run("p3_run_0", "p3", 0.0, 6.0),
        _mk_run("p4_run_0", "p4", 0.0, 6.0),
        _mk_run("p5_run_0", "p5", 0.0, 6.0),
    ]
    captured: dict = {}

    async def fake_get_seg(cid):
        return dict(seg_state)

    async def fake_compute(cid):
        return fake_runs

    async def fake_insert(**kwargs):
        captured.update(kwargs)
        return seg_state["id"]

    with patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = AsyncMock(side_effect=fake_insert)
        await _enforce_runtime_budget("c1", target_seconds=20.0)

    picked_after = captured.get("ordered_clip_ids")
    assert picked_after is not None, "guard should have re-saved (over-budget trim)"
    # 6s per run × 3 runs = 18s, ≤ 20s. 4 runs would be 24s, > 20s.
    assert len(picked_after) == 3, (
        f"expected 3 runs after trim, got {len(picked_after)}: {picked_after}"
    )
    distinct_parents = len({rid.rsplit("_run_", 1)[0] for rid in picked_after})
    assert distinct_parents >= 2, "must preserve parent-diversity floor"


@pytest.mark.asyncio
async def test_enforce_runtime_budget_noop_when_picks_empty():
    """No picks → guard no-ops (no DB read of cluster runs, no re-save)."""
    from backend.pipeline.compile import _enforce_runtime_budget

    seg_state = {
        "id": "seg-rt-4", "cluster_id": "c1",
        "ordered_clip_ids": "[]",
        "title": "", "caption": "", "location": "Pasadena, CA",
        "source_count": 0, "video_url": None,
    }

    async def fake_get_seg(cid):
        return dict(seg_state)

    insert_mock = AsyncMock()
    with patch("backend.pipeline.compile.db") as mock_db:
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = insert_mock
        await _enforce_runtime_budget("c1", target_seconds=20.0)

    insert_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_enforce_runtime_budget_handles_synthetic_full_parent_runs():
    """Synthetic full-parent runs (member_child_ids=[]) use the estimate.
    Picked has 1 normal (3s) + 1 synthetic (estimated 6s); 9s used → 11s
    remaining. Only candidate left is another synthetic (6s) which fits."""
    from backend.pipeline.compile import _enforce_runtime_budget

    seg_state = {
        "id": "seg-rt-5", "cluster_id": "c1",
        "ordered_clip_ids": '["p1_run_0", "p2_run_0"]',
        "title": "", "caption": "", "location": "Pasadena, CA",
        "source_count": 2, "video_url": None,
    }
    fake_runs = [
        _mk_run("p1_run_0", "p1", 0.0, 3.0),       # 3s
        _mk_synthetic_run("p2_run_0", "p2"),        # estimate 6s
        _mk_synthetic_run("p3_run_0", "p3"),        # estimate 6s — extension candidate
    ]
    captured: dict = {}

    async def fake_get_seg(cid):
        return dict(seg_state)

    async def fake_compute(cid):
        return fake_runs

    async def fake_insert(**kwargs):
        captured.update(kwargs)
        return seg_state["id"]

    with patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.compute_runs_for_cluster",
               side_effect=fake_compute):
        mock_db.get_segment_for_cluster = AsyncMock(side_effect=fake_get_seg)
        mock_db.insert_segment = AsyncMock(side_effect=fake_insert)
        await _enforce_runtime_budget(
            "c1", target_seconds=20.0, synthetic_run_estimate_sec=6.0,
        )

    picked_after = captured.get("ordered_clip_ids")
    assert picked_after is not None, "guard should extend with the synthetic candidate"
    assert "p3_run_0" in picked_after, "synthetic candidate should be appended"
    assert len(picked_after) == 3
