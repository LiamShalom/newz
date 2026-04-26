---
spike: 002
name: compile-baseline
type: standard
validates: "Given a 3-clip cluster, when compile_segment runs (gather of _run_agents ‖ stitch_clips ‖ generate_caption) N times, then we see per-track ms vs. a serial baseline — quantifying what the Phase 4.5 parallelization actually buys"
verdict: REWIRED — pending re-run
related: [001]
tags: [compile, claude-agent-sdk, latency, parallelization]
---

# Spike 002: compile-baseline

## What This Validates

Given a 3-clip throwaway cluster (built from `backend/seed/demo/realworld-{1,2,3}.mp4`), the bench runs the **new compile_segment shape** — three coroutines inside `asyncio.gather` — and measures per-track wall-clock against a serial baseline.

| Track | What runs | Source |
|-------|-----------|--------|
| **A** | `_run_agents` — caption-writer + angle-selector → editor → publisher | `compile.py:297-304` |
| **B** | `stitch_clips` — ffmpeg concat to `.webm` | `stitch.py:57` |
| **C** | `generate_caption` — frame-based Haiku/Sonnet visual caption | `caption_pipeline.py:89` |

Two modes per run, on independent fixtures:

- **parallel** — replicates `compile_segment`'s body with per-track timing wrappers and a configurable cap (default 300s; bypasses the prod 60s `wait_for` so we get raw numbers instead of always-`TimeoutError`).
- **serial** — same three coroutines awaited sequentially. Apples-to-apples baseline for the pre-overhaul shape.

The headline numbers:

```
parallel_total_ms ≈ max(track_a, track_b, track_c)
serial_total_ms   ≈ track_a + track_b + track_c
saved_ms          = serial - parallel
speedup_x         = serial / parallel
```

If `track_a` dominates (orchestrator chain ≈ 112s), the gather's wall-clock floor IS `track_a`, and the speedup is just `(track_b + track_c) / track_a` — which is small until track A is shrunk.

## Why this rewire was needed

The earlier version of `bench.py` called `_run_caption_writer_with_vision` and `_run_orchestrator_chain` directly, sequentially, with manual timers — it never invoked `compile_segment`, never entered the `asyncio.gather` block, and never ran `stitch_clips` or `generate_caption`. The numbers it produced were identical in shape to pre-overhaul timing. See `.planning/debug/spike-002-bottleneck.md` for the full diagnosis.

This rewire fixes that by:
1. Replicating `compile_segment`'s body inline (so the 60s prod cap can be raised for measurement).
2. Wrapping each branch with a per-track timer.
3. Running a paired serial baseline on a separate fixture, same RNG-seeded embeddings.
4. Inserting `clip_embeddings` rows + populating `CLUSTERS[cluster_id]` so `centroid is not None` and Track C runs the real path (not the `asyncio.sleep(0)` short-circuit).

## How to Run

From repo root, with `ANTHROPIC_API_KEY` set in env (read by claude-agent-sdk via the bundled CLI):

```bash
# Default: 3 parallel + 3 serial runs, 3 clips each. Cap at 300s for raw numbers.
./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 3

# Parallel only (skip serial baseline)
./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 3 --mode parallel

# Reproduce production exactly (60s cap → expect TimeoutError on Track A)
./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 1 --cap 60

# Smaller cluster, keep fixture for inspection
./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 1 --clips 1 --keep
```

Each run inserts one cluster + N clips + N `clip_embeddings` (random 512-d unit vectors, seeded by `--seed`) and registers a `ClusterCache` in memory. Cleanup deletes all four (cluster, clips, embeddings, segment) unless `--keep`.

Cost per parallel run: orchestrator (sonnet x2 + haiku) + caption-writer (sonnet+vision) + generate_caption (haiku x ≤3 + sonnet) — Track C adds Haiku calls on top of the old harness.

## What to Expect

- Per-run line per mode with track-A/B/C ms + total ms + `prod_timeout=YES/no` flag (parallel only).
- Two summary tables (PARALLEL, SERIAL) with min/p50/p95/max for each track + total.
- Comparison block: `serial_total_ms`, `parallel_total_ms`, `saved`, `speedup`.
- Failures listed at the bottom (orchestrator publisher silently no-call'ing `save_segment`, generate_caption falling through to fallback caption, etc).

## Investigation Trail

- **Original bench** measured the orchestrator sub-stages directly, never the new gather. See debug session `.planning/debug/spike-002-bottleneck.md`.
- **Rewire** mirrors `compile_segment`'s body in the harness rather than calling `compile_segment` itself. Reasons: (1) prod's 60s `asyncio.wait_for` would always trip with `track_a ≈ 112s`, (2) per-track timing requires wrapping each branch which can't be done from outside `compile_segment`, (3) we want a clean serial baseline running the *same* coroutines.
- **Cost of rewire**: bench drifts if `compile_segment`'s body changes shape (e.g. adds a fourth track). Acceptable — this is a spike, not a regression suite.

## Results

### Pre-rewire (deprecated — these numbers measure the wrong system)

The earlier run on the same hardware/seed clips: orchestrator 112575 ms, caption 7076 ms, keyframes 61 ms, total 119712 ms. Now understood as Track A ≈ 120s when run serially. Track A alone exceeds the 60s prod cap.

### Post-rewire

Pending re-run. Expectations from the orchestrator-dominant breakdown:

- `track_a_ms` ≈ 110-120s (unchanged — `_run_agents` body is the same)
- `track_b_ms` ≈ 1-3s (ffmpeg concat of three short demo clips)
- `track_c_ms` ≈ 5-15s (Haiku x3 frame description + Sonnet headline)
- `parallel_total_ms` ≈ `track_a_ms` (gather wall-clock = max branch)
- `serial_total_ms` ≈ sum of all three ≈ `track_a_ms + 6-18s`
- `speedup` ≈ 1.05-1.15x — the gather saves ~10s, but that's a rounding error against the 120s Track A floor
- `would_timeout_at_60s` = YES on every run until Track A drops below 60s

If those numbers come back materially different, update this section and `.planning/debug/spike-002-bottleneck.md` Resolution.

### Pivot signals (read this, don't act yet)

- The parallelization buys roughly `track_b + track_c` ≈ 6-18 seconds. That's real, but irrelevant while Track A is at 120s.
- The real lever for hitting the 30s demo target is **shrinking Track A**: parallelize sub-agents inside the orchestrator chain, drop the editor stage, demote publisher to a direct DB write, or replace the SDK chain with a single hand-orchestrated query.
- Compression / URL upload optimizations on embed (Spike 001) save ~1.4s. Still table-scraps.

### Caveats

- Track C uses RNG-seeded random embeddings (not real Marengo vectors). The `_select_caption_children` cosine ranking will be approximately random across runs, but the *timing* is unaffected — generate_caption still does Haiku x3 + Sonnet regardless of which children are selected.
- The bench inserts/deletes against the live `newz.db` with a `bench` prefix on all IDs. Don't run while users are uploading.
- Setting `--cap 60` reproduces the exact prod failure mode (TimeoutError on Track A). Useful for confirming `_save_fallback_segment` would always be triggered today.
