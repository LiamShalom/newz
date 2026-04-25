---
phase: "045-sub-clip-embed-caption"
plan: "01"
subsystem: backend/pipeline
tags: [embedding, segmentation, db-schema, twelve-labs, children]
dependency_graph:
  requires: []
  provides: [child-clip-schema, segmented-embed, run-pipeline-child-dispatch]
  affects: [backend/db.py, backend/pipeline/embed.py, backend/pipeline/run.py]
tech_stack:
  added: []
  patterns: [idempotent-alter-table, deterministic-child-id, embed-scope-segmentation]
key_files:
  created: []
  modified:
    - backend/db.py
    - backend/pipeline/embed.py
    - backend/pipeline/run.py
decisions:
  - "Child clip id is deterministic: {parent_id}_child_{int(start_offset_sec)} — enables idempotent INSERT OR IGNORE"
  - "Child path stored as empty string — children reference parent file + offsets for ffmpeg (Wave 2)"
  - "Short clips (<=3s, no children returned by Marengo) fall back to parent entering clustering directly"
  - "compile_candidates deduplicates cluster_ids; only first eligible cluster fires compile per upload batch"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-25"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 3
---

# Phase 045 Plan 01: Sub-Clip Embedding — DB Child Schema + Embed Segmentation + run.py Dispatch Summary

**One-liner:** Marengo native 3s segmentation producing child clip rows per upload, with DB schema migration, embed pipeline returning (child_id, vec) pairs, and run_pipeline dispatching children to cluster_worker.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | DB schema migration — parent_id + offset columns + child helpers | 6110526 | backend/db.py |
| 2 | embed.py — native segmentation + updated embed_worker return type | 6110526 | backend/pipeline/embed.py |
| 3 | run.py — dispatch children to cluster_worker | 6110526 | backend/pipeline/run.py |

## What Was Built

### Task 1: DB Schema (backend/db.py)

- Added `CREATE INDEX IF NOT EXISTS idx_clips_parent_id ON clips(parent_id)` to SCHEMA_SQL
- Added idempotent Phase 4.5 migration block in `init()` for three new clips columns: `parent_id TEXT REFERENCES clips(id)`, `start_offset_sec REAL DEFAULT 0`, `end_offset_sec REAL DEFAULT NULL` — uses same PRAGMA table_info pattern as Phase 4 compile migrations
- Added `insert_child_clip(parent_id, start_offset_sec, end_offset_sec, lat, lng, ts, session_id) -> str` — deterministic child_id = `{parent_id}_child_{int(start_offset_sec)}`, INSERT OR IGNORE, child path is empty string
- Added `get_children_by_parent(parent_id) -> list[dict]` — SELECT ordered by start_offset_sec ASC

### Task 2: Embed Pipeline (backend/pipeline/embed.py)

- Updated module docstring to reflect new return types
- `_call_marengo` now returns `tuple[np.ndarray, list[dict], int]` — (parent_vec, children, latency_ms). Uses `embedding_scope=["clip", "asset"]` and `VideoSegmentation_Fixed(fixed=VideoSegmentationFixedFixed(duration_sec=3))`. Iterates response.data, routes items by embedding_scope, normalizes each vector. Falls back to first child if asset-scope missing; raises RuntimeError if no embeddings at all.
- `_sync_embed` now returns `tuple[np.ndarray, list[dict], int]`. Mock mode generates 3 deterministic fake children at 0-3s, 3-6s, 6-9s using `_mock_embedding` keyed by `{clip_id}_child_{i*3}`.
- `embed_worker` now returns `list[tuple[str, np.ndarray]]`. Always stores parent embedding. If no children (short clip), returns `[(clip_id, parent_vec)]`. Otherwise inserts child rows via `db.insert_child_clip` and stores each child embedding, returns `[(child_id, vec), ...]`.

### Task 3: Pipeline Dispatch (backend/pipeline/run.py)

- `run_pipeline` unpacks `child_pairs = await embed_worker(clip_id)` — a list of (id, vec) tuples
- Loops `for cid, vec in child_pairs:` calling `cluster_worker(cid, vec)` per pair, collecting cluster_ids into `compile_candidates: set[str]`
- After clustering loop, iterates compile_candidates and fires `compile_segment` for the first cluster that passes `_should_compile` — breaks after first to avoid multiple compiles per upload batch

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Child rows have empty `path` strings by design (intentional — Wave 2 stitch/caption will use parent path + offsets for ffmpeg extraction). This is not a stub; it is the specified contract documented in the plan's must_haves.

## Threat Flags

No new security surface introduced beyond what was specified in the plan's threat model.

## Self-Check

- [x] backend/db.py exists and parses cleanly
- [x] backend/pipeline/embed.py exists and parses cleanly
- [x] backend/pipeline/run.py exists and parses cleanly
- [x] Commit 6110526 exists

## Self-Check: PASSED
