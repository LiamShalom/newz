---
spike: 001
name: embed-baseline
type: standard
validates: "Given a real clip, when embed_worker runs N=10 times, then we see p50/p95 broken into upload-ms vs marengo-ms vs cold-vs-warm"
verdict: VALIDATED
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

## Results — VALIDATED ✓ (with surprises)

Real run, 10 calls against Marengo, 5.05 MB `realworld-1.mp4`:

```
| stage      |      min |      p50 |      p95 |      max |
|------------|---------:|---------:|---------:|---------:|
| upload     |     1273 |     1351 |     1359 |     1360 |
| embed      |     1088 |     1171 |     3298 |    11568 |
| total      |     2438 |     2499 |     4581 |    12926 |
```

cold total: 2560 ms · warm p50: 2499 ms · cold-vs-warm delta: **+61 ms (+2.5%)**

### Findings

1. **Cold start is NOT the dominant cost.** Cold = 2.56s, warm p50 = 2.50s — only 61ms apart. Pre-warm is working; the assumption that "60s demo budget gets eaten by one slow Marengo cold-start" doesn't hold against this data.

2. **Upload is ~54% of typical embed time.** 1.35s p50 upload vs 1.17s p50 model embed. A 5 MB clip uploads at ~38 Mbps effective — close to typical egress. Optimization levers if we want this faster:
   - Compress clip client-side before POST (most direct win — halve the bytes, halve the upload).
   - URL-based ingestion if Twelve Labs supports it (skip the upload entirely, hand them a CDN URL).

3. **Tail latency is the real risk.** Typical warm call: 2.5s. But warm#1 took **12.9s** (embed step alone was 11.6s) and warm#2 took 4.6s. This is *not* cold-start — it's intermittent Marengo backend variance. p95 = 4.6s, max = 12.9s. In a 60s pipeline budget shared with compile, one bad spin eats 22% of the budget.

4. **`pitfalls.md` was pessimistic.** It predicted 5–30s. Actual p50 is 1.2s (model only) / 2.5s (with upload). The pessimism was warranted as a planning bound but not as a tuning target.

### Implications for the build

- Stop optimizing for cold-start. It's already solved.
- If we want to shave embed wall-clock, compress the upload — that's where the time is.
- Build resilience to tail-latency outliers (>5s embed) into the demo flow, not the average case.
