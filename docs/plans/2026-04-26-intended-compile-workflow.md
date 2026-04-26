# Intended Compile Workflow Implementation Plan

**Purpose:** After this change, every published segment is built by (a) detecting "runs" — contiguous similar 3-second slices within each parent clip — then (b) running angle-selection over runs (not parents), (c) stitching ONLY the angle-selector's chosen runs into the final video, and (d) producing a `{title, caption}` pair from descriptions of the 3 children closest to the cluster centroid. The current code stitches every child of every parent regardless of selection, runs two redundant caption pipelines, and does angle selection at parent-clip granularity — all of which goes away.

**Architecture:** Run detection is a pure synchronous function operating on already-embedded children. Compile orchestration becomes two parallel branches inside the existing 60s wall-clock cap: Branch A `angle_select → stitch (chosen runs only)`, Branch B `describe_3_centroid_closest_children → synth_title_and_caption`. Both branches converge into a single `save_segment` write. Runs are computed deterministically from persisted children — no new DB tables.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite (WAL), NumPy (in-memory cosine), `claude-agent-sdk==0.1.68` (subagents + MCP), `anthropic` async client (vision + synthesis), ffmpeg-python (concat). Pytest + pytest-asyncio.

**Codebase Orientation:**
- Entry point: `backend/app.py` — `POST /clips` → `run_pipeline(clip_id)` (fire-and-forget)
- Pipeline: `backend/pipeline/run.py` — embed → cluster → maybe compile chain
- Embedding: `backend/pipeline/embed.py` — single Marengo call, returns 1 parent + N children (3-s windows)
- Clustering: `backend/pipeline/cluster.py` — composite score, parent-only (Pivot 1 locked)
- **Compile (most changes here):** `backend/pipeline/compile.py`
- MCP tools: `backend/pipeline/compile_tools.py` — exposed to subagents as `mcp__newz_tools__*`
- Caption: `backend/pipeline/caption_pipeline.py` — vision-grounded caption (Track C)
- Stitch: `backend/pipeline/stitch.py` — ffmpeg concat
- DB: `backend/db.py` — single `clips` table for parents + children; segments table; `parent_id IS NULL` distinguishes parents
- Test runner: `backend/.venv/bin/python -m pytest backend/tests/<file>.py -v` (run from repo root). Test discovery uses `@pytest.mark.asyncio` decorators (no `pytest.ini` — explicit decorators per existing convention).
- Config: `backend/config.py` — env-tunable thresholds (`CLUSTER_THRESHOLD`, `VISUAL_FLOOR`, `USE_MOCK_EMBEDDINGS`, `OFFLINE_DEMO`)

**Locked decisions (do not re-litigate during execution):**
- Run-similarity threshold: `RUN_THRESHOLD = 0.85` (cosine, child-to-child within same parent). Env-tunable via `RUN_THRESHOLD`.
- Run vector: arithmetic mean of constituent child vectors, L2-renormalized, float32.
- Run identity: synthetic deterministic ID `f"{parent_id}_run_{idx}"` where `idx` is the run's 0-based ordinal within that parent (sorted by `start_offset_sec`). NOT persisted.
- Runs are **transient** — recomputed on demand from children. Cluster + children are persisted; runs are derived.
- Single parent with no children (clip too short for 3-s segmentation): emits exactly one run that covers the entire parent file.
- Angle-selector input granularity: **runs**, not parent clips, not raw children. The MCP tool `get_cluster_clips` is renamed to `get_cluster_runs` and changes shape.
- Editor + publisher subagents stay. Editor validates `run_ids`. Publisher's `save_segment` accepts `ordered_run_ids` (stored under existing `ordered_clip_ids` column — column name kept for migration simplicity, payload semantics change).
- Caption pipeline: drop the vision keyframe caption-writer (`_run_caption_writer_with_vision`) entirely. Single Track: describe-3-children (parallel Haiku calls) → synth `{title, caption}` (one Sonnet call).
- Schema: add nullable `title TEXT` column to `segments`. Backwards-compatible.
- Wall-clock cap stays at 60s.

---

## Milestone 1: Run Detection (pure logic)

**Goal:** A pure function `find_runs(children, threshold)` produces deterministic run groupings from a list of child dicts.
**Acceptance test:** `backend/.venv/bin/python -m pytest backend/tests/test_runs.py -v` — all run-detection tests pass.

### Task 1.1: Create the runs module skeleton

**Behavioral check:** `from backend.pipeline.runs import find_runs` succeeds.

**Files:**
- Create: `backend/pipeline/runs.py`
- Test: `backend/tests/test_runs.py`

**Step 1: Write the failing test**

`backend/tests/test_runs.py`:
```python
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
```

**Step 2: Run test — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs.py::test_find_runs_module_imports -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline.runs'`

**Step 3: Implement minimal module**

`backend/pipeline/runs.py`:
```python
"""backend/pipeline/runs.py — run detection over already-embedded children.

A "run" is a contiguous span of children within the SAME parent whose
adjacent pairwise cosine similarity meets RUN_THRESHOLD. Runs are transient
(computed on-demand) and identified by f"{parent_id}_run_{idx}".

Public API:
    find_runs(children, threshold) -> list[Run]
        Pure, deterministic. Same input → same output → same run IDs.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Run:
    id: str
    parent_id: str
    parent_path: str
    start_offset_sec: float
    end_offset_sec: float
    member_child_ids: list[str]
    vec: np.ndarray  # float32, unit-length, mean of member child vecs


def find_runs(children: list[dict], threshold: float) -> list[Run]:
    raise NotImplementedError
```

**Step 4: Run test — verify it passes**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs.py::test_find_runs_module_imports -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/pipeline/runs.py backend/tests/test_runs.py
git commit -m "scaffold runs module + failing import test"
```

---

### Task 1.2: Single-parent, all-similar children → one run

**Behavioral check:** Three near-identical 3-s child windows of one parent collapse into one run spanning 0-9s.

**Files:**
- Modify: `backend/pipeline/runs.py`
- Modify: `backend/tests/test_runs.py`

**Step 1: Append failing test**

```python
def test_one_parent_all_similar_collapses_to_one_run():
    base = _unit(42)
    # tiny perturbations → high cosine
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
```

**Step 2: Run test — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs.py::test_one_parent_all_similar_collapses_to_one_run -v`
Expected: FAIL with `NotImplementedError`

**Step 3: Implement the function**

Replace the `raise NotImplementedError` body in `backend/pipeline/runs.py`:
```python
def find_runs(children: list[dict], threshold: float) -> list[Run]:
    """Group children into runs.

    Children are bucketed by parent_id, sorted by start_offset_sec, then walked
    pairwise: a new run starts when adjacent cosine drops below threshold.
    Each run's vec is the renormalized mean of member vecs.
    """
    if not children:
        return []

    by_parent: dict[str, list[dict]] = {}
    for c in children:
        by_parent.setdefault(c["parent_id"], []).append(c)

    out: list[Run] = []
    for parent_id, group in by_parent.items():
        group.sort(key=lambda c: float(c.get("start_offset_sec") or 0.0))
        # Greedy contiguous grouping
        run_groups: list[list[dict]] = [[group[0]]]
        for prev, cur in zip(group, group[1:]):
            cos = float(np.dot(prev["vec"], cur["vec"]))
            if cos >= threshold:
                run_groups[-1].append(cur)
            else:
                run_groups.append([cur])

        parent_path = group[0].get("parent_path", "")
        for idx, members in enumerate(run_groups):
            stack = np.stack([m["vec"].astype(np.float32) for m in members], axis=0)
            mean = stack.mean(axis=0)
            mean /= np.linalg.norm(mean) + 1e-12
            out.append(Run(
                id=f"{parent_id}_run_{idx}",
                parent_id=parent_id,
                parent_path=parent_path,
                start_offset_sec=float(members[0]["start_offset_sec"]),
                end_offset_sec=float(members[-1]["end_offset_sec"]),
                member_child_ids=[m["id"] for m in members],
                vec=mean.astype(np.float32),
            ))
    return out
```

**Step 4: Run test — verify it passes**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs.py -v`
Expected: 2 PASS

**Step 5: Commit**

```bash
git add backend/pipeline/runs.py backend/tests/test_runs.py
git commit -m "find_runs: collapse contiguous similar children into one run"
```

---

### Task 1.3: Scene-cut splits one parent into multiple runs

**Behavioral check:** Two clusters of dissimilar children within one parent produce two distinct runs.

**Files:**
- Modify: `backend/tests/test_runs.py`

**Step 1: Append failing test**

```python
def test_scene_cut_splits_into_two_runs():
    a, b = _unit(1), _unit(99)  # orthogonal-ish → cosine << 0.85
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
```

**Step 2: Run test — verify it passes (already implemented)**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs.py::test_scene_cut_splits_into_two_runs -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/tests/test_runs.py
git commit -m "find_runs: assert scene-cut splits run boundary"
```

---

### Task 1.4: Multi-parent → independent run namespaces

**Behavioral check:** Children from two different parents produce runs scoped per-parent (`p1_run_0`, `p2_run_0`).

**Files:**
- Modify: `backend/tests/test_runs.py`

**Step 1: Append failing test**

```python
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
```

**Step 2: Run test — verify it passes**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs.py::test_multiple_parents_independent_runs -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/tests/test_runs.py
git commit -m "find_runs: each parent gets its own run namespace"
```

---

### Task 1.5: Empty input + single-child edge cases

**Files:**
- Modify: `backend/tests/test_runs.py`

**Step 1: Append failing tests**

```python
def test_empty_children_returns_empty():
    assert find_runs([], threshold=0.85) == []


def test_single_child_becomes_one_run():
    v = _unit(11)
    children = [{
        "id": "p1_child_0", "parent_id": "p1", "parent_path": "/x/p1.mp4",
        "start_offset_sec": 0.0, "end_offset_sec": 3.0, "vec": v,
    }]
    runs = find_runs(children, threshold=0.85)
    assert len(runs) == 1
    assert runs[0].member_child_ids == ["p1_child_0"]
    assert runs[0].id == "p1_run_0"
```

**Step 2: Run + verify pass**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs.py -v`
Expected: 5 PASS

**Step 3: Commit**

```bash
git add backend/tests/test_runs.py
git commit -m "find_runs: cover empty + single-child edge cases"
```

---

## Milestone 2: Cluster → Runs Helper + MCP Tool

**Goal:** A coroutine `compute_runs_for_cluster(cluster_id)` returns the deterministic run list for a cluster, and an MCP tool exposes it to subagents.
**Acceptance test:** `backend/.venv/bin/python -m pytest backend/tests/test_runs_for_cluster.py -v` — all pass.

### Task 2.1: Add config knob `RUN_THRESHOLD`

**Behavioral check:** `from backend.config import RUN_THRESHOLD` returns 0.85 by default; setting `RUN_THRESHOLD=0.7` env var overrides.

**Files:**
- Modify: `backend/config.py`

**Step 1: Inspect current config**

Run: `grep -n "CLUSTER_THRESHOLD\|VISUAL_FLOOR\|os.environ" backend/config.py`
(Use this to find where existing thresholds are defined and copy the pattern.)

**Step 2: Add the new constant**

Insert after the existing `VISUAL_FLOOR` definition in `backend/config.py`:
```python
RUN_THRESHOLD: float = float(os.environ.get("RUN_THRESHOLD", "0.85"))
```

**Step 3: Verify**

Run: `backend/.venv/bin/python -c "from backend.config import RUN_THRESHOLD; print(RUN_THRESHOLD)"`
Expected: `0.85`

**Step 4: Commit**

```bash
git add backend/config.py
git commit -m "config: add RUN_THRESHOLD (default 0.85)"
```

---

### Task 2.2: `compute_runs_for_cluster` coroutine

**Behavioral check:** Given a cluster with persisted parent + children rows, returns a `list[Run]` ordered by parent and run-index.

**Files:**
- Modify: `backend/pipeline/runs.py`
- Test: `backend/tests/test_runs_for_cluster.py`

**Step 1: Write the failing test**

`backend/tests/test_runs_for_cluster.py`:
```python
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

    with patch("backend.pipeline.runs.db.fetch_cluster_clips_with_children",
               return_value=fake_rows), \
         patch("backend.pipeline.runs.db.get_embedding",
               side_effect=lambda cid: fake_vecs.get(cid)):
        runs = await compute_runs_for_cluster("cluster-x")

    assert len(runs) == 1
    assert runs[0].id == "p1_run_0"
    assert runs[0].parent_id == "p1"
    assert runs[0].member_child_ids == ["p1_child_0", "p1_child_3"]
```

**Step 2: Run — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs_for_cluster.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_runs_for_cluster'`

**Step 3: Implement**

Append to `backend/pipeline/runs.py`:
```python
from .. import config, db


async def compute_runs_for_cluster(cluster_id: str) -> list[Run]:
    """Load child rows for cluster's parents, attach embeddings, return runs.

    Parents whose Marengo call returned NO clip-scope items have no child rows;
    we synthesize a single run that spans the full parent file (start=0, end=None
    encoded as 0.0 placeholder — stitch handles None elsewhere via parent_path).
    """
    rows = await db.fetch_cluster_clips_with_children(cluster_id)
    if not rows:
        return []

    parent_paths: dict[str, str] = {}
    children: list[dict] = []
    parents_with_children: set[str] = set()

    for r in rows:
        if r.get("parent_id") is None:
            # parent row
            parent_paths[r["id"]] = r.get("path") or ""
        else:
            vec = await db.get_embedding(r["id"])
            if vec is None:
                continue
            parents_with_children.add(r["parent_id"])
            children.append({
                "id": r["id"],
                "parent_id": r["parent_id"],
                "parent_path": r.get("parent_path") or parent_paths.get(r["parent_id"], ""),
                "start_offset_sec": r.get("start_offset_sec") or 0.0,
                "end_offset_sec": r.get("end_offset_sec") or 0.0,
                "vec": vec,
            })

    runs = find_runs(children, threshold=config.RUN_THRESHOLD)

    # Edge: a parent with NO children at all → emit one synthetic run for the
    # full file. Stitch consumes (parent_path, 0.0, None) elsewhere, so we use
    # end_offset_sec=0.0 here as a sentinel only consumed by ID generation;
    # the stitch resolver detects "no children" by checking member_child_ids.
    for parent_id, parent_path in parent_paths.items():
        if parent_id in parents_with_children:
            continue
        parent_vec = await db.get_embedding(parent_id)
        if parent_vec is None:
            continue
        runs.append(Run(
            id=f"{parent_id}_run_0",
            parent_id=parent_id,
            parent_path=parent_path,
            start_offset_sec=0.0,
            end_offset_sec=0.0,  # sentinel: resolver treats as "use full parent file"
            member_child_ids=[],
            vec=parent_vec,
        ))

    return runs
```

**Step 4: Run — verify it passes**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs_for_cluster.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/pipeline/runs.py backend/tests/test_runs_for_cluster.py
git commit -m "compute_runs_for_cluster: db-backed run computation"
```

---

### Task 2.3: Childless-parent fallback test

**Files:**
- Modify: `backend/tests/test_runs_for_cluster.py`

**Step 1: Append failing test**

```python
@pytest.mark.asyncio
async def test_compute_runs_synthesizes_run_for_childless_parent():
    a = _unit(2)
    fake_rows = [
        {"id": "p2", "parent_id": None, "parent_path": "/x/p2.mp4",
         "start_offset_sec": None, "end_offset_sec": None,
         "lat": 0, "lng": 0, "ts": 0, "path": "/x/p2.mp4"},
    ]
    fake_vecs = {"p2": a}
    with patch("backend.pipeline.runs.db.fetch_cluster_clips_with_children",
               return_value=fake_rows), \
         patch("backend.pipeline.runs.db.get_embedding",
               side_effect=lambda cid: fake_vecs.get(cid)):
        runs = await compute_runs_for_cluster("cluster-y")
    assert len(runs) == 1
    assert runs[0].id == "p2_run_0"
    assert runs[0].parent_id == "p2"
    assert runs[0].member_child_ids == []
    assert runs[0].parent_path == "/x/p2.mp4"
```

**Step 2: Run + verify pass**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_runs_for_cluster.py -v`
Expected: 2 PASS

**Step 3: Commit**

```bash
git add backend/tests/test_runs_for_cluster.py
git commit -m "compute_runs_for_cluster: childless parent gets synthetic run"
```

---

### Task 2.4: Replace MCP tool `get_cluster_clips` with `get_cluster_runs`

**Behavioral check:** `mcp__newz_tools__get_cluster_runs` JSON-serializes a list of run dicts (id, parent_id, parent_path, start_offset_sec, end_offset_sec, duration_sec, lat, lng, ts, member_child_ids).

**Files:**
- Modify: `backend/pipeline/compile_tools.py`
- Test: `backend/tests/test_compile_tools_runs.py`

**Step 1: Write the failing test**

`backend/tests/test_compile_tools_runs.py`:
```python
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

    with patch("backend.pipeline.compile_tools.compute_runs_for_cluster",
               return_value=fake_runs), \
         patch("backend.pipeline.compile_tools.db.get_clip",
               return_value=fake_parent):
        result = await get_cluster_runs({"cluster_id": "cluster-x"})

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
```

**Step 2: Run — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile_tools_runs.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_cluster_runs'`

**Step 3: Implement — replace `get_cluster_clips`**

In `backend/pipeline/compile_tools.py`:

**Delete** the existing `@tool("get_cluster_clips", ...)` decorator block (lines ~19-34).
**Add imports** at top of file:
```python
from .runs import compute_runs_for_cluster
```
**Insert** the replacement tool above `get_clip_metadata`:
```python
@tool(
    "get_cluster_runs",
    (
        "Return all RUNS in a cluster. A run is a contiguous span of similar "
        "3-second slices within a single parent clip — i.e. one continuous "
        "camera angle. Use these as candidates for angle selection. "
        "Each run has: id, parent_id, parent_path, start_offset_sec, "
        "end_offset_sec, duration_sec, lat/lng/ts (from parent), member_child_ids."
    ),
    {"cluster_id": str},
)
async def get_cluster_runs(args: dict) -> dict:
    runs = await compute_runs_for_cluster(args["cluster_id"])
    out: list[dict] = []
    for r in runs:
        parent = await db.get_clip(r.parent_id)
        out.append({
            "id": r.id,
            "parent_id": r.parent_id,
            "parent_path": r.parent_path,
            "start_offset_sec": r.start_offset_sec,
            "end_offset_sec": r.end_offset_sec,
            "duration_sec": round(max(0.0, r.end_offset_sec - r.start_offset_sec), 2),
            "lat": parent.get("lat") if parent else None,
            "lng": parent.get("lng") if parent else None,
            "ts": parent.get("ts") if parent else None,
            "member_child_ids": r.member_child_ids,
        })
    return {"content": [{"type": "text", "text": json.dumps(out)}]}
```
**Update** the `newz_tools_server` `tools=[...]` list at the bottom: replace `get_cluster_clips` with `get_cluster_runs`.

**Step 4: Run — verify it passes**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile_tools_runs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/pipeline/compile_tools.py backend/tests/test_compile_tools_runs.py
git commit -m "MCP: replace get_cluster_clips with get_cluster_runs"
```

---

## Milestone 3: Angle-Selector + Editor over Runs

**Goal:** The angle-selector subagent picks 2-4 RUN ids; editor validates them; publisher saves them under `ordered_clip_ids`.
**Acceptance test:** `backend/.venv/bin/python -m pytest backend/tests/test_compile.py -v -k "happy or fallback"` — orchestrator chain still passes against updated mocks.

### Task 3.1: Update angle-selector + editor + publisher prompts

**Behavioral check:** `AGENTS["angle-selector"].tools` includes `mcp__newz_tools__get_cluster_runs` and not `mcp__newz_tools__get_cluster_clips`.

**Files:**
- Modify: `backend/pipeline/compile.py` (the `AGENTS` dict)

**Step 1: Update angle-selector**

Replace its `prompt` field:
```python
"""You are the Angle Selector for the Newz news compile pipeline.

You select the best 2-4 RUNS from a cluster. A run = one continuous camera
angle (a contiguous span of similar 3-second slices from the same source
clip). Different runs from different parent clips give you different
viewpoints of the same event.

Selection criteria — rank candidates by:
1. TEMPORAL SPREAD: prefer runs from early, middle, and late in the event
   timeline (spread across the timestamp range).
2. SPATIAL DIVERSITY: prefer runs whose parent clips were recorded from
   different GPS coordinates (different physical viewpoints).
3. DURATION: prefer runs whose duration_sec >= 3.0; discard runs shorter
   than 2.0 seconds.
4. NO REDUNDANCY: exclude runs whose parent was filmed within 5 seconds AND
   within 10 meters of an already-selected run's parent.

Order the selected runs chronologically (earliest parent ts first).

Use mcp__newz_tools__get_cluster_runs to list candidates, then
mcp__newz_tools__get_clip_metadata for any parent-clip details.
Return ONLY a single JSON object: {"run_ids": ["...", "..."], "rationale": "..."}.
Do not include any text outside the JSON."""
```
And replace its `tools=` field:
```python
tools=["mcp__newz_tools__get_cluster_runs", "mcp__newz_tools__get_clip_metadata"],
```

**Step 2: Update editor**

Replace its `prompt`:
```python
"""You are the Editor for the Newz news compile pipeline.

Review the Angle Selector's run ordering. Confirm it makes editorial sense:
no jarring cuts, sufficient temporal coverage, the chosen runs tell the
story. You may reorder or drop runs but must not add new ones.

Return ONLY a single JSON object: {"run_ids": ["..."], "edit_notes": "..."}."""
```

**Step 3: Update publisher**

Replace its `prompt`:
```python
"""You are the Publisher for the Newz news compile pipeline.

The title, caption, and location are provided by the orchestrator (already
written upstream). Take the editor's validated run_ids and the provided
title/caption/location.

Call mcp__newz_tools__save_segment EXACTLY ONCE with:
  - cluster_id: provided by the orchestrator
  - ordered_run_ids: from editor's run_ids list
  - title: provided by the orchestrator
  - caption: provided by the orchestrator
  - location: provided by the orchestrator
  - source_count: number of distinct parent_ids in ordered_run_ids

Return ONLY the segment id string from the tool result."""
```

**Step 4: Verify prompts are syntactically valid**

Run: `backend/.venv/bin/python -c "from backend.pipeline.compile import AGENTS; print(list(AGENTS['angle-selector'].tools))"`
Expected: `['mcp__newz_tools__get_cluster_runs', 'mcp__newz_tools__get_clip_metadata']`

**Step 5: Commit**

```bash
git add backend/pipeline/compile.py
git commit -m "subagents: pivot angle-selector/editor/publisher to runs"
```

---

### Task 3.2: Update `save_segment` MCP tool to accept `ordered_run_ids` + `title`

**Behavioral check:** Tool persists run ids under `ordered_clip_ids` column and `title` into a new `title` column.

**Files:**
- Modify: `backend/pipeline/compile_tools.py`
- Test: `backend/tests/test_compile_tools_save_segment.py`

**Step 1: Write the failing test**

`backend/tests/test_compile_tools_save_segment.py`:
```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.pipeline.compile_tools import save_segment


@pytest.mark.asyncio
async def test_save_segment_passes_run_ids_and_title():
    insert_mock = AsyncMock(return_value="seg-xyz")
    with patch("backend.pipeline.compile_tools.db.insert_segment", insert_mock):
        result = await save_segment({
            "cluster_id": "c1",
            "ordered_run_ids": ["p1_run_0", "p2_run_0"],
            "title": "Multi-angle gathering",
            "caption": "Two contributors filmed people gathered with signs.",
            "location": "Pasadena, CA",
            "source_count": 2,
        })
    text = result["content"][0]["text"]
    assert text == "saved:seg-xyz"
    insert_mock.assert_awaited_once()
    kwargs = insert_mock.await_args.kwargs
    assert kwargs["ordered_clip_ids"] == ["p1_run_0", "p2_run_0"]
    assert kwargs["title"] == "Multi-angle gathering"
    assert kwargs["caption"].startswith("Two contributors")
```

**Step 2: Run — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile_tools_save_segment.py -v`
Expected: FAIL — current `save_segment` rejects `ordered_run_ids`/`title` keys.

**Step 3: Implement — replace `save_segment` in `compile_tools.py`**

```python
@tool(
    "save_segment",
    (
        "Persist the final compiled segment to the database. "
        "Call EXACTLY ONCE with all required fields. "
        "Only the Publisher subagent is allowed to call this tool."
    ),
    {
        "cluster_id":       str,
        "ordered_run_ids":  list[str],
        "title":            str,
        "caption":          str,
        "location":         str,
        "source_count":     int,
    },
)
async def save_segment(args: dict) -> dict:
    seg_id = await db.insert_segment(
        cluster_id=args["cluster_id"],
        ordered_clip_ids=args["ordered_run_ids"],  # column name retained; payload = run ids
        title=args["title"],
        caption=args["caption"],
        location=args["location"],
        source_count=args["source_count"],
    )
    log.info("save_segment cluster_id=%s seg_id=%s runs=%d",
             args["cluster_id"], seg_id, len(args["ordered_run_ids"]))
    return {"content": [{"type": "text", "text": f"saved:{seg_id}"}]}
```

**Step 4: Run — verify it still fails (db.insert_segment doesn't accept title yet)**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile_tools_save_segment.py -v`
Expected: FAIL with `TypeError: insert_segment() got an unexpected keyword argument 'title'` — this is the lead-in to Milestone 4.

**Step 5: Commit (failing test stays red until M4)**

```bash
git add backend/pipeline/compile_tools.py backend/tests/test_compile_tools_save_segment.py
git commit -m "save_segment MCP: accept ordered_run_ids + title (db plumbing pending)"
```

---

## Milestone 4: Schema — `title` column on segments

**Goal:** `segments.title` exists, `insert_segment(title=...)` works, existing rows back-fill `NULL`.
**Acceptance test:** `backend/.venv/bin/python -m pytest backend/tests/test_segments_db.py backend/tests/test_compile_tools_save_segment.py -v` — all pass.

### Task 4.1: Migration — add `title TEXT` column to `segments`

**Behavioral check:** `PRAGMA table_info(segments)` includes a `title` column.

**Files:**
- Modify: `backend/db.py` (the schema-creation / migration block — see line ~85 region for how `parent_id` was added)

**Step 1: Locate the existing migration block**

Run: `grep -n "ALTER TABLE\|PRAGMA table_info\|table_info(segments)" backend/db.py`
(Use this output to find the existing pattern.)

**Step 2: Add idempotent migration**

After the existing ALTER for `clips` (around line ~88-93), add a parallel block for `segments`:
```python
        async with conn.execute("PRAGMA table_info(segments)") as cur:
            seg_cols = {row[1] for row in await cur.fetchall()}
        if "title" not in seg_cols:
            await conn.execute("ALTER TABLE segments ADD COLUMN title TEXT")
```

**Step 3: Verify migration runs**

Run: `backend/.venv/bin/python -c "
import asyncio
from backend import db
async def main():
    await db.init_db()
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as c:
        async with c.execute('PRAGMA table_info(segments)') as cur:
            cols = [r[1] for r in await cur.fetchall()]
    print('title' in cols, cols)
asyncio.run(main())
"`
Expected: `True [... 'title' ...]`

**Step 4: Commit**

```bash
git add backend/db.py
git commit -m "schema: add segments.title column (idempotent migration)"
```

---

### Task 4.2: `insert_segment(title=...)` parameter

**Behavioral check:** Calling `insert_segment(..., title="Hello")` writes the title; reading back via `get_segment_for_cluster` returns it.

**Files:**
- Modify: `backend/db.py` — `insert_segment`, `get_segment_for_cluster`, `fetch_recent_segments`
- Test: `backend/tests/test_segments_db.py` (extend existing)

**Step 1: Add a failing test**

Append to `backend/tests/test_segments_db.py`:
```python
@pytest.mark.asyncio
async def test_insert_segment_persists_title(tmp_path, monkeypatch):
    import backend.db as dbm
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "t.db"))
    await dbm.init_db()
    # Need a cluster row for FK
    import numpy as np
    await dbm.upsert_cluster(type("C", (), {
        "id": "c1",
        "centroid": np.zeros(512, dtype=np.float32),
        "centroid_lat": 0.0, "centroid_lng": 0.0,
        "median_ts": 0.0, "member_count": 1, "member_ids": ["x"],
    })())
    seg_id = await dbm.insert_segment(
        cluster_id="c1",
        ordered_clip_ids=["p1_run_0"],
        title="Test Title",
        caption="Test Caption",
        location="Pasadena, CA",
        source_count=1,
    )
    seg = await dbm.get_segment_for_cluster("c1")
    assert seg["title"] == "Test Title"
    assert seg["caption"] == "Test Caption"
```

**Step 2: Run — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_segments_db.py::test_insert_segment_persists_title -v`
Expected: FAIL — `insert_segment` does not yet accept `title`.

**Step 3: Update `insert_segment`**

In `backend/db.py`, replace the function with:
```python
async def insert_segment(
    cluster_id: str,
    ordered_clip_ids: list[str],
    caption: str,
    location: str,
    source_count: int,
    video_url: str | None = None,
    title: str | None = None,
) -> str:
    """Idempotent: one segment per cluster. ON CONFLICT(cluster_id) updates."""
    seg_id = uuid.uuid4().hex
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            """INSERT INTO segments
                 (id, cluster_id, ordered_clip_ids, title, caption, location,
                  source_count, created_at, video_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cluster_id) DO UPDATE SET
                 ordered_clip_ids = excluded.ordered_clip_ids,
                 title            = excluded.title,
                 caption          = excluded.caption,
                 location         = excluded.location,
                 source_count     = excluded.source_count,
                 video_url        = excluded.video_url
               RETURNING id""",
            (seg_id, cluster_id, json.dumps(ordered_clip_ids),
             title, caption, location, source_count, now, video_url),
        )
        row = await cur.fetchone()
        await conn.commit()
    return row[0]
```

**Step 4: Update `get_segment_for_cluster` SELECT**

Find the existing query (around line ~360). Add `title` to the column list. Same for any place `fetch_recent_segments` selects from segments — include `s.title` and propagate into the returned dict.

**Step 5: Run — verify pass**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_segments_db.py backend/tests/test_compile_tools_save_segment.py -v`
Expected: ALL PASS (the M3.2 test now passes too)

**Step 6: Commit**

```bash
git add backend/db.py backend/tests/test_segments_db.py
git commit -m "db: insert_segment + get_segment_for_cluster carry title field"
```

---

## Milestone 5: Single Caption Pipeline (`describe → synth title+caption`)

**Goal:** `caption_pipeline.generate_caption` returns `{"title": str, "caption": str, "location": str, "source": "vision"}`. The vision keyframe caption-writer in `compile.py` is deleted.
**Acceptance test:** `backend/.venv/bin/python -m pytest backend/tests/test_caption_pipeline.py -v` — all new caption-pipeline tests pass.

### Task 5.1: New synth call returns `{title, caption}` JSON

**Behavioral check:** `generate_caption` invokes Sonnet with a synthesis prompt that asks for a JSON object with `title` and `caption` keys, parses the response, and returns both.

**Files:**
- Modify: `backend/pipeline/caption_pipeline.py`
- Test: `backend/tests/test_caption_pipeline.py` (new)

**Step 1: Write the failing test**

`backend/tests/test_caption_pipeline.py`:
```python
"""Tests for backend/pipeline/caption_pipeline.py — describe → synth title+caption."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.pipeline import caption_pipeline as cp


def _mk_child(idx, vec):
    return {
        "id": f"p{idx}_child_0", "parent_id": f"p{idx}", "parent_path": f"/x/p{idx}.mp4",
        "start_offset_sec": 0.0, "end_offset_sec": 3.0,
        "lat": 34.1, "lng": -118.1, "ts": 1700000000.0 + idx, "vec": vec,
    }


@pytest.mark.asyncio
async def test_generate_caption_returns_title_and_caption(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(cp.config, "USE_MOCK_EMBEDDINGS", False)

    centroid = np.ones(512, dtype=np.float32)
    centroid /= np.linalg.norm(centroid)
    children = [_mk_child(i, centroid) for i in range(3)]

    fake_client = MagicMock()
    # 3 describe calls (Haiku) + 1 synth call (Sonnet)
    describe_responses = [
        MagicMock(content=[MagicMock(text=f"Description {i}")]) for i in range(3)
    ]
    synth_response = MagicMock(content=[MagicMock(text=json.dumps({
        "title": "Multi-angle event in Pasadena",
        "caption": "Three contributors filmed the same scene from different angles.",
    }))])
    fake_client.messages.create = AsyncMock(side_effect=describe_responses + [synth_response])

    with patch("backend.pipeline.caption_pipeline.anthropic.AsyncAnthropic",
               return_value=fake_client), \
         patch("backend.pipeline.caption_pipeline.extract_frames",
               return_value=[b"\xff\xd8\xff_jpeg"] * 3):
        out = await cp.generate_caption("cluster-x", centroid, children)

    assert out is not None
    assert out["title"] == "Multi-angle event in Pasadena"
    assert out["caption"].startswith("Three contributors")
    assert out["location"] == "Pasadena, CA"
    assert out["source"] == "vision"
```

**Step 2: Run — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_caption_pipeline.py -v`
Expected: FAIL — current `generate_caption` returns no `title` key.

**Step 3: Update `generate_caption`**

In `backend/pipeline/caption_pipeline.py`, replace the synth block (around lines 139-163) with:
```python
        location = "Pasadena, CA"
        ts = selected[0].get("ts") if selected else None
        if ts:
            when = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %-d, %Y")
        else:
            when = datetime.now(tz=timezone.utc).strftime("%b %-d, %Y")

        aggregated = "\n".join(f"- {d}" for d in desc_texts)
        synthesis_prompt = (
            f"You will produce a JSON object with two keys: 'title' and 'caption' "
            f"for a news segment recorded on {when} in {location}.\n\n"
            f"Ground both ONLY in these per-clip descriptions — do not add "
            f"participant counts, motives, or details not in the text:\n\n"
            f"{aggregated}\n\n"
            f"Rules:\n"
            f"- title: 60 characters or fewer, AP-wire style headline.\n"
            f"- caption: 200 characters or fewer, one-sentence summary referencing "
            f"  date and neighborhood.\n\n"
            f"Return ONLY a single JSON object: "
            f'{{"title": "...", "caption": "..."}}.'
        )

        result = await client.messages.create(
            model=_SONNET,
            max_tokens=200,
            messages=[{"role": "user", "content": synthesis_prompt}],
        )
        raw = result.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        parsed = json.loads(raw)
        title = parsed["title"][:60]
        caption = parsed["caption"][:200]
        log.info("generate_caption ok cluster_id=%s title_len=%d caption_len=%d",
                 cluster_id, len(title), len(caption))
        return {"title": title, "caption": caption, "location": location, "source": "vision"}
```
And add `import json` at the top of the file (if not already present).

**Step 4: Update the mock-embeddings branch**

Replace the `if config.USE_MOCK_EMBEDDINGS:` early-return (around lines 103-108):
```python
    if config.USE_MOCK_EMBEDDINGS:
        log.info("generate_caption mock cluster_id=%s", cluster_id)
        return {
            "title": "Staged multi-angle event",
            "caption": "Staged event captured from multiple angles at Caltech campus.",
            "location": "Pasadena, CA",
            "source": "vision",
        }
```

**Step 5: Update `_fallback_caption` return contract**

Replace the function:
```python
def _fallback_caption(cluster_id: str, children: list[dict]) -> dict | None:
    """Track collapse fallback: Anthropic unavailable / errored → return None."""
    log.info("caption fallback (returning None) cluster_id=%s", cluster_id)
    return None
```
(Returns `None` so the compile.py call site uses a deterministic generic fallback.)

**Step 6: Run — verify pass**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_caption_pipeline.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add backend/pipeline/caption_pipeline.py backend/tests/test_caption_pipeline.py
git commit -m "caption_pipeline: synth returns {title, caption} JSON"
```

---

## Milestone 6: Compile Orchestration Restructure

**Goal:** `compile_segment` runs two parallel branches inside the 60s cap:
- Branch A: angle-select chain → resolve runs → stitch
- Branch B: describe-3-children → synth title+caption
Both converge into a single `insert_segment` write.

**Acceptance test:** Updated `backend/tests/test_compile.py` happy-path passes; integration test exercises the new flow end-to-end with mocks.

### Task 6.1: Run resolver helper

**Behavioral check:** `_resolve_run_ids_to_stitch_refs(cluster_id, run_ids)` returns `[{path, start_offset_sec, end_offset_sec}, ...]` ready for `stitch_clips`.

**Files:**
- Modify: `backend/pipeline/compile.py`
- Test: `backend/tests/test_compile_resolve_runs.py`

**Step 1: Write the failing test**

`backend/tests/test_compile_resolve_runs.py`:
```python
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
    with patch("backend.pipeline.compile.compute_runs_for_cluster",
               return_value=fake_runs):
        refs = await compile_mod._resolve_run_ids_to_stitch_refs(
            "c1", ["p2_run_0", "p1_run_0"]  # editor reorder
        )
    assert refs == [
        {"path": "/x/p2.mp4", "start_offset_sec": 0.0, "end_offset_sec": None},
        {"path": "/x/p1.mp4", "start_offset_sec": 0.0, "end_offset_sec": 6.0},
    ]
```

**Step 2: Run — verify it fails**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile_resolve_runs.py -v`
Expected: FAIL — `_resolve_run_ids_to_stitch_refs` does not exist.

**Step 3: Implement**

Add to `backend/pipeline/compile.py` (and import `compute_runs_for_cluster` from `.runs` at the top):
```python
from .runs import compute_runs_for_cluster


async def _resolve_run_ids_to_stitch_refs(
    cluster_id: str, ordered_run_ids: list[str]
) -> list[dict]:
    """Re-derive runs from cluster, then look up each ordered_run_id.

    Childless-parent runs (member_child_ids == []) emit end_offset_sec=None
    so ffmpeg ingests the full parent file. Otherwise we use the run's
    [start, end] window.
    """
    runs = await compute_runs_for_cluster(cluster_id)
    by_id = {r.id: r for r in runs}
    refs: list[dict] = []
    for rid in ordered_run_ids:
        r = by_id.get(rid)
        if r is None:
            log.warning("resolve: unknown run_id=%s cluster_id=%s", rid, cluster_id)
            continue
        end = None if not r.member_child_ids else r.end_offset_sec
        refs.append({
            "path": r.parent_path,
            "start_offset_sec": r.start_offset_sec,
            "end_offset_sec": end,
        })
    return refs
```

**Step 4: Run — verify pass**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile_resolve_runs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/pipeline/compile.py backend/tests/test_compile_resolve_runs.py
git commit -m "compile: resolver maps run_ids to stitch refs"
```

---

### Task 6.2: Branch A — angle-chain → stitch (sequential)

**Behavioral check:** New helper `_branch_angles_then_stitch(cluster_id)` runs the orchestrator chain to completion (which has saved a placeholder segment), then resolves run_ids from the saved segment and stitches them; returns `(segment_id, video_url)`.

**Files:**
- Modify: `backend/pipeline/compile.py`

**Step 1: Refactor orchestrator chain**

Modify `_run_orchestrator_chain` to no longer accept a `caption_data` argument (it will run BEFORE caption synth). The orchestrator's prompt must be updated so the publisher saves a placeholder title + caption (`""`), which Branch B overwrites later.

Replace the existing `ORCHESTRATOR_PROMPT_TEMPLATE` with:
```python
ORCHESTRATOR_PROMPT_TEMPLATE = """Compile cluster {cluster_id} into a published news segment.

The title and caption will be filled in later by another worker. Pass empty
strings ("") for both when calling save_segment. The orchestrator will
overwrite them.

Steps — use the named subagents in this order:
1. Run angle-selector to pick the best 2-4 RUNS and order them.
2. Run editor on angle-selector's JSON output to validate the run order.
3. Run publisher with editor's run_ids. Pass title="" and caption="".

Pass each subagent's JSON output verbatim into the next subagent's prompt.
The cluster_id is: {cluster_id}
"""
```

Replace the body of `_run_orchestrator_chain`:
```python
async def _run_orchestrator_chain(cluster_id: str) -> str:
    options = ClaudeAgentOptions(
        allowed_tools=[
            "Agent",
            "mcp__newz_tools__get_cluster_runs",
            "mcp__newz_tools__get_clip_metadata",
            "mcp__newz_tools__save_segment",
        ],
        agents=AGENTS,
        mcp_servers={"newz_tools": newz_tools_server},
        max_turns=20,
        model="sonnet",
    )
    prompt = ORCHESTRATOR_PROMPT_TEMPLATE.format(cluster_id=cluster_id)
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            if msg.is_error:
                log.error(
                    "compile orchestrator error cluster_id=%s turns=%s errors=%s",
                    cluster_id, msg.num_turns, msg.errors,
                )
                raise RuntimeError(f"orchestrator returned is_error=True: {msg.errors}")
            log.info(
                "compile orchestrator done cluster_id=%s turns=%s duration_ms=%s",
                cluster_id, msg.num_turns, msg.duration_ms,
            )
            break
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        raise RuntimeError(
            f"compile finished but no segment row for cluster {cluster_id}"
        )
    return seg["id"]
```

**Step 2: Add Branch A helper**

```python
async def _branch_angles_then_stitch(cluster_id: str) -> tuple[str, str | None]:
    """Sequential: orchestrator chain (writes segment with run_ids) → stitch.

    Returns (segment_id, video_url_or_None).
    """
    segment_id = await _run_orchestrator_chain(cluster_id)
    seg = await db.get_segment_for_cluster(cluster_id)
    raw = seg.get("ordered_clip_ids") if seg else None
    run_ids = json.loads(raw) if isinstance(raw, str) else (raw or [])

    if not run_ids:
        log.warning("Branch A: no run_ids saved for cluster_id=%s", cluster_id)
        return segment_id, None

    refs = await _resolve_run_ids_to_stitch_refs(cluster_id, run_ids)
    if not refs:
        return segment_id, None

    output_path = str(config.DATA_DIR / "clips" / f"{cluster_id}_compiled.mp4")
    stitched = await stitch_clips(refs, output_path)
    if stitched and Path(stitched).exists() and stitched == output_path:
        return segment_id, f"/media/{Path(stitched).name}"
    return segment_id, None
```

**Step 3: Quick syntax check**

Run: `backend/.venv/bin/python -c "from backend.pipeline.compile import _branch_angles_then_stitch; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add backend/pipeline/compile.py
git commit -m "compile: Branch A — orchestrator chain then stitch chosen runs"
```

---

### Task 6.3: Branch B — describe → synth title+caption

**Behavioral check:** New helper `_branch_caption(cluster_id)` calls `generate_caption` against the cluster's centroid + children and returns the result dict (or None on failure).

**Files:**
- Modify: `backend/pipeline/compile.py`

**Step 1: Add Branch B helper**

```python
async def _branch_caption(cluster_id: str) -> dict | None:
    from .cluster import CLUSTERS  # local import: avoid module-load cycle
    cluster_cache = CLUSTERS.get(cluster_id)
    if cluster_cache is None:
        return None
    children = await _get_children_with_vecs(cluster_id)
    if not children:
        return None
    return await generate_caption(cluster_id, cluster_cache.centroid, children)
```

**Step 2: Quick check**

Run: `backend/.venv/bin/python -c "from backend.pipeline.compile import _branch_caption; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add backend/pipeline/compile.py
git commit -m "compile: Branch B — describe + synth title+caption"
```

---

### Task 6.4: Wire branches into `compile_segment`

**Behavioral check:** `compile_segment(cluster_id)` runs Branch A ‖ Branch B inside `asyncio.wait_for(timeout=60)`. After both complete, calls `insert_segment` once more to overwrite title + caption + video_url on the row Branch A wrote.

**Files:**
- Modify: `backend/pipeline/compile.py`

**Step 1: Replace the body of `compile_segment`**

Replace the existing function body with:
```python
async def compile_segment(cluster_id: str) -> None:
    """Top-level entry. Two parallel branches inside a 60s cap.

    Branch A: orchestrator chain (angle-select → editor → publisher) → stitch.
              Writes the segment row with ordered_run_ids; produces video_url.
    Branch B: describe-3-children → synth {title, caption}.
              Returns the title/caption to overwrite Branch A's placeholders.

    Both write through one final insert_segment call to land everything atomically.
    """
    started_at = time.time()
    await events.broadcast({
        "type": "compile_started",
        "cluster_id": cluster_id,
        "started_at": started_at,
    })

    segment_id: str = ""
    video_url: str | None = None
    caption_result: dict | None = None

    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                _branch_angles_then_stitch(cluster_id),
                _branch_caption(cluster_id),
                return_exceptions=True,
            ),
            timeout=60.0,
        )
        a_result, b_result = results

        if isinstance(a_result, Exception):
            log.error("Branch A failed: %s — using fallback", a_result)
            segment_id = await _save_fallback_segment(cluster_id, None)
        else:
            segment_id, video_url = a_result

        if isinstance(b_result, dict) and b_result.get("source") == "vision":
            caption_result = b_result
        elif isinstance(b_result, Exception):
            log.warning("Branch B failed: %s — using existing/fallback caption", b_result)

        seg = await db.get_segment_for_cluster(cluster_id)
        if seg is not None:
            run_ids = (
                json.loads(seg["ordered_clip_ids"])
                if isinstance(seg.get("ordered_clip_ids"), str)
                else seg.get("ordered_clip_ids", [])
            )
            distinct_parents = len({rid.rsplit("_run_", 1)[0] for rid in run_ids})
            await db.insert_segment(
                cluster_id=cluster_id,
                ordered_clip_ids=run_ids,
                title=(caption_result["title"] if caption_result else seg.get("title") or ""),
                caption=(caption_result["caption"] if caption_result else seg.get("caption") or ""),
                location=(caption_result["location"] if caption_result else seg.get("location") or "Pasadena, CA"),
                source_count=distinct_parents or seg.get("source_count", 1),
                video_url=video_url or seg.get("video_url"),
            )

        elapsed_ms = int((time.time() - started_at) * 1000)
        log.info(
            "compile success cluster_id=%s segment_id=%s elapsed_ms=%d video_url=%s",
            cluster_id, segment_id, elapsed_ms, video_url,
        )

    except asyncio.TimeoutError:
        log.warning("compile TIMEOUT cluster_id=%s after 60s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id, video_url)
    except Exception:
        log.exception("compile FAILED cluster_id=%s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id, video_url)
    finally:
        await db.set_compile_in_flight(cluster_id, False)

    await events.broadcast({
        "type": "segment_published",
        "cluster_id": cluster_id,
        "segment_id": segment_id,
    })
```

**Step 2: Update `_save_fallback_segment` to also pass title**

Modify the call to `db.insert_segment` inside `_save_fallback_segment`:
```python
    return await db.insert_segment(
        cluster_id=cluster_id,
        ordered_clip_ids=clip_ids,
        title="",
        caption=caption,
        location=location_str,
        source_count=len(clip_ids),
        video_url=video_url,
    )
```

**Step 3: Delete the old vision caption-writer pipeline**

In `backend/pipeline/compile.py`, **delete**:
- The `CAPTION_WRITER_SYSTEM` constant
- The `_build_caption_user_message` helper
- The `_extract_text_from_assistant` helper
- The `_parse_caption_json` helper
- The `_run_caption_writer_with_vision` coroutine
- The `_run_agents` wrapper (no longer used)

Also remove now-dead imports if any (`extract_cluster_keyframes`, `base64`, `AssistantMessage`, `TextBlock`, `_build_caption_user_message`-only types).

**Step 4: Quick smoke**

Run: `backend/.venv/bin/python -c "from backend.pipeline.compile import compile_segment; print('ok')"`
Expected: `ok`

**Step 5: Commit**

```bash
git add backend/pipeline/compile.py
git commit -m "compile_segment: parallel branches converge to single insert_segment"
```

---

### Task 6.5: Update `test_compile.py` happy-path mock to reflect new shape

**Behavioral check:** `test_compile_segment_happy_path` exercises Branch A ‖ Branch B and asserts the final segment carries the new title + caption.

**Files:**
- Modify: `backend/tests/test_compile.py`

**Step 1: Rewrite the happy-path test**

Open `backend/tests/test_compile.py`. The existing test mocks `query()` with branching on prompt shape (string vs. AsyncIterable) — now both Branch A and Branch B use distinct entry points. Replace the test body so it:
- Mocks `_run_orchestrator_chain` to return a fixed `segment_id`.
- Mocks `compute_runs_for_cluster` to return one run.
- Mocks `stitch_clips` to write a fake .mp4 and return its path.
- Mocks `generate_caption` to return `{"title": "T", "caption": "C", "location": "Pasadena, CA", "source": "vision"}`.
- Asserts the final segment row contains `title="T"`, `caption="C"`, and `video_url` set.

A skeleton:
```python
@pytest.mark.asyncio
async def test_compile_segment_happy_path(tmp_path, monkeypatch):
    from backend.pipeline import compile as compile_mod
    from backend.pipeline.runs import Run
    import numpy as np

    seg_state = {"id": "seg-abc", "cluster_id": "c1",
                 "ordered_clip_ids": '["p1_run_0"]',
                 "title": "", "caption": "", "location": "Pasadena, CA",
                 "source_count": 1, "video_url": None, "created_at": 1.0}

    async def fake_orch(cluster_id):
        return "seg-abc"

    async def fake_get_seg(cluster_id):
        return dict(seg_state)

    captured = {}
    async def fake_insert(**kwargs):
        captured.update(kwargs)
        seg_state["title"] = kwargs.get("title", seg_state["title"])
        seg_state["caption"] = kwargs.get("caption", seg_state["caption"])
        seg_state["video_url"] = kwargs.get("video_url", seg_state["video_url"])
        return "seg-abc"

    fake_runs = [Run(id="p1_run_0", parent_id="p1", parent_path=str(tmp_path/"p1.mp4"),
                     start_offset_sec=0.0, end_offset_sec=3.0,
                     member_child_ids=["p1_child_0"],
                     vec=np.zeros(512, dtype=np.float32))]
    (tmp_path/"p1.mp4").write_bytes(b"fake")

    async def fake_stitch(refs, out):
        from pathlib import Path as P
        P(out).write_bytes(b"stitched")
        return out

    async def fake_caption(cid, centroid, children):
        return {"title": "T", "caption": "C", "location": "Pasadena, CA", "source": "vision"}

    async def fake_set_inflight(cid, val, ttl_seconds=None):
        return True

    class FakeCluster:
        centroid = np.ones(512, dtype=np.float32) / np.sqrt(512)

    monkeypatch.setattr(compile_mod, "_run_orchestrator_chain", fake_orch)
    monkeypatch.setattr(compile_mod.db, "get_segment_for_cluster", fake_get_seg)
    monkeypatch.setattr(compile_mod.db, "insert_segment", fake_insert)
    monkeypatch.setattr(compile_mod.db, "set_compile_in_flight", fake_set_inflight)
    monkeypatch.setattr(compile_mod, "compute_runs_for_cluster",
                        lambda cid: _async_return(fake_runs))
    monkeypatch.setattr(compile_mod, "stitch_clips", fake_stitch)
    monkeypatch.setattr(compile_mod, "generate_caption", fake_caption)
    monkeypatch.setattr(compile_mod, "_get_children_with_vecs",
                        lambda cid: _async_return([{"id": "p1_child_0", "vec": np.ones(512, dtype=np.float32)}]))
    monkeypatch.setattr(compile_mod, "config", compile_mod.config)
    monkeypatch.setattr(compile_mod.config, "DATA_DIR", tmp_path)
    monkeypatch.setitem(compile_mod.CLUSTERS if hasattr(compile_mod, "CLUSTERS") else {}, "c1", FakeCluster())
    # Patch CLUSTERS via the cluster module since compile imports it locally:
    from backend.pipeline import cluster as cluster_mod
    monkeypatch.setitem(cluster_mod.CLUSTERS, "c1", FakeCluster())

    await compile_mod.compile_segment("c1")
    assert captured.get("title") == "T"
    assert captured.get("caption") == "C"
    assert captured.get("video_url", "").endswith("_compiled.mp4")
```
Add a tiny helper at the top of the test file (if not present):
```python
async def _async_return(value):
    return value
```

**Step 2: Run + verify pass**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile.py::test_compile_segment_happy_path -v`
Expected: PASS

**Step 3: Update or delete the other tests in `test_compile.py`**

Open the file and walk each remaining test (timeout, fallback, etc.). For tests that referenced `extract_cluster_keyframes`, `_run_caption_writer_with_vision`, or the dual-branch `query` mock: replace the mock surface to use Branch A / Branch B helpers per Step 1 pattern. Run after each fix.

Run: `backend/.venv/bin/python -m pytest backend/tests/test_compile.py -v`
Expected: all PASS

**Step 4: Commit**

```bash
git add backend/tests/test_compile.py
git commit -m "test_compile: rewrite for parallel branches + run granularity"
```

---

### Task 6.6: End-to-end mock-mode integration test

**Behavioral check:** With `USE_MOCK_EMBEDDINGS=true`, posting two clips to the same coords/timestamp produces a segment whose `title` and `caption` come from the mock-mode caption pipeline and whose `ordered_clip_ids` are run IDs (matching the regex `.*_run_\d+$`).

**Files:**
- Modify: `backend/tests/test_pipeline_integration.py`

**Step 1: Add the integration test (mock mode)**

Append:
```python
import re

@pytest.mark.asyncio
async def test_full_pipeline_produces_run_segment(monkeypatch, tmp_path):
    monkeypatch.setenv("USE_MOCK_EMBEDDINGS", "true")
    # ... existing fixture setup that hits POST /clips twice ...
    # Then poll get_segment_for_cluster until non-None or 5s elapsed.
    # Assertion sketch:
    seg = await db.get_segment_for_cluster(cluster_id)
    assert seg is not None
    run_ids = json.loads(seg["ordered_clip_ids"])
    assert run_ids, "segment must carry at least one run_id"
    for rid in run_ids:
        assert re.match(r".*_run_\d+$", rid), f"not a run id: {rid}"
    assert seg["title"]  # mock-mode supplies a title
    assert seg["caption"]
```
(Adapt the setup to the existing test's fixtures — re-use the existing `monkeypatch` patterns in the file.)

**Step 2: Run + verify pass**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_pipeline_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/tests/test_pipeline_integration.py
git commit -m "integration: full pipeline emits run-id segments + title"
```

---

## Milestone 7: Frontend — surface the title

**Goal:** Feed cards display the new `title` field above the existing caption. Backend `/feed` already returns the column post-M4.
**Acceptance test:** Open `make backend-mock` + `make frontend`; ingest two staged clips; segment card in the feed shows the title in larger type with the caption beneath.

### Task 7.1: Type + render the title in the feed

**Behavioral check:** A segment in the rendered feed shows `<h3>{title}</h3>` followed by the existing caption paragraph. If `title` is empty/null, the title element does not render (no empty `<h3>`).

**Files:**
- Modify: `frontend/src/types/segment.ts` (or wherever the `Segment` type lives — find it via `grep -rn "ordered_clip_ids" frontend/src`)
- Modify: the segment-card React component (find via `grep -rn "caption" frontend/src/components | head`)

**Step 1: Locate the types**

Run: `grep -rn "ordered_clip_ids" /Users/liamshalom/Hacktech/frontend/src/ | head -5`

**Step 2: Add `title?: string | null` to the segment type**

Add the field to the existing `Segment` (or equivalent) interface.

**Step 3: Render in the card**

In the segment-card component, just above the existing `<p>{caption}</p>` (or equivalent), add:
```tsx
{segment.title ? (
  <h3 className="text-base font-semibold leading-tight">{segment.title}</h3>
) : null}
```
Match the existing Tailwind class conventions in the file.

**Step 4: Sanity check via dev server**

Run (from repo root):
```bash
make backend-mock
```
And in another terminal:
```bash
make frontend
```
Open the displayed URL in a browser, ingest two staged clips, and confirm a segment with both title + caption appears.

**Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feed: render segment title above caption"
```

---

## Wrap-up

Final verification — run the full backend test suite from repo root:

```bash
backend/.venv/bin/python -m pytest backend/tests/ -v
```
Expected: all PASS.

Then run the demo path:
```bash
make reset
make backend-mock
# in another terminal:
make frontend
```
Ingest two staged clips at the same coords. Expected:
- SSE shows `compile_started` then `segment_published`
- Final segment in feed has a title and a caption derived from the synthesis call
- The stitched `.mp4` contains only the runs the angle-selector chose (verify by length: total run durations < total parent durations)

---

## Progress
- [x] M1.1: Runs module skeleton — `9964976`
- [x] M1.2: Single-parent collapse → one run — `a2c4593`
- [x] M1.3: Scene-cut splits into two runs — `c27a183`
- [x] M1.4: Multi-parent → independent run namespaces — `12dfcd0`
- [x] M1.5: Empty + single-child edge cases — `eeebbf1`
- [x] M2.1: Add `RUN_THRESHOLD` to config — `c97e4b7`
- [x] M2.2: `compute_runs_for_cluster` coroutine — `40fa7d5`
- [x] M2.3: Childless-parent fallback test — `3fe38f2`
- [x] M2.4: Replace MCP tool with `get_cluster_runs` — `e659cd2`
- [x] M3.1: Subagent prompts pivot to runs — `fcc0cc9`
- [x] M3.2: `save_segment` accepts `ordered_run_ids` + `title` — `2cb6703`
- [x] M4.1: Migration — add `segments.title` — `7e58fec`
- [x] M4.2: `insert_segment(title=...)` — `c1e7900`
- [x] M6.1: Run resolver helper — `4e2e04b`
- [x] M6.2: Branch A — angle-chain → stitch — `0532b1f`
- [x] M6.3: Branch B — describe → synth (via existing generate_caption) — `5151959`
- [x] M6.4: Wire branches into compile_segment — `f609de7`
- [x] M6.5: Update test_compile.py + test_compile_timeout.py — `7c3ecfd`

## Decision Log
| Task | Decision | Rationale |
|------|----------|-----------|
| M2.1 | Bundled pre-existing 3-line `VISUAL_FLOOR` comment removal into the `RUN_THRESHOLD` commit. | The user's working tree had an uncommitted comment delete in `backend/config.py` from before this session. Splitting it out would have required restoring then re-deleting the comments, risking loss of intent. Both changes are config-file-scoped and atomic. |
| M3.2 | Test passed green (rather than failing as plan Step 4 predicted). | Plan expected `db.insert_segment` to reject `title=` kwarg, but the test mocks `db.insert_segment` with `AsyncMock`, which silently accepts arbitrary kwargs. Real-DB rejection is now caught only at M4.2. Not changing the test — the mocked-call assertion is still correct contract for the MCP tool. |

## Surprises & Discoveries
- M1.1 commit unexpectedly bundled `frontend/src/components/SegmentCard.test.tsx` (new) and a modification to `frontend/src/components/SegmentCard.tsx`. These were not in `git add` — appears to be a hook auto-staging frontend test files. Files unrelated to the plan; commit went through OK. Frontend-side commits also appeared between my batches (e.g. `6264e71`, `e736cb2`, `39c46c1`, `a19145b` for video-on-scroll feed work). Confirmed not blocking; backend tests unaffected.
- **Pre-existing M1-M4 wrap-up failures**: `test_compile_timeout.py::test_compile_segment_timeout_uses_fallback` and `..._exception_uses_fallback` fail with `TypeError: object MagicMock can't be used in 'await' expression` (the test mocks `db.fetch_cluster_clips_with_children` with a regular `MagicMock` but `_get_children_with_vecs` awaits it). Verified failing on `842b97d` (last commit before plan started) — pre-existing, not caused by my changes. M6.5 in the plan already explicitly slates these for rewrite as part of the compile-orchestration restructure.

## Unresolved questions

- run threshold tuning vs real Marengo embeddings — 0.85 is a reasonable starting prior; calibrate against a staged scene-cut clip if results look wrong
- run granularity for clips with N children all of which are similar but the content semantically shifts — current design = one big run; may want max-duration cap (e.g., 12s) later
- title length 60 chars is arbitrary; revisit after seeing real outputs
- should distinct_parents be the source_count, or should run count be? current plan: distinct_parents (preserves "N contributors" framing)
- frontend title style (font / weight / spacing) — currently inheriting existing Tailwind tokens; design pass post-MVP
- mock-mode caption now emits same fixed strings every time — fine for the demo, but unit tests of the integration end-to-end should not rely on those exact strings if you ever change them
