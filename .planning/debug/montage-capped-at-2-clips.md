---
slug: montage-capped-at-2-clips
status: resolved
trigger: "the current arch only allows segments to be 2 clips long, I want to allow segments to be at least 20s long worth of compiled clips"
created: 2026-05-01
updated: 2026-05-01
resolved: 2026-05-01
---

## Resolution (2026-05-01)

User selected Option B (prompt rewrite + deterministic budget guard). Applied:

**1. Prompt rewrite — `backend/pipeline/compile.py:111`**
- Dropped "best 2-4 RUNS" framing.
- New `RUNTIME BUDGET` section: total stitched runtime ≤ 20.0s, aim to fill ≥14s, target 3-5 runs at ~3-6s each. Explicit "Do NOT default to 2 runs when more eligible runs exist."
- Added `MONTAGE_RUNTIME_BUDGET_SEC = 20.0` constant; prompt uses `{budget_sec}` / `{budget_floor}` placeholders for single source of truth.
- Parent-diversity HARD CONSTRAINT preserved verbatim.

**2. Deterministic post-processor — `backend/pipeline/compile.py:_enforce_runtime_budget`**
- Mirrors `_enforce_parent_diversity` shape (read seg → load runs → mutate → re-insert).
- Extension: when `sum(durations) < target - 0.5`, append candidates in chronological order whose individual duration fits remaining budget.
- Trim: when `sum > target + 0.5`, drop trailing picks while preserving ≥2 distinct parents and ≥2 picks total.
- Synthetic full-parent runs (member_child_ids=[]) handled via `synthetic_run_estimate_sec` parameter (default 6.0).
- Helper `_run_duration_sec` extracted for reuse + isolated unit-testability.

**3. Wire-in — `backend/pipeline/compile.py:compile_segment`**
- Phase 1.6 step added immediately after Phase 1.5 (parent-diversity guard) at line ~640.
- Same try/except defensive pattern: a guard failure logs a warning and proceeds with whatever picks the segment row already has — never blocks the segment from publishing.

**4. Tests — `backend/tests/test_compile.py`**
- 5 new test cases: extends 2-pick to fill budget, no-op when no eligible candidates, trims when over budget while preserving 2 parents, no-op when picks empty, handles synthetic full-parent runs.
- Helpers `_mk_run` + `_mk_synthetic_run` factored out.

**Verification:** `pytest backend/tests/test_compile.py backend/tests/test_compile_resolve_runs.py backend/tests/test_compile_timeout.py backend/tests/test_compile_tools_runs.py backend/tests/test_compile_tools_save_segment.py backend/tests/test_runs.py backend/tests/test_runs_for_cluster.py backend/tests/pipeline/test_recompile.py` → 31 passed.

**Files changed:**
- `backend/pipeline/compile.py` (prompt rewrite + new helper + new guard + wire-in)
- `backend/tests/test_compile.py` (5 new tests + 2 helpers)

**Production validation pending:** the next live multi-parent cluster (≥3 parents) on Railway should produce a montage with 3-5 runs totaling ~14-20s. Inspect a freshly-published segment's `ordered_clip_ids` length on `/feed` JSON to confirm.

---

# Montage capped at 2 clips — desired: multi-clip up to ~20s runtime

## Symptoms

User-observed (not read in code): every produced **montage** on the feed currently
contains exactly 2 compiled clips. They want montages to contain more than 2
clips, with the **total stitched runtime not exceeding 20s** (i.e. multi-clip
montages bounded at ≤20s wall-clock playback, not capped at 2 clips).

> Project nomenclature reminder: legacy code may use "segment" — that is the
> **montage** in v1.1 nomenclature (final compiled multi-angle output). Do not
> rename existing identifiers; just be aware they map to the same concept.

### Expected behavior

- Montage = stitched compilation of N≥2 clips drawn from the cluster's
  videorecordings/children
- Total stitched runtime ≤ 20s (new constraint)
- Number of clips per montage = whatever fits within the 20s budget (more than 2
  when the cluster has the material to support it)

### Actual behavior

- Every montage on the live feed contains exactly 2 clips
- Even when a cluster has ≥3 distinct parent videorecordings (or ≥3 children),
  only 2 make it into the final montage

### Reproduction

User has been observing this on the production feed
(`https://newz-prod.up.railway.app/`) — every published montage caps at 2 clips.
No specific reproduction steps yet; need to inspect a recent multi-parent
cluster and trace why the compile pipeline emitted only 2 clips.

### Timeline

Behavior appears consistent across the v1.0 → v1.1 lifespan; not a recent
regression. Treat as an architectural/configuration cap to lift, not a
sudden break.

## Investigation goal

`find_and_fix` — locate where the 2-clip cap originates (could be: clustering
output, compile-pipeline tool definition, Claude Agent SDK prompt, ffmpeg
concat list construction, OR an LLM-side default in the multi-agent SDK
pipeline). Propose a fix that lets montages accumulate clips until the 20s
runtime budget is consumed.

**Project memory constraint:** Per `MEMORY.md` "Discuss before tuning fixes" —
for clustering / threshold / weight tweaks, **propose options + tradeoffs
first**, do not auto-apply. Surface the candidate fix to the user before edits.

## Investigation starting points

Strong suspects (unverified):

1. **`backend/pipeline/compile.py`** — orchestrates compile via Claude Agent SDK
2. **`backend/pipeline/compile_tools.py`** — likely defines the clip-selection
   tool exposed to the SDK; may hard-cap N or expose a `max_clips=2` default
3. **`backend/pipeline/stitch.py`** — ffmpeg concat list builder; check if it
   slices to 2 inputs
4. **`backend/pipeline/cluster.py`** — clustering composite score may be
   filtering out the 3rd+ candidate before it reaches compile
5. **Claude Agent SDK system prompt** — the LLM may be instructed to "pick the
   best 2 angles" or similar phrasing
6. **`backend/pipeline/run.py`** — orchestrator may be passing only top-2
   members of the cluster into compile

Secondary check:

- Inspect a recent live cluster on `/debug/clusters` (production):
  - Pick a cluster with `member_count ≥ 3`
  - Check `compile_runs` row for that cluster
  - Confirm only 2 of N clips ended up in the output `compile_run.clips_used`
    or equivalent

## Current Focus

```yaml
hypothesis: "Cap originates in the angle-selector LLM prompt: it asks for
             '2-4 RUNS' but Sonnet consistently picks the minimum (2). The
             parent-diversity guard floors at min_parents=2 so doesn't extend.
             No downstream cap; stitch + frontend both handle N>2 already."
test: "Inspected compile.py prompt template, runs.py, cluster.py, run.py,
       stitch.py + production /feed JSON for cluster with member_count=6"
expecting: "Confirmed prompt-driven cap. Lift requires: (a) prompt rewrite to
            target ≤20s total runtime instead of '2-4 runs', AND (b) add
            deterministic post-processor that trims/extends the LLM pick to
            satisfy the 20s budget."
next_action: "Surface fix options to user (per MEMORY 'discuss before tuning')"
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/compile.py:111
  finding: |
    `ANGLE_SELECTOR_PROMPT_TEMPLATE` opens with: "You are picking the best
    **2-4 RUNS** from cluster {cluster_id}." The lower bound is 2, upper is
    4. There's no runtime budget mentioned in the prompt — the LLM has no
    reason to pick more than 2 unless the criteria force it. Sonnet
    defaults to the minimum.

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/compile.py:398-458 (`_enforce_parent_diversity`)
  finding: |
    Deterministic guard runs after the LLM pick. Default `min_parents=2`
    (called as `_enforce_parent_diversity(cluster_id, min_parents=2)` at
    line 627). Floor only — augments the run list when fewer than 2
    distinct parents are represented. Does NOT cap upward, so it cannot
    be the cap, BUT also does not extend a 2-from-2-parents pick to 3+
    runs. Result: when the LLM picks 2 from 2 distinct parents, the
    guard returns immediately at line 426-427 (`if len(picked_parents) >=
    target: return`), so output stays at 2.

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/runs.py + config.py:36-39
  finding: |
    `RUN_THRESHOLD=0.70` and `MAX_RUN_MEMBERS=2`. With 3-second child
    windows, a single run is capped at 6 seconds (2 children × 3s). This
    means each "run" the LLM picks contributes at most 6 seconds to the
    final montage. Two runs ≈ ≤12s currently — fits under a 20s budget
    with significant headroom (room for 3-4 runs at 6s each).

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/run.py:42-50 (`_should_compile`)
  finding: |
    Compile gate is `parent_count >= 2`, not `== 2`. No cap on cluster
    size or members reaching compile. Eliminates run.py / cluster.py
    as the cap source.

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/stitch.py:32-80 (`_sync_stitch`) + compile.py:497 (`_trim_one`)
  finding: |
    Stitch builds an N-input ffmpeg concat filter graph (no slicing to 2
    inputs). `_stitch_segment_runs` calls `_trim_one` per run via
    `asyncio.gather` — fully N-aware. Frontend `SegmentCard.tsx:49` and
    `Montage.tsx:85` consume `video_urls` as N items. No downstream cap.

- timestamp: 2026-05-01T (manager investigation)
  source: production /feed JSON, cluster dc3fc885474f48a5aab019ed06377db1
  finding: |
    Cluster has `source_count: 6` (six distinct parents). Published
    segment `a5c1213fb1644d7d963bb86fb36ca46b` has only 2 entries in
    `ordered_clip_ids`: `5f3737f5...run_0` and `4ed5d8ee...run_0`. Two
    different parents, both `_run_0`. Confirms the LLM pick at 2 distinct
    parents → diversity guard satisfied → no augmentation. Same pattern
    on cluster `b5d28e5a...` (member_count 2, segment has 2 runs — but
    that's the floor, no upward signal).

## Eliminated

- ffmpeg stitch capping at 2 inputs — confirmed N-input concat filter graph
- Frontend capping `video_urls` rendering — handles arbitrary N
- Cluster-side filter producing only 2 candidates — no such filter
- `_should_compile` cap — gate is `>=2`, not `==2`
- `MAX_RUN_MEMBERS=2` is NOT the symptom cause: it caps each run at 6s, but
  the symptom is "only 2 runs", not "only 6s of footage". `MAX_RUN_MEMBERS`
  is relevant to fix sizing (informs how many runs fit in 20s budget), but
  is not the bug.

## Root cause

The 2-run cap is **prompt-driven, not architectural**. Two factors combine:

1. **`ANGLE_SELECTOR_PROMPT_TEMPLATE`** (compile.py:111) requests "best 2-4
   RUNS" — Sonnet consistently picks the lower bound when given a range.
2. **`_enforce_parent_diversity(min_parents=2)`** (compile.py:627) is a
   floor, not a target — when the LLM already returns 2 runs from 2
   distinct parents, the guard returns immediately without extending.

No downstream code (stitch, frontend, DB schema) caps N. The fix is entirely
in compile.py: rewrite the prompt to target a 20s runtime budget AND add a
deterministic post-processor that trims/extends the LLM pick to satisfy the
20s budget.

## Suggested fix direction

(specialist_hint: python)

Two-layer fix in `backend/pipeline/compile.py`:

**Layer 1 — Prompt rewrite.** Replace "2-4 RUNS" with a runtime-budget framing:

```
You are picking RUNS from cluster {cluster_id} to compile a montage.

BUDGET: total stitched runtime ≤ 20.0 seconds (sum of run durations).
Aim for as many runs as fit cleanly under budget — typically 3-5 runs.
Minimum 2 runs (parent diversity is required).
```

Keep the existing parent-diversity HARD CONSTRAINT and the temporal/spatial
ranking criteria. Drop the "2-4" range entirely; replace with budget framing.

**Layer 2 — Deterministic post-processor.** Add a `_enforce_runtime_budget`
helper that runs alongside `_enforce_parent_diversity`. Behavior:

- If sum(run.duration) for picked runs is well under 20s AND additional
  unpicked runs exist with new spatial/temporal diversity, extend.
- If sum > 20s, trim trailing runs until ≤20s (preserve chronological order).
- Belt-and-suspenders: do NOT trust the LLM to obey the budget alone, same
  philosophy as `_enforce_parent_diversity`.

Both `MAX_RUN_MEMBERS=2` (6s per run cap) means an LLM pick of 3-4 runs lands
in the 12-18s sweet spot; 4 runs × 6s = 24s would just barely overshoot, so
the post-processor would trim to 3 runs ≈ 18s. Math works for the 20s target.

**Wall-clock impact (300s LLM budget consideration):**

- Per-run trim is ~0.5-1.0s ffmpeg time, parallelized via `asyncio.gather`
  in `_stitch_segment_runs`. Going from 2 → 4 runs in parallel adds ~0
  wall-clock (still <2s). Stitch budget is 30s — plenty of headroom.
- Caption pipeline runs unchanged (centroid-closest children, not per-run).
- Angle-selector LLM may take 1-2 more turns to produce a longer run list,
  but max_turns=20 is generous. Total LLM phase well within 180s inner cap.

**Anonymity / iOS / OFFLINE_DEMO:** unaffected (server-side compile-only fix).

## Specialist Review

(pending dispatch to python-expert-best-practices-code-review)
