---
spike: 001
name: embed-baseline
type: standard
validates: "Given a real clip, when embed_worker runs N=10 times, then we see p50/p95 broken into upload-ms vs marengo-ms vs cold-vs-warm"
verdict: PENDING
related: []
tags: [embed, marengo, latency]
---

# Spike 001: embed-baseline

## What This Validates
Given a real clip, when embed_worker runs N=10 times, then we see p50/p95 broken into upload-ms vs marengo-ms vs cold-vs-warm.

## How to Run
From repo root:
```bash
# Real Marengo run (costs API credit)
./backend/.venv/bin/python .planning/spikes/001-embed-baseline/bench.py -n 10

# Custom clip / count
./backend/.venv/bin/python .planning/spikes/001-embed-baseline/bench.py -n 5 --clip backend/seed/demo/clip-1.mp4

# Harness sanity (no API call)
USE_MOCK_EMBEDDINGS=true ./backend/.venv/bin/python .planning/spikes/001-embed-baseline/bench.py -n 3
```

Defaults: 10 runs, clip = `backend/seed/demo/realworld-1.mp4` (5.05 MB).

## What to Expect
- One cold call (first since process start) followed by N-1 warm calls.
- Per-run line showing `upload_ms` (assets.create) vs `embed_ms` (embed.v_2.create) vs `total_ms`.
- Markdown summary with min/p50/p95/max for warm calls only (cold reported separately as cold-vs-warm delta).
- `pitfalls.md` predicts Marengo embed at 5–30s. If we're seeing >30s warm, that's a Marengo regression worth flagging. If `upload_ms` dominates, the bottleneck is network / file size, not the model.

## Investigation Trail
- Built harness that wraps the same `assets.create` + `embed.v_2.create` calls as `backend/pipeline/embed.py::_call_marengo`, but with timer slices between the two steps. No retry layer (we want raw single-call latency, not p99 across retries).
- Smoke-tested in `USE_MOCK_EMBEDDINGS=true` mode → harness produces clean output. Real-API run pending.

## Results
PENDING — run `bench.py` with a real `TWELVELABS_API_KEY` and paste output here.
