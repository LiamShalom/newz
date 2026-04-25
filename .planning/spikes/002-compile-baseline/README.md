---
spike: 002
name: compile-baseline
type: standard
validates: "Given a 3-clip cluster, when compile_segment runs N=3, then we see per-stage ms: keyframes, caption-writer, orchestrator-chain"
verdict: VALIDATED
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

## Results — VALIDATED ✓ (with critical findings)

Real run, 3 attempts, 3-clip clusters from `backend/seed/demo/realworld-{1,2,3}.mp4`:

```
| stage          |       min |       p50 |       p95 |       max |
|----------------|----------:|----------:|----------:|----------:|
| keyframes      |        61 |        61 |        61 |        61 |
| caption        |      7076 |      7076 |      7076 |      7076 |
| orchestrator   |    112575 |    112575 |    112575 |    112575 |
| total          |    119712 |    119712 |    119712 |    119712 |
```

(Only run 3/3 succeeded end-to-end; runs 1 and 2 failed at the publisher — see below.)

### Findings

1. **Orchestrator chain is the entire pipeline cost.**
   - keyframes: 61 ms (0.1%)
   - caption-writer: 7076 ms (5.9%)
   - orchestrator (angle-selector → editor → publisher): **112575 ms (94.0%)**
   - The 60s `asyncio.wait_for(_run_agents, timeout=60.0)` cap in `compile_segment` is **smaller than orchestrator p50** on this hardware/this prompt. In production this exact run would have hit the timeout and fallen back to `_save_fallback_segment`.

2. **Compile dwarfs embed by ~25–40×.** Spike 001 measured embed at 2.5s p50; compile is 120s. Time spent optimizing embed is a rounding error against compile.

3. **Publisher reliability is broken at the prod level.** 2 of 3 runs raised `compile finished but no segment row for cluster <id> — Publisher may have failed to call save_segment`. The orchestrator returned a non-error `ResultMessage`, but the haiku publisher subagent never actually invoked `mcp__newz_tools__save_segment`. This is a prod bug — when production hits this, `_run_orchestrator_chain` raises and `compile_segment` falls through to the fallback. Symptom would be: AI-written caption silently replaced with the generic "Multi-angle event captured by N contributors..." fallback.

4. **The pre-existing 60s cap is misleading.** It's not "headroom for the multi-agent pipeline" — it's the dominant constraint, and we're 2× over budget. Either the cap raises, or the orchestrator design changes.

### Pivot signals (read this, don't act yet)

- The user's original framing — "caption-writer ‖ angle-selector, drop editor, demote publisher" — is *exactly* the right shape of fix for what this data shows. The orchestrator chain is sequential 3-subagent sonnet+sonnet+haiku. Parallelizing or removing stages directly attacks the 112s.
- Compression / URL upload optimizations on embed (the spike-001 finding) save ~1.4s. Worth doing only if compile is already sub-30s. Right now it's table-scraps next to the 112s problem.
- Publisher's failure mode needs investigating before any timing fix lands — otherwise we'll just be making a still-broken pipeline faster.

### Caveats

- N=3 with 67% failure rate is not statistically robust. The 112s number is a single observation. Could be longer or shorter on retry. But the order of magnitude is unambiguous — even a 2× variance still puts us over the 60s cap.
- The harness deliberately bypasses the 60s cap to get raw numbers. In real `compile_segment`, this run would have raised TimeoutError around the 60s mark and the `orchestrator_ms` measurement would have been clipped.
