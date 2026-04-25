# Spike Manifest

## Idea
Measure where wall-clock time is actually spent across the Newz pipeline (embed → cluster → compile) before stacking more optimizations. Goal: data-driven baseline so we know which stage to attack instead of guessing.

## Requirements
- Output is a stdout markdown table — numbers, not UI. Spikes are about facts, not feel.
- Each spike runs against the **real backend module** (no rewrites of the pipeline) — instrument via wrappers / monkey-patches, not by editing production code.
- Embed and compile spikes must be runnable in `USE_MOCK_EMBEDDINGS=1` mode for harness validation, then flipped to real APIs for the actual numbers.

## Spikes

| # | Name | Type | Validates | Verdict | Tags |
|---|------|------|-----------|---------|------|
| 001 | embed-baseline | standard | Marengo upload-ms vs embed-ms, cold-vs-warm, p50/p95 over N=10 | **VALIDATED** ✓ — embed p50 2.5s, cold-start solved, tail latency is the risk | embed, marengo, latency |
| 002 | compile-baseline | standard | Per-stage ms (keyframes, caption, orchestrator-chain) for 3-clip cluster, N=3 | **VALIDATED** ✓ — orchestrator 112s = 94% of total, 2× over the 60s cap; publisher reliability broken in 2/3 runs | compile, claude-agent-sdk, latency |
| 003 | cluster-baseline | standard | Cluster worker ms with 1/10/100 existing clusters — confirm negligible | **VALIDATED** ✓ — flat 1.7ms p50 from 1→100 clusters | cluster, numpy, latency |

## Headline finding

The 60-second compile budget is **already gone** — orchestrator chain alone measured at 112s on a real 3-clip cluster, with a 67% publisher-reliability failure on top. Embed at 2.5s and cluster at 1.7ms are rounding errors in comparison. **Compile is the only stage worth optimizing right now.**
