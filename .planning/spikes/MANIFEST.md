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
| 001 | embed-baseline | standard | Marengo upload-ms vs embed-ms, cold-vs-warm, p50/p95 over N=10 | PENDING | embed, marengo, latency |
| 002 | compile-baseline | standard | Per-stage ms (keyframes, caption, orchestrator-chain) for 3-clip cluster, N=3 | PENDING | compile, claude-agent-sdk, latency |
| 003 | cluster-baseline | standard | Cluster worker ms with 1/10/100 existing clusters — confirm negligible | **VALIDATED** ✓ | cluster, numpy, latency |
