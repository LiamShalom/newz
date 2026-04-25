---
spike: 003
name: cluster-baseline
type: standard
validates: "Given 1 / 10 / 100 existing clusters, when cluster_worker runs, then we see ms scaling and confirm <100ms"
verdict: VALIDATED
related: []
tags: [cluster, numpy, latency]
---

# Spike 003: cluster-baseline

## What This Validates
Given 1 / 10 / 100 existing clusters seeded with random 512-d unit centroids, when `cluster_worker` runs N=10 times, then per-call ms is well under the 100ms sanity bar AND scales sub-linearly with cluster pool size (the linear scan dominates at large N, but at hackathon-scale pool sizes it's trivial).

## How to Run
From repo root:
```bash
./backend/.venv/bin/python .planning/spikes/003-cluster-baseline/bench.py
# Or with custom pool sizes:
./backend/.venv/bin/python .planning/spikes/003-cluster-baseline/bench.py --sizes 1,50,500 -n 20
```

The harness:
1. Seeds an in-memory `CLUSTERS` cache + DB rows with `size` random clusters.
2. Pre-creates N clip rows (so the timed loop only measures `cluster_worker`, not clip insert).
3. Calls `cluster_worker(clip_id, random_vec)` N times — each call hits the lock, scans the pool, fails the visual floor (random vecs ≈ orthogonal), and creates a new cluster (1 upsert + 1 UPDATE).
4. Cleans up all `bench`-prefixed rows.

## What to Expect
Per-call ms should stay under 10ms even at 100 clusters. If it grows linearly with size (×100 size → ×100 ms), the linear scan would matter — but at hackathon scale it doesn't.

## Investigation Trail
- Used real `cluster.cluster_worker` against the live `newz.db` (WAL mode). No code mocked except embeddings (synthetic random unit vectors).
- Random vecs vs visual floor: with `VISUAL_FLOOR=0.80`, two random 512-d unit vecs almost never clear the floor — every call results in CREATE-new-cluster, which is the heaviest path (1 upsert + 1 UPDATE). So these numbers are an upper bound for the create branch; join-existing would be cheaper.

## Results — VALIDATED ✓

```
| clusters |       min |       p50 |       p95 |       max |
|---------:|----------:|----------:|----------:|----------:|
|        1 |      1.63 |      1.83 |      1.88 |      1.88 |
|       10 |      1.55 |      1.71 |      1.75 |      1.88 |
|      100 |      1.59 |      1.71 |      2.00 |      2.04 |
```

- Size ×100 → p50 ×0.93. Effectively flat. The linear scan over 100 unit-vector dot products is dwarfed by the two SQLite commits (~1.5ms baseline).
- **Cluster stage is negligible relative to the 60s compile budget.** Spend zero optimization effort here.
- Implication for embed/compile spikes: any wall-clock pain in the pipeline is in network/LLM, not in our Python code path.
