---
title: Cluster on parents — design decision
date: 2026-04-25
context: Phase 4.6 prep; reverses Phase 4.5 child-clustering for demo simplicity
---

# Cluster on parents — design decision

## Decision

Flip clustering unit from **children** (Phase 4.5) back to **parents** (whole uploads).
Children remain in the DB but only as compile-time slicing metadata
(`parent_id`, `start_offset_sec`, `end_offset_sec`, embedding for angle-selector use)
— they no longer carry `cluster_id`.

Add a publish gate: **compile fires only when a cluster has ≥2 parent members.**
Single-uploader clusters never produce a segment.

## Why

### Calibration was tuned on parents

Git timeline (verified):

```
e928689  Apr 25  feat(03-02): add calibration notebook   ← thresholds set
df465ac  Apr 25  fix(03): visual floor calibration       ← VISUAL_FLOOR tuned
6110526  Apr 25  feat(045): sub-clip embedding           ← children introduced AFTER
```

`CLUSTER_THRESHOLD=0.55` and `VISUAL_FLOOR` were dialed in against parent-level
(asset-scope) Marengo embeddings. Phase 4.5 then applied those same thresholds
to child (clip-scope) embeddings without re-tuning. The notebook still passes
CLU-07 because children-of-same-parent score ~0.99 cosine and fuse trivially —
the test validates child co-clustering, not threshold correctness for the new unit.

**Implication:** flipping back to parent-clustering is the zero-tuning-cost direction.

### Demo failure mode is staged-fusion + stage debugability, not multi-event uploads

Per `.planning/PROJECT.md` and demo memory: 60-second window, 4 staged contributors,
the team controls the dataset. Contributors will not film cross-event uploads in
60 seconds. Child-clustering's main earned-complexity win — handling "one parent
spans two events" — does not apply at this scope.

What matters for the demo:
- Staged 4-clip dataset fuses cleanly into one cluster
- Debug overlay reads cleanly on stage ("parent A: composite 0.73" beats
  "parent A child 2 of 5: composite 0.71, child 3: 0.68, child 1 below floor")
- Threshold story is defensible ("we calibrated it") not vibes-tuned

### Angle-selector still benefits from child slices

Children stay in DB with offsets + embeddings. Angle-selector queries
`get_cluster_clips_with_children` and picks the best ~3s windows across
parent members of the cluster. Same compile-time behavior, just cleaner
clustering semantics.

## Why ≥2-parent publish gate

A "cluster" with one parent is not a multi-angle event — it's a solo upload.
The product premise (anonymous crowdsourced footage → multi-angle compile)
is broken for solo clusters. Compiling them produces a single-source
"segment" that's just the original upload with a Claude-written caption,
which is not the demo story.

With parent-clustering, `member_count == parent_count` by construction —
the gate is a numeric check, no extra bookkeeping.

## What this touches (scope preview for Phase 4.6 plan)

- `backend/pipeline/embed.py` — `embed_worker` returns `(parent_id, asset_vec)`
  for clustering; child rows still get inserted but their vectors go to a
  child-only embedding store, not back to the cluster dispatcher.
- `backend/pipeline/run.py` — dispatch single `cluster_worker(parent_id, asset_vec)`
  instead of looping over children.
- `backend/pipeline/cluster.py` — no logic change; just receives parent vectors.
- `backend/pipeline/cluster.py` (compile trigger) — gate on `member_count >= 2`
  before kicking `compile_segment` via `asyncio.create_task`.
- `backend/db.py` — children no longer get `cluster_id` set on insert.
  `fetch_cluster_clips_with_children` already joins via parent's `cluster_id`
  → child membership; verify this still works (it should — children inherit
  via parent_id lookup, not via their own cluster_id).
- Calibration notebook — re-run to confirm CLU-07 / CLU-08 still pass against
  parent-clustered code path. Should pass cleanly since thresholds were
  originally tuned for this.

## Out of scope for the flip

- Removing child rows entirely (keep them — angle-selector + stitch need offsets)
- Re-tuning thresholds (calibration was already on parents)
- Touching the compile orchestrator chain (angle-selector / editor / publisher
  unchanged — they read children via `get_cluster_clips_with_children`)
