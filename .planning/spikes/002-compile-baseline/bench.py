"""Spike 002 — compile-baseline (rewired for the Phase 4.5 parallel orchestrator).

Times the NEW compile_segment shape — three coroutines inside asyncio.gather:
  Track A: _run_agents          (caption-writer + angle-selector → editor → publisher)
  Track B: stitch_clips         (ffmpeg concat to .webm)
  Track C: generate_caption     (frame-based Haiku/Sonnet visual caption)

Two modes per run, on independent fixtures, so we can quantify what the gather buys:
  parallel — replicates compile_segment's body with per-track timing wrappers and a
             configurable cap (default 300s; bypasses the prod 60s wait_for so we get
             raw numbers instead of always-TimeoutError).
  serial   — same three coroutines awaited sequentially. Apples-to-apples baseline.

Each mode reports:
  parallel_total_ms, serial_total_ms, track_a_ms, track_b_ms, track_c_ms.

Plus a "would TimeoutError in prod" flag: True if parallel_total_ms > 60s.

Run:
  ./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 3
  ./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 3 --mode parallel
  ./backend/.venv/bin/python .planning/spikes/002-compile-baseline/bench.py -n 1 --cap 60 --keep
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
import numpy as np  # noqa: E402

from backend import config, db  # noqa: E402
from backend.pipeline.caption_pipeline import generate_caption  # noqa: E402
from backend.pipeline.cluster import CLUSTERS, ClusterCache  # noqa: E402
from backend.pipeline.compile import (  # noqa: E402
    _get_children_with_vecs,
    _run_agents,
)
from backend.pipeline.stitch import stitch_clips  # noqa: E402


SEED_CLIPS = [
    REPO / "backend/seed/demo/realworld-1.mp4",
    REPO / "backend/seed/demo/realworld-2.mp4",
    REPO / "backend/seed/demo/realworld-3.mp4",
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _rand_unit_vec(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


async def setup_fixture(n_clips: int, rng: np.random.Generator) -> str:
    """Insert one cluster + n clips + n embeddings; populate CLUSTERS in-memory.

    The in-memory ClusterCache is required so compile_segment passes a non-None
    centroid into generate_caption — otherwise Track C short-circuits to sleep(0)
    and we'd be timing only two of three tracks.
    """
    cluster_id = "bench" + uuid.uuid4().hex[:12]
    now = time.time()
    vecs: list[np.ndarray] = []
    clip_ids: list[str] = []

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
            vec = _rand_unit_vec(rng)
            await conn.execute(
                "INSERT OR REPLACE INTO clip_embeddings "
                "(clip_id, vector, latency_ms, created_at) VALUES (?, ?, ?, ?)",
                (clip_id, vec.tobytes(), 0, now),
            )
            vecs.append(vec)
            clip_ids.append(clip_id)
        await conn.commit()

    centroid = np.mean(np.stack(vecs), axis=0).astype(np.float32)
    centroid /= np.linalg.norm(centroid) + 1e-12
    CLUSTERS[cluster_id] = ClusterCache(
        id=cluster_id,
        centroid=centroid,
        centroid_lat=34.1377,
        centroid_lng=-118.1253,
        median_ts=now,
        member_count=n_clips,
        member_ids=clip_ids,
    )
    return cluster_id


async def cleanup_fixture(cluster_id: str) -> None:
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute("DELETE FROM segments WHERE cluster_id = ?", (cluster_id,))
        await conn.execute(
            "DELETE FROM clip_embeddings WHERE clip_id IN "
            "(SELECT id FROM clips WHERE cluster_id = ?)",
            (cluster_id,),
        )
        await conn.execute("DELETE FROM clips WHERE cluster_id = ?", (cluster_id,))
        await conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
        await conn.commit()
    CLUSTERS.pop(cluster_id, None)


# ---------------------------------------------------------------------------
# Per-track timing wrapper + setup helpers (mirror compile_segment body)
# ---------------------------------------------------------------------------

async def _timed(name: str, coro, sink: dict) -> object:
    t0 = time.monotonic()
    try:
        return await coro
    finally:
        sink[name] = (time.monotonic() - t0) * 1000


async def _build_tracks(cluster_id: str) -> tuple[list[dict], np.ndarray | None, list[dict], str]:
    """Mirror compile_segment's pre-gather setup so parallel/serial run the same coroutines."""
    children = await _get_children_with_vecs(cluster_id)

    stitch_refs = []
    for child in children:
        if child.get("parent_path") and child.get("end_offset_sec") is not None:
            stitch_refs.append({
                "path": child["parent_path"],
                "start_offset_sec": child.get("start_offset_sec", 0.0),
                "end_offset_sec": child["end_offset_sec"],
            })
    if not stitch_refs:
        clips = await db.fetch_cluster_clips(cluster_id)
        stitch_refs = [
            {"path": c["path"], "start_offset_sec": 0.0, "end_offset_sec": None}
            for c in clips[:3]
        ]

    cache = CLUSTERS.get(cluster_id)
    centroid = cache.centroid if cache else None
    output_path = str(config.DATA_DIR / "clips" / f"{cluster_id}_compiled.webm")
    return stitch_refs, centroid, children, output_path


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

async def run_parallel(cluster_id: str, cap_sec: float) -> dict:
    """Mirror compile_segment's gather, but with per-track timers and a configurable cap.

    Production uses asyncio.wait_for(..., timeout=60.0). We bypass that by default so
    runs longer than 60s produce real numbers instead of TimeoutError. Use --cap 60
    to reproduce production behavior exactly.
    """
    out: dict = {"mode": "parallel", "ok": False}
    track_ms: dict[str, float] = {}
    try:
        stitch_refs, centroid, children, output_path = await _build_tracks(cluster_id)

        track_c = (
            generate_caption(cluster_id, centroid, children)
            if centroid is not None and children
            else asyncio.sleep(0)
        )

        t0 = time.monotonic()
        results = await asyncio.wait_for(
            asyncio.gather(
                _timed("track_a", _run_agents(cluster_id), track_ms),
                _timed("track_b", stitch_clips(stitch_refs, output_path), track_ms),
                _timed("track_c", track_c, track_ms),
                return_exceptions=True,
            ),
            timeout=cap_sec,
        )
        total_ms = (time.monotonic() - t0) * 1000

        agent_res, stitch_res, caption_res = results
        out.update(
            parallel_total_ms=total_ms,
            track_a_ms=track_ms.get("track_a"),
            track_b_ms=track_ms.get("track_b"),
            track_c_ms=track_ms.get("track_c"),
            track_a_err=_fmt_err(agent_res),
            track_b_err=_fmt_err(stitch_res),
            track_c_err=_fmt_err(caption_res),
            would_timeout_at_60s=total_ms > 60_000,
            ok=True,
        )
    except asyncio.TimeoutError:
        out["err"] = f"TimeoutError at cap={cap_sec}s"
        out.update(
            track_a_ms=track_ms.get("track_a"),
            track_b_ms=track_ms.get("track_b"),
            track_c_ms=track_ms.get("track_c"),
        )
    except Exception as e:
        out["err"] = f"{type(e).__name__}: {e}"
    return out


async def run_serial(cluster_id: str) -> dict:
    """Same three coroutines awaited sequentially. Apples-to-apples baseline.

    No cap — this is the reference for what wall-clock would look like without the
    parallelization overhaul.
    """
    out: dict = {"mode": "serial", "ok": False}
    try:
        stitch_refs, centroid, children, output_path = await _build_tracks(cluster_id)

        t0 = time.monotonic()
        ta0 = time.monotonic()
        agent_res = await _safe(_run_agents(cluster_id))
        ta = (time.monotonic() - ta0) * 1000

        tb0 = time.monotonic()
        stitch_res = await _safe(stitch_clips(stitch_refs, output_path))
        tb = (time.monotonic() - tb0) * 1000

        tc0 = time.monotonic()
        if centroid is not None and children:
            caption_res = await _safe(generate_caption(cluster_id, centroid, children))
        else:
            caption_res = None
        tc = (time.monotonic() - tc0) * 1000

        total_ms = (time.monotonic() - t0) * 1000
        out.update(
            serial_total_ms=total_ms,
            track_a_ms=ta,
            track_b_ms=tb,
            track_c_ms=tc,
            track_a_err=_fmt_err(agent_res),
            track_b_err=_fmt_err(stitch_res),
            track_c_err=_fmt_err(caption_res),
            ok=True,
        )
    except Exception as e:
        out["err"] = f"{type(e).__name__}: {e}"
    return out


async def _safe(coro):
    """Run coro and return either result or the exception (no raise) — mirrors
    asyncio.gather(return_exceptions=True) so serial and parallel handle errors
    the same way."""
    try:
        return await coro
    except Exception as e:
        return e


def _fmt_err(res) -> str | None:
    return f"{type(res).__name__}: {res}" if isinstance(res, BaseException) else None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def fmt(v: float | None) -> str:
    return f"{v:>9.0f}" if v is not None else "      n/a"


def stats(name: str, vals: list[float]) -> str:
    if not vals:
        return f"| {name:<22} | {'n/a':>9} | {'n/a':>9} | {'n/a':>9} | {'n/a':>9} |"
    s = sorted(vals)
    p50 = s[len(s) // 2]
    p95 = s[max(0, int(len(s) * 0.95) - 1)]
    return (
        f"| {name:<22} | {fmt(min(vals))} | {fmt(p50)} | {fmt(p95)} | {fmt(max(vals))} |"
    )


def _summarize(label: str, runs: list[dict], total_key: str) -> None:
    ok = [r for r in runs if r.get("ok")]
    if not ok:
        print(f"\n## {label}: no successful runs")
        return

    print()
    print(f"## {label} (ms, N={len(ok)})")
    print()
    print("| stage                  |       min |       p50 |       p95 |       max |")
    print("|------------------------|----------:|----------:|----------:|----------:|")
    print(stats("track_a (_run_agents)",   [r["track_a_ms"]  for r in ok if r.get("track_a_ms") is not None]))
    print(stats("track_b (stitch_clips)",  [r["track_b_ms"]  for r in ok if r.get("track_b_ms") is not None]))
    print(stats("track_c (gen_caption)",   [r["track_c_ms"]  for r in ok if r.get("track_c_ms") is not None]))
    print(stats(f"TOTAL ({label.lower()})", [r[total_key] for r in ok if r.get(total_key) is not None]))

    if total_key == "parallel_total_ms":
        n_timeout = sum(1 for r in ok if r.get("would_timeout_at_60s"))
        print(f"\n  would TimeoutError in prod (cap=60s): {n_timeout}/{len(ok)}")


def _compare(parallel: list[dict], serial: list[dict]) -> None:
    p_ok = [r for r in parallel if r.get("ok")]
    s_ok = [r for r in serial if r.get("ok")]
    if not p_ok or not s_ok:
        return
    p_med = sorted(r["parallel_total_ms"] for r in p_ok)[len(p_ok) // 2]
    s_med = sorted(r["serial_total_ms"]   for r in s_ok)[len(s_ok) // 2]
    saved = s_med - p_med
    speedup = (s_med / p_med) if p_med else float("nan")
    print()
    print("## Parallel vs serial (medians)")
    print(f"  serial_total_ms   = {s_med:>9.0f}")
    print(f"  parallel_total_ms = {p_med:>9.0f}")
    print(f"  saved             = {saved:>9.0f} ms  (~{saved/1000:.1f}s)")
    print(f"  speedup           = {speedup:>9.2f}x")
    print()
    print("  Interpretation: gather wall-clock ≈ max(track_a, track_b, track_c).")
    print("  Serial wall-clock ≈ track_a + track_b + track_c.")
    print("  Speedup is meaningful only if track_b + track_c is non-trivial vs track_a.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _one_run(mode: str, n_clips: int, cap_sec: float, rng, keep: bool) -> dict:
    cluster_id = await setup_fixture(n_clips, rng)
    try:
        if mode == "parallel":
            r = await run_parallel(cluster_id, cap_sec)
        else:
            r = await run_serial(cluster_id)
        r["cluster_id"] = cluster_id
        return r
    finally:
        if keep:
            print(f"     kept fixture cluster_id={cluster_id}")
        else:
            await cleanup_fixture(cluster_id)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=3, help="runs per mode (default 3)")
    ap.add_argument("--clips", type=int, default=3, help="clips per cluster (default 3)")
    ap.add_argument(
        "--mode", choices=["parallel", "serial", "both"], default="both",
        help="which mode(s) to run (default: both)",
    )
    ap.add_argument(
        "--cap", type=float, default=300.0,
        help="parallel-mode wait_for cap in seconds. Use 60 to reproduce prod (default 300)",
    )
    ap.add_argument("--keep", action="store_true", help="don't delete fixtures after run")
    ap.add_argument("--seed", type=int, default=42, help="rng seed for embedding vectors")
    args = ap.parse_args()

    if not Path(config.DATA_DIR).exists():
        print(f"ERROR: DATA_DIR missing: {config.DATA_DIR}", file=sys.stderr)
        sys.exit(2)
    (config.DATA_DIR / "clips").mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.seed)

    print(f"# Spike 002 — compile-baseline (rewired for compile_segment gather)")
    print(f"runs/mode:    {args.runs}")
    print(f"clips/run:    {args.clips}")
    print(f"mode:         {args.mode}")
    print(f"cap (s):      {args.cap}")
    print(f"data dir:     {config.DATA_DIR}")
    print()

    parallel_runs: list[dict] = []
    serial_runs: list[dict] = []

    modes = ["parallel", "serial"] if args.mode == "both" else [args.mode]

    for mode in modes:
        print(f"=== mode: {mode} ===")
        for i in range(args.runs):
            r = await _one_run(mode, args.clips, args.cap, rng, args.keep)
            (parallel_runs if mode == "parallel" else serial_runs).append(r)
            if not r.get("ok"):
                print(f"  [run {i+1}/{args.runs}] FAILED: {r.get('err')}")
                continue
            if mode == "parallel":
                print(
                    f"  [run {i+1}/{args.runs}] "
                    f"total={fmt(r['parallel_total_ms'])}ms  "
                    f"a={fmt(r['track_a_ms'])}  b={fmt(r['track_b_ms'])}  c={fmt(r['track_c_ms'])}  "
                    f"prod_timeout={'YES' if r['would_timeout_at_60s'] else 'no'}"
                )
            else:
                print(
                    f"  [run {i+1}/{args.runs}] "
                    f"total={fmt(r['serial_total_ms'])}ms  "
                    f"a={fmt(r['track_a_ms'])}  b={fmt(r['track_b_ms'])}  c={fmt(r['track_c_ms'])}"
                )
            for tk in ("track_a_err", "track_b_err", "track_c_err"):
                if r.get(tk):
                    print(f"      {tk}: {r[tk]}")
        print()

    if parallel_runs:
        _summarize("PARALLEL", parallel_runs, "parallel_total_ms")
    if serial_runs:
        _summarize("SERIAL",   serial_runs,   "serial_total_ms")
    if parallel_runs and serial_runs:
        _compare(parallel_runs, serial_runs)

    failed = [r for r in (parallel_runs + serial_runs) if not r.get("ok")]
    if failed:
        print()
        print("## Failures")
        for r in failed:
            print(f"  - {r.get('mode')}: {r.get('err')}")


if __name__ == "__main__":
    asyncio.run(main())
