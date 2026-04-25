"""Spike 002 — compile-baseline.

Times each compile sub-stage independently:
  keyframe_ms     — extract_cluster_keyframes (ffmpeg, parallel per clip)
  caption_ms      — _run_caption_writer_with_vision (sonnet + image content)
  orchestrator_ms — _run_orchestrator_chain (angle-selector → editor → publisher, single SDK session)
  total_ms        — sum

Sets up a throwaway cluster (3 clips from backend/seed/demo/) per run, runs the
sub-stages, cleans up. Does NOT call embed (embeddings are not used by compile).
N runs gives p50/p95.

Run: ./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 3
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))

import aiosqlite  # noqa: E402

from backend import config, db  # noqa: E402
from backend.pipeline.compile import (  # noqa: E402
    _run_caption_writer_with_vision,
    _run_orchestrator_chain,
)
from backend.pipeline.keyframes import extract_cluster_keyframes  # noqa: E402


SEED_CLIPS = [
    REPO / "backend/seed/demo/realworld-1.mp4",
    REPO / "backend/seed/demo/realworld-2.mp4",
    REPO / "backend/seed/demo/realworld-3.mp4",
]


async def setup_fixture(n_clips: int) -> str:
    """Insert one cluster + n clips referencing seed clips. Returns cluster_id.

    No embeddings inserted — compile.py never reads them.
    """
    cluster_id = "bench" + uuid.uuid4().hex[:12]
    now = time.time()

    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO clusters
                 (id, centroid, centroid_lat, centroid_lng, median_ts,
                  member_count, created_at, updated_at)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?)""",
            (cluster_id, 34.1377, -118.1253, now, n_clips, now, now),
        )
        for i in range(n_clips):
            clip_id = "benchclip" + uuid.uuid4().hex[:10]
            src = SEED_CLIPS[i % len(SEED_CLIPS)]
            await conn.execute(
                """INSERT INTO clips
                     (id, path, lat, lng, ts, duration_sec, embedding_status,
                      cluster_id, session_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'done', ?, 'bench', ?)""",
                (
                    clip_id,
                    str(src),
                    34.1377 + i * 0.0001,
                    -118.1253 + i * 0.0001,
                    now - (n_clips - i) * 5,
                    4.0,
                    cluster_id,
                    now,
                ),
            )
        await conn.commit()
    return cluster_id


async def cleanup_fixture(cluster_id: str) -> None:
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute("DELETE FROM segments WHERE cluster_id = ?", (cluster_id,))
        await conn.execute("DELETE FROM clips WHERE cluster_id = ?", (cluster_id,))
        await conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
        await conn.commit()


async def bench_one(cluster_id: str) -> dict:
    """One end-to-end compile, sliced. Returns ms per stage."""
    out: dict = {"ok": False, "err": None}
    try:
        t0 = time.monotonic()
        frames = await extract_cluster_keyframes(cluster_id)
        t1 = time.monotonic()
        if not frames:
            raise RuntimeError("no keyframes extracted")

        caption_data = await _run_caption_writer_with_vision(cluster_id)
        t2 = time.monotonic()

        seg_id = await _run_orchestrator_chain(cluster_id, caption_data)
        t3 = time.monotonic()

        out.update(
            keyframe_ms=(t1 - t0) * 1000,
            caption_ms=(t2 - t1) * 1000,
            orchestrator_ms=(t3 - t2) * 1000,
            total_ms=(t3 - t0) * 1000,
            n_frames=len(frames),
            segment_id=seg_id,
            ok=True,
        )
    except Exception as e:
        out["err"] = f"{type(e).__name__}: {e}"
    return out


def fmt(v: float | None) -> str:
    return f"{v:>9.0f}" if v is not None else "      n/a"


def stats(name: str, vals: list[float]) -> str:
    if not vals:
        return f"| {name:<14} | {'n/a':>9} | {'n/a':>9} | {'n/a':>9} | {'n/a':>9} |"
    s = sorted(vals)
    p50 = s[len(s) // 2]
    p95 = s[max(0, int(len(s) * 0.95) - 1)]
    return (
        f"| {name:<14} | {fmt(min(vals))} | {fmt(p50)} | {fmt(p95)} | {fmt(max(vals))} |"
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=3, help="compile runs (default 3)")
    ap.add_argument("--clips", type=int, default=3, help="clips per cluster (default 3)")
    ap.add_argument("--keep", action="store_true", help="don't delete fixtures after run")
    args = ap.parse_args()

    if not config.OFFLINE_DEMO and not Path(config.DATA_DIR).exists():
        print(f"ERROR: DATA_DIR missing: {config.DATA_DIR}", file=sys.stderr)
        sys.exit(2)

    print(f"# Spike 002 — compile-baseline")
    print(f"runs:         {args.runs}")
    print(f"clips/run:    {args.clips}")
    print(f"data dir:     {config.DATA_DIR}")
    print()

    runs: list[dict] = []
    for i in range(args.runs):
        cluster_id = await setup_fixture(args.clips)
        try:
            r = await bench_one(cluster_id)
            r["cluster_id"] = cluster_id
            runs.append(r)
            if r["ok"]:
                print(
                    f"  [run {i+1}/{args.runs}] keyframe={fmt(r['keyframe_ms'])}ms  "
                    f"caption={fmt(r['caption_ms'])}ms  "
                    f"orchestrator={fmt(r['orchestrator_ms'])}ms  "
                    f"total={fmt(r['total_ms'])}ms  frames={r['n_frames']}"
                )
            else:
                print(f"  [run {i+1}/{args.runs}] FAILED: {r['err']}")
        finally:
            if not args.keep:
                await cleanup_fixture(cluster_id)
            elif runs and runs[-1].get("ok"):
                print(f"     kept fixture cluster_id={cluster_id}")

    ok = [r for r in runs if r["ok"]]
    if not ok:
        print("\nNo successful runs — aborting summary.", file=sys.stderr)
        sys.exit(1)

    print()
    print("## Summary (ms)")
    print()
    print("| stage          |       min |       p50 |       p95 |       max |")
    print("|----------------|----------:|----------:|----------:|----------:|")
    print(stats("keyframes",    [r["keyframe_ms"]     for r in ok]))
    print(stats("caption",      [r["caption_ms"]      for r in ok]))
    print(stats("orchestrator", [r["orchestrator_ms"] for r in ok]))
    print(stats("total",        [r["total_ms"]        for r in ok]))
    print()
    print("## Share of total (median)")
    if ok:
        med_total = sorted(r["total_ms"] for r in ok)[len(ok) // 2]
        for label, key in [("keyframes", "keyframe_ms"),
                           ("caption", "caption_ms"),
                           ("orchestrator", "orchestrator_ms")]:
            vals = sorted(r[key] for r in ok)
            med = vals[len(vals) // 2]
            pct = (med / med_total * 100) if med_total else 0
            print(f"  {label:<14} {pct:>5.1f}%  ({med:.0f} ms)")

    print()
    failed = [r for r in runs if not r["ok"]]
    if failed:
        print("## Failures")
        for r in failed:
            print(f"- {r['err']}")


if __name__ == "__main__":
    asyncio.run(main())
