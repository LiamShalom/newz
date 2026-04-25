---
spike: 002
name: compile-baseline
type: standard
validates: "Given a 3-clip cluster, when compile_segment runs N=3, then we see per-stage ms: keyframes, caption-writer, orchestrator-chain"
verdict: PENDING
related: [001]
tags: [compile, claude-agent-sdk, latency]
---

# Spike 002: compile-baseline

## What This Validates
Given a 3-clip throwaway cluster (built from `backend/seed/demo/realworld-{1,2,3}.mp4`), when the compile pipeline runs N times, then we see per-stage ms broken into:
- `keyframe_ms` — `extract_cluster_keyframes` (ffmpeg, parallel per clip)
- `caption_ms` — `_run_caption_writer_with_vision` (single sonnet+vision call)
- `orchestrator_ms` — `_run_orchestrator_chain` (angle-selector → editor → publisher; one SDK session)
- `total_ms` — sum

This is intentionally coarser than per-subagent timing for the orchestrator. Reason: the production orchestrator runs all 3 subagents inside a single sonnet conversation, so splitting it into 3 separate `query()` calls would measure a *different* system. If `orchestrator_ms` dominates, a follow-up spike can break it apart by parsing SDK message streams.

## How to Run
From repo root, with `ANTHROPIC_API_KEY` set in env (read by claude-agent-sdk via the bundled CLI):
```bash
# Real run (costs Anthropic API credit — sonnet x2 + haiku x1 + sonnet+vision per run)
./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 3

# Smaller cluster (1 clip — useful sanity)
./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 2 --clips 1

# Keep fixture for inspection
./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 1 --keep
```

Each run inserts one throwaway cluster + N clips with `bench`-prefixed IDs into the live `newz.db`, runs compile, then deletes the cluster + clips + segment. Embeddings are NOT inserted because compile.py never reads them.

## What to Expect
- Per-run line with the 4 timing slices.
- Markdown summary table with min/p50/p95/max.
- "Share of total (median)" — instantly tells us which sub-stage dominates.
- The 60s `compile_segment` cap (`asyncio.wait_for(..., timeout=60.0)`) is bypassed in this spike — we want raw timings even if they exceed the cap.

## Investigation Trail
- Built fixture-driven harness that calls the same module-level functions used by `compile_segment` (`extract_cluster_keyframes`, `_run_caption_writer_with_vision`, `_run_orchestrator_chain`) with timers between them. No production code modified.
- Decided against splitting the orchestrator into 3 separate query calls — that would diverge from production's single-session SDK overhead. Coarse first, finer later if warranted.

## Results
PENDING — run with a real `ANTHROPIC_API_KEY` and paste output here.
