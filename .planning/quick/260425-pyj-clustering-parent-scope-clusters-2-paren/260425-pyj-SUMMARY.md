---
phase: quick-260425-pyj
plan: 01
subsystem: backend/pipeline
tags: [clustering, compile-gate, pivot, phase-4.6]
requirements:
  - CLU-01
  - CLU-02
  - CLU-03
  - CMP-05
dependency_graph:
  requires:
    - backend/pipeline/embed.py (Phase 4.5 child-emit shape)
    - backend/pipeline/cluster.py (composite scoring untouched)
    - backend/db.py (Phase 4.5 child-clip schema with parent_id col)
  provides:
    - "embed_worker(clip_id) -> tuple[str, np.ndarray]  (one pair, parent only)"
    - "db.count_distinct_parents_in_cluster(cluster_id) -> int  (Pivot 2 gate primitive)"
    - "fetch_cluster_clips_with_children walks parent_id (Pivot 1 compatible)"
  affects:
    - backend/pipeline/compile.py (transparently — _get_children_with_vecs unchanged)
    - backend/pipeline/compile_tools.py (transparently — same reader)
    - frontend (none — public surface unchanged)
tech_stack:
  added: []
  patterns:
    - "Forward-only gate: 2-parent check runs upstream of compile_segment dispatch (no wasted tokens / 60s budget on doomed compiles)"
    - "Defensive SQL: count_distinct_parents_in_cluster filters parent_id IS NULL even though Pivot 1 already keeps children's cluster_id NULL"
key_files:
  created: []
  modified:
    - backend/pipeline/embed.py
    - backend/pipeline/run.py
    - backend/db.py
    - backend/tests/test_pipeline_integration.py
    - backend/tests/test_cluster.py
decisions:
  - "Cluster on parent (asset-scope) vector only — restores Phase 3 calibration context"
  - "Children stay in DB with embeddings + parent_id, but cluster_id=NULL (Pivot 1)"
  - "compile_segment gated on >=2 distinct parent uploads (Pivot 2, the pitch gate)"
  - "Forward-only: no schema migration, no Phase 3 history rewrite"
metrics:
  duration_minutes: 12
  completed_date: "2026-04-25"
  tasks_completed: 3
  files_modified: 5
  commits: 2
---

# Quick Task 260425-pyj: Clustering Parent-Scope + 2-Parent Compile Gate Summary

Locked architectural pivots applied: clustering reverts to parent (asset-scope) vectors only (Pivot 1), and `compile_segment` is now gated on >=2 distinct parent uploads (Pivot 2) — the multi-angle pitch gate.

## What Changed

**Pivot 1 — `embed_worker` returns one pair (the parent), not a list of children.**
- `backend/pipeline/embed.py`: signature changed from `list[tuple[str, np.ndarray]]` to `tuple[str, np.ndarray]`. Children are still inserted via `db.insert_child_clip` and embedded via `db.store_embedding` (compile-time slicing metadata for Angle Selector / Caption Writer / stitch), but they no longer surface for clustering.
- `backend/pipeline/run.py`: deleted the votes loop. `cluster_worker` is now called exactly once per upload using the parent's asset-scope 512-d vector.

**Pivot 2 — 2-parent gate before compile dispatch.**
- `backend/pipeline/run.py::_should_compile`: now reads `db.count_distinct_parents_in_cluster(cluster_id)` and gates on `>= 2`. Old `cluster["member_count"] < 2` check removed (under Pivot 1 those values are equal, but the new SQL is defensive against any stray child cluster_id).
- `backend/db.py`: added `count_distinct_parents_in_cluster(cluster_id) -> int` with `SELECT COUNT(*) FROM clips WHERE cluster_id = ? AND parent_id IS NULL`.

**Backward-compatible reader rewrite.**
- `backend/db.py::fetch_cluster_clips_with_children`: rewritten as a two-step walk (find parent ids in cluster, then SELECT parents + their children via `parent_id IN (...)`). Output row shape preserved so `compile.py::_get_children_with_vecs` and `compile_tools.py::get_cluster_clips` need no changes.

## Tests Added / Updated

- `test_run_pipeline_creates_cluster_for_first_clip` — was failing on `main` (parent had no cluster_id under Phase 4.5). Now passes: parent is the cluster member.
- `test_solo_parent_cluster_does_not_trigger_compile` (NEW) — single mock upload with 3 children: asserts `member_count==1`, `compile_segment` NOT spawned, and SQL count of `parent_id IS NOT NULL AND cluster_id IS NOT NULL` is 0.
- `test_two_parents_triggers_compile` (NEW) — stubs `_mock_embedding` to return a fixed parent vector for two uploads; asserts `member_count==2`, `count_distinct_parents_in_cluster==2`, and `compile_segment` fires exactly once.
- `test_count_distinct_parents_in_cluster_ignores_children` (NEW) — confirms helper filters `parent_id IS NULL` even when a child row leaks a `cluster_id`.

## Verification

### Test results

`backend/.venv/bin/python -m pytest backend/tests/ -q`:

- **37 passed, 2 failed** (failures pre-existing and unrelated — see Deferred Issues).
- All 5 `test_pipeline_integration.py` tests pass.
- All 9 `test_cluster.py` tests pass.
- `test_db_clusters.py` and `test_segments_db.py` untouched, still pass.

### AST verify (Task 1 hook)

```
$ python -c "ast.parse(...).embed_worker.returns -> 'tuple[str, np.ndarray]'"
OK embed_worker signature: tuple[str, np.ndarray]
```

### Grep gates — all green

| Gate | Pattern | Expected | Result |
|------|---------|----------|--------|
| Pivot 1: no child cluster assignment | `assign_clip_to_cluster.*child` in `backend/pipeline/` `backend/db.py` | empty | empty |
| Pivot 1: list return type gone | `list\[tuple\[str, np.ndarray\]\]` in embed.py | empty | empty |
| Pivot 1: tuple return type present | `tuple\[str, np.ndarray\]` in embed.py | matches | 2 matches (docstring + signature) |
| Pivot 2: votes loop gone | `votes` in run.py | empty | empty |
| Pivot 2: helper wired | `count_distinct_parents_in_cluster` in db.py + run.py | matches in both | 1 in db.py, 2 in run.py |
| Pivot 2: old member_count gate gone | `member_count.*< *2` in run.py | empty | empty |
| Forward-only | `ALTER TABLE` added in db.py diff | empty | empty |

### Live boot

Skipped — covered by `test_two_parents_triggers_compile` (positive gate) and `test_solo_parent_cluster_does_not_trigger_compile` (negative gate). The mock-embedding path in `_sync_embed` is the same code path the live demo would hit when `USE_MOCK_EMBEDDINGS=true`, so the integration tests give equivalent coverage to a manual `curl` smoke test.

## Deviations from Plan

None. Plan executed exactly as written. The only modification to existing tests called out in the plan (broadcast-order assertion in `test_run_pipeline_chains_embed_then_cluster_in_order`) was not needed — the existing assertion `["pipeline_progress:embedded", "cluster_assigned", "pipeline_progress:clustered"]` was already correct under the new single-call contract and passed unchanged.

## Deferred Issues

**Pre-existing test failures (out of scope per CLAUDE.md scope boundary):**

`backend/tests/test_compile_timeout.py` — both tests fail on `main` and continue to fail after this plan's changes. Root cause is in the test, not in production code:

```
File "backend/pipeline/compile.py", line 365, in compile_segment
    children = await _get_children_with_vecs(cluster_id)
File "backend/pipeline/compile.py", line 309, in _get_children_with_vecs
    rows = await db.fetch_cluster_clips_with_children(cluster_id)
TypeError: object MagicMock can't be used in 'await' expression
```

The tests `patch("backend.pipeline.compile.db")` as a generic `MagicMock` without setting `fetch_cluster_clips_with_children` to an `AsyncMock`. `compile_segment` calls `_get_children_with_vecs` BEFORE entering the `_run_agents` path the tests want to exercise, so the test fails before the patched timeout/exception ever fires. Pre-dates this plan; verified by running `pytest backend/tests/test_compile_timeout.py` against the base commit `add9f8c` — same failure.

Recommended fix (separate task): add `mock_db.fetch_cluster_clips_with_children = AsyncMock(return_value=[])` to both tests. Not done here per scope boundary.

## Commits

| # | Hash | Message |
|---|------|---------|
| 1 | `fa0a41c` | feat(260425-pyj): cluster on parents + 2-parent compile gate (Pivots 1+2) |
| 2 | `b81cb92` | test(260425-pyj): lock both pivots — solo-parent skip + 2-parent compile |

## Self-Check: PASSED

- [x] `backend/pipeline/embed.py` modified — `embed_worker` returns `tuple[str, np.ndarray]`
- [x] `backend/pipeline/run.py` modified — single `cluster_worker` call, `_should_compile` uses parent count
- [x] `backend/db.py` modified — `count_distinct_parents_in_cluster` exists, `fetch_cluster_clips_with_children` walks parent_id
- [x] `backend/tests/test_pipeline_integration.py` modified — 2 new tests
- [x] `backend/tests/test_cluster.py` modified — 1 new test
- [x] Commit `fa0a41c` exists in git log
- [x] Commit `b81cb92` exists in git log
- [x] All grep gates green
- [x] Pytest: 37 passed, 2 failed (pre-existing, documented)
