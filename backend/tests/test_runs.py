"""Tests for backend/pipeline/runs.py — run detection over child clips."""
import numpy as np
import pytest

from backend.pipeline.runs import find_runs, Run


def _unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


def test_find_runs_module_imports():
    """Sanity: the public surface exists."""
    assert callable(find_runs)
    assert Run is not None


def test_one_parent_all_similar_collapses_to_one_run():
    base = _unit(42)
    # tiny perturbations -> high cosine
    def jitter(v, n):
        rng = np.random.default_rng(n)
        out = v + 0.01 * rng.random(512).astype(np.float32)
        out /= np.linalg.norm(out) + 1e-12
        return out

    children = [
        {"id": "p1_child_0", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 0.0, "end_offset_sec": 3.0, "vec": jitter(base, 1)},
        {"id": "p1_child_3", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 3.0, "end_offset_sec": 6.0, "vec": jitter(base, 2)},
        {"id": "p1_child_6", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 6.0, "end_offset_sec": 9.0, "vec": jitter(base, 3)},
    ]
    runs = find_runs(children, threshold=0.85)
    assert len(runs) == 1
    r = runs[0]
    assert r.id == "p1_run_0"
    assert r.parent_id == "p1"
    assert r.parent_path == "/x/p1.mp4"
    assert r.start_offset_sec == 0.0
    assert r.end_offset_sec == 9.0
    assert r.member_child_ids == ["p1_child_0", "p1_child_3", "p1_child_6"]
    assert r.vec.shape == (512,)
    assert abs(np.linalg.norm(r.vec) - 1.0) < 1e-5


def test_scene_cut_splits_into_two_runs():
    a, b = _unit(1), _unit(99)  # orthogonal-ish -> cosine << 0.85
    children = [
        {"id": "p1_child_0", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 0.0, "end_offset_sec": 3.0, "vec": a},
        {"id": "p1_child_3", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 3.0, "end_offset_sec": 6.0, "vec": a},
        {"id": "p1_child_6", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 6.0, "end_offset_sec": 9.0, "vec": b},  # cut here
        {"id": "p1_child_9", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 9.0, "end_offset_sec": 12.0, "vec": b},
    ]
    runs = find_runs(children, threshold=0.85)
    assert len(runs) == 2
    assert runs[0].id == "p1_run_0"
    assert runs[0].end_offset_sec == 6.0
    assert runs[0].member_child_ids == ["p1_child_0", "p1_child_3"]
    assert runs[1].id == "p1_run_1"
    assert runs[1].start_offset_sec == 6.0
    assert runs[1].end_offset_sec == 12.0


def test_multiple_parents_independent_runs():
    a = _unit(7)
    children = [
        {"id": "p1_child_0", "parent_id": "p1", "parent_path": "/x/p1.mp4",
         "start_offset_sec": 0.0, "end_offset_sec": 3.0, "vec": a},
        {"id": "p2_child_0", "parent_id": "p2", "parent_path": "/x/p2.mp4",
         "start_offset_sec": 0.0, "end_offset_sec": 3.0, "vec": a},
    ]
    runs = find_runs(children, threshold=0.85)
    assert {r.id for r in runs} == {"p1_run_0", "p2_run_0"}
    assert {r.parent_id for r in runs} == {"p1", "p2"}
