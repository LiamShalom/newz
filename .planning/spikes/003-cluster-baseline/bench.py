"""Spike 003 — cluster-baseline.

Times cluster_worker against a synthetic in-memory cluster cache of varying size.
Goal: confirm the linear scan + DB writes stay <100ms even at 100 clusters
(or surface the ms scaling curve if not).

Mocks Marengo (synthetic random unit vectors). Uses real cluster.py logic.

Run:
  ./backend/.venv/bin/python .planning/spikes/003-cluster-baseline/bench.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))

import aiosqlite  # noqa: E402

from backend import db  # noqa: E402
from backend.pipeline import cluster as cluster_mod  # noqa: E402


def random_unit_vec(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


async def seed_clusters(n: int, rng: np.random.Generator) -> list[str]:
    """Insert n clusters into in-memory cache + DB. Returns list of cluster IDs."""
    cluster_mod.CLUSTERS.clear()
    ids: list[str] = []
    for _ in range(n):
        cid = "benchcl" + uuid.uuid4().hex[:14]
        cc = cluster_mod.ClusterCache(
            id=cid,
            centroid=random_unit_vec(rng),
            centroid_lat=34.1377 + rng.standard_normal() * 0.001,
            centroid_lng=-118.1253 + rng.standard_normal() * 0.001,
            median_ts=time.time() - rng.random() * 600,
            member_count=1,
            member_ids=[],
        )
        cluster_mod.CLUSTERS[cid] = cc
        await db.upsert_cluster(cc)
        ids.append(cid)
    return ids


async def insert_clip_for_bench(rng: np.random.Generator) -> str:
    """Insert a clip row so cluster_worker.fetch_clip succeeds. Returns clip_id."""
    clip_id = "benchclip" + uuid.uuid4().hex[:10]
    now = time.time()
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO clips
                 (id, path, lat, lng, ts, embedding_status, session_id, created_at)
               VALUES (?, '/tmp/bench.mp4', ?, ?, ?, 'done', 'bench', ?)""",
            (
                clip_id,
                34.1377 + rng.standard_normal() * 0.001,
                -118.1253 + rng.standard_normal() * 0.001,
                now,
                now,
            ),
        )
        await conn.commit()
    return clip_id


async def cleanup_bench_rows() -> None:
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute("DELETE FROM clips WHERE id LIKE 'benchclip%'")
        await conn.execute("DELETE FROM clusters WHERE id LIKE 'benchcl%'")
        await conn.commit()
    cluster_mod.CLUSTERS.clear()


async def bench_at_size(size: int, runs: int, rng: np.random.Generator) -> dict:
    """Seed `size` clusters, then run cluster_worker `runs` times.

    Each cluster_worker call inserts a fresh clip + new vector that won't match
    any existing cluster (random unit vec → cosine ~0). It will create a new
    cluster every time, so we measure: lock + linear scan over `size` clusters
    + 1 DB upsert + 1 DB UPDATE.
    """
    await seed_clusters(size, rng)

    # Pre-create clips so we don't measure clip insert in the loop
    clip_ids = []
    for _ in range(runs):
        clip_ids.append(await insert_clip_for_bench(rng))

    timings: list[float] = []
    try:
        for clip_id in clip_ids:
            vec = random_unit_vec(rng)
            t0 = time.monotonic()
            await cluster_mod.cluster_worker(clip_id, vec)
            timings.append((time.monotonic() - t0) * 1000)
    finally:
        await cleanup_bench_rows()

    return {
        "size": size,
        "runs": len(timings),
        "min": min(timings),
        "p50": sorted(timings)[len(timings) // 2],
        "p95": sorted(timings)[max(0, int(len(timings) * 0.95) - 1)],
        "max": max(timings),
        "raw": timings,
    }


def fmt(v: float) -> str:
    return f"{v:>9.2f}"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=str, default="1,10,100", help="cluster pool sizes (csv)")
    ap.add_argument("-n", "--runs", type=int, default=20, help="cluster_worker calls per size")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    sizes = [int(s) for s in args.sizes.split(",")]
    rng = np.random.default_rng(args.seed)

    print(f"# Spike 003 — cluster-baseline")
    print(f"sizes:   {sizes}  (active clusters during scoring)")
    print(f"runs:    {args.runs} cluster_worker calls per size")
    print()

    rows: list[dict] = []
    for size in sizes:
        r = await bench_at_size(size, args.runs, rng)
        rows.append(r)
        print(
            f"  size={size:>4}: min={fmt(r['min'])}ms  p50={fmt(r['p50'])}ms  "
            f"p95={fmt(r['p95'])}ms  max={fmt(r['max'])}ms"
        )

    print()
    print("## Summary (ms)")
    print()
    print("| clusters |       min |       p50 |       p95 |       max |")
    print("|---------:|----------:|----------:|----------:|----------:|")
    for r in rows:
        print(
            f"| {r['size']:>8} | {fmt(r['min'])} | {fmt(r['p50'])} | "
            f"{fmt(r['p95'])} | {fmt(r['max'])} |"
        )

    print()
    print("## Scaling")
    if len(rows) >= 2:
        first, last = rows[0], rows[-1]
        ratio_size = last["size"] / first["size"]
        ratio_p50 = last["p50"] / first["p50"] if first["p50"] > 0 else float("inf")
        print(f"  size  ×{ratio_size:.0f}")
        print(f"  p50   ×{ratio_p50:.2f}")
        if last["p50"] < 100:
            print(f"  ✓ p50 at largest pool ({last['p50']:.1f}ms) is well under 100ms — cluster stage is negligible.")
        else:
            print(f"  ✗ p50 at largest pool ({last['p50']:.1f}ms) exceeds 100ms — investigate.")


if __name__ == "__main__":
    asyncio.run(main())
