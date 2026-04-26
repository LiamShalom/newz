---
slug: spike-002-bottleneck
status: resolved
trigger: |
  DATA_START
  Roan kept _run_agents as a wrapper around the OLD orchestrator chain (line 297-304).
  The new compile_segment runs asyncio.gather(_run_agents, stitch, generate_caption) —
  but since orchestrator chain is unchanged at ~85s and is one of the parallel tracks,
  total wall-clock is bottlenecked by it. Spike 002 as-is would re-measure the same chain.
  The genuinely new test is to bench compile_segment end-to-end.
  DATA_END
created: "2026-04-25"
updated: "2026-04-25"
---

# Debug Session: Spike 002 Bottleneck Investigation

## Symptoms

**Expected behavior:**
Spike 002 should benchmark the new `compile_segment` architecture end-to-end — measuring whether the parallel `asyncio.gather(_run_agents, stitch, generate_caption)` design improves wall-clock time vs. the pre-parallelization sequential chain.

**Actual behavior (suspected):**
`_run_agents` is allegedly a thin wrapper around the unchanged ~85s orchestrator chain at lines 297-304. Since `_run_agents` is one branch of `asyncio.gather`, total wall-clock is bottlenecked by it (max of N parallel tracks = at least 85s). Spike 002 measures the same chain it always did; the parallelization is a no-op in terms of measured improvement.

**Error messages:** None — this is a design / measurement-validity issue, not a runtime failure.

**Timeline:** Discovered while reviewing Roan's recent compile pipeline overhaul (commit 9dfc527, fd14662).

**Reproduction:**
1. Read `backend/.../compile.py` around lines 297-304 — verify `_run_agents` wraps the old chain
2. Read `compile_segment` — verify `asyncio.gather(_run_agents, stitch, generate_caption)` structure
3. Read Spike 002 plan/script — verify what it actually times

## Investigation Goal

1. **Verify the wrapper claim** — does `_run_agents` at line 297-304 in fact wrap the old orchestrator chain unchanged?
2. **Trace the workflow** — what does `compile_segment` actually do, and how do `_run_agents` / `stitch` / `generate_caption` interact?
3. **Confirm the measurement gap** — would Spike 002 as currently designed produce a number that is meaningfully different from the pre-overhaul orchestrator chain timing?

## Current Focus

- hypothesis: `_run_agents` is a passthrough to the unchanged ~85s orchestrator chain; `asyncio.gather` masks no real concurrency benefit because the gather's wall-clock = max(parallel branches) and `_run_agents` dominates. Spike 002 would re-measure the old chain and miss that the new architecture's actual gain (if any) comes from `stitch` / `generate_caption` overlapping with `_run_agents` — which only matters if `stitch` + `generate_caption` were previously serial *after* the chain.
- test: Read compile.py around line 297-304, read compile_segment, read Spike 002 setup. Confirm wrapper structure + what spike measures.
- expecting: `_run_agents` body == old orchestrator chain; spike script times `_run_agents` directly OR times something equivalent in cost; the genuinely new measurement (compile_segment end-to-end vs. pre-overhaul total) is NOT what spike 002 captures.
- next_action: Locate compile.py and Spike 002 plan, read both, verify workflow.

## Evidence

- timestamp: 2026-04-25 — file: `backend/pipeline/compile.py:297-304` — `_run_agents(cluster_id)` body is exactly two awaits: `caption_data = await _run_caption_writer_with_vision(cluster_id)` then `return await _run_orchestrator_chain(cluster_id, caption_data)`. No new concurrency, no restructuring. **Wrapper claim is TRUE.**
- timestamp: 2026-04-25 — file: `backend/pipeline/compile.py:339-392` — `compile_segment` runs three coroutines via `asyncio.gather(_run_agents(cluster_id), stitch_clips(stitch_refs, output_path), generate_caption(cluster_id, centroid, children), return_exceptions=True)` inside `asyncio.wait_for(..., timeout=60.0)`. Confirmed Track A = `_run_agents` (caption-writer + 3-subagent chain), Track B = `stitch_clips` (ffmpeg concat), Track C = `generate_caption` (frame-based Haiku/Sonnet vision call).
- timestamp: 2026-04-25 — file: `backend/pipeline/compile.py:209-294` — `_run_caption_writer_with_vision` is one sonnet+vision `query()` call; `_run_orchestrator_chain` runs sonnet (angle-selector) → sonnet (editor) → haiku (publisher) inside a single SDK session. Both bodies are unchanged from the pre-overhaul code.
- timestamp: 2026-04-25 — file: `.planning/spikes/002-compile-baseline/bench.py:92-119` — `bench_one()` calls `extract_cluster_keyframes`, then `_run_caption_writer_with_vision`, then `_run_orchestrator_chain` *sequentially* with `time.monotonic()` between them. **It does NOT call `compile_segment` and does NOT call `stitch_clips` or `generate_caption`.** The asyncio.gather code path is never exercised.
- timestamp: 2026-04-25 — file: `.planning/spikes/002-compile-baseline/README.md:14-20,47-86` — Spike 002 explicitly documents itself as measuring `keyframe_ms / caption_ms / orchestrator_ms / total_ms`, which are the same three slices that existed before the overhaul. Verdict already recorded as VALIDATED with p50 total = 119712 ms (≈120s, dominated by orchestrator at 112575 ms / 94%).
- timestamp: 2026-04-25 — file: `backend/pipeline/stitch.py:57` and `backend/pipeline/caption_pipeline.py:89-124` — Tracks B and C are real coroutines that do nontrivial work (ffmpeg subprocess, Anthropic API calls). They are *not* `asyncio.sleep(0)` no-ops — though `compile_segment` does fall back to `asyncio.sleep(0)` for Track C when `centroid is None or not children` (line 388).

## Eliminated

- "Roan added concurrency inside `_run_agents`" — eliminated. The function body is two sequential awaits.
- "Spike 002 was updated to call `compile_segment`" — eliminated. `bench.py` imports only `_run_caption_writer_with_vision` and `_run_orchestrator_chain`; `compile_segment` is never called.
- "Tracks B and C are stubs that don't add real concurrency value" — eliminated. They make their own subprocess / API calls and run for nontrivial wall-clock time.

## Resolution

### root_cause

The user's structural analysis is **correct on all three points**:

1. **`_run_agents` IS a thin wrapper around the unchanged orchestrator chain.** `compile.py:297-304` is literally `await _run_caption_writer_with_vision(...)` then `return await _run_orchestrator_chain(...)`. Same code as before, just wrapped in a function so it can be a gather branch.

2. **`asyncio.gather` wall-clock IS bottlenecked by `_run_agents`.** Spike 002's recorded p50 of 119.7s breaks down as caption=7.1s + orchestrator=112.6s, all serial inside Track A. Even if Tracks B (stitch) and C (generate_caption) finish in zero time, `compile_segment` cannot return faster than ~120s — well past the 60s `asyncio.wait_for` cap, which means in production this run *always* hits TimeoutError and falls through to `_save_fallback_segment`. Tracks B and C overlapping with Track A only saves wall-clock equal to `min(B, C, A)` = essentially `B + C` time (since both are <<A); it does *not* shrink Track A itself.

3. **Spike 002 as written does NOT measure the new architecture.** `bench.py:96-106` calls the three sub-stages sequentially with manual timers — it never invokes `compile_segment`, never enters the `asyncio.gather` block, and never runs `stitch_clips` or `generate_caption`. The numbers it produces are identical in shape to what the spike would have measured pre-overhaul. The "compile_segment is ~120s" result the user is looking at is actually "caption + orchestrator chain serially is ~120s" — which is necessarily a lower bound on `compile_segment`'s wall-clock, but it's not the same number.

### Why the user's analysis is right (and what it implies)

The new architecture's *only* real wall-clock gain is `max(stitch, generate_caption) - 0` saved compared to running stitch+caption *after* the orchestrator chain serially. Given orchestrator alone is 112s and the cap is 60s, this gain is irrelevant — Track A blows the cap regardless. The parallelization buys nothing measurable until Track A drops below ~30s.

This is consistent with Spike 002's own "Pivot signals" section, which explicitly says: *"Parallelizing or removing stages directly attacks the 112s. Compression / URL upload optimizations on embed save ~1.4s. Worth doing only if compile is already sub-30s."* The current overhaul (parallel stitch + parallel generate_caption) is in the same "saves seconds while orchestrator burns minutes" category.

### What Spike 002 SHOULD measure to validate the overhaul

If the goal is to validate that the **new compile_segment architecture** is faster than the old serial pipeline, the spike must:

1. **Call `compile_segment(cluster_id)` directly** — not `_run_caption_writer_with_vision` + `_run_orchestrator_chain` independently. That's the only way to exercise the `asyncio.gather` path and the 60s cap.

2. **Measure two numbers per run**, not three slices:
   - `compile_segment_ms` — wall-clock from entry to `events.broadcast("segment_published")`
   - `track_a_ms`, `track_b_ms`, `track_c_ms` — per-branch durations (instrument inside the gather, e.g. wrap each coroutine with a timer wrapper, or record from inside via `time.monotonic()` and a shared dict)

3. **Compare against a "serial baseline"** that runs the same three coroutines sequentially with the same fixture. Without this comparison, the gather's benefit is invisible. Pseudocode:
   ```python
   # parallel
   t0 = monotonic(); await compile_segment(cid); parallel_ms = monotonic() - t0
   # serial baseline (same work, no gather)
   t0 = monotonic()
   await _run_agents(cid)
   await stitch_clips(refs, path)
   await generate_caption(cid, centroid, children)
   serial_ms = monotonic() - t0
   speedup = serial_ms / parallel_ms
   ```

4. **Decide what to do about the 60s cap.** With orchestrator alone at p50=112s, `compile_segment` will hit `asyncio.TimeoutError` and the timing data is meaningless (just records the cap). Either: (a) raise the cap to >120s for the spike only, (b) bypass `wait_for` in the spike and instrument `compile_segment` directly, or (c) accept that the spike will record "always times out" until the orchestrator is shrunk first.

### Bottom line

The user's read is right. Spike 002 in its current shape **cannot** validate the parallelization overhaul because (a) it doesn't run the parallelized code path at all, and (b) even if it did, Track A's 112s makes the gather's wall-clock ≥112s no matter what Tracks B and C do, and the 60s cap clips the whole thing to a TimeoutError fallback. The genuinely new measurement — does `compile_segment` end-to-end finish faster than serial caption+orchestrator+stitch+generate_caption? — is not what the current bench.py captures.

The fix is **not in compile.py** (which is doing what its docstring says). The fix is in the spike harness, OR — more importantly — in the orchestrator chain itself, since shaving Track A is the only way the cap holds.

### fix

**Not applied.** Goal was `find_root_cause_only`. No source code modified. No spike modified.
