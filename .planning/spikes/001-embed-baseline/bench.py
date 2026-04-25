"""Spike 001 — embed-baseline.

Run: python -m planning.spikes.001-embed-baseline.bench  (won't work — dashes)
Or:  cd backend && python ../.planning/spikes/001-embed-baseline/bench.py [N] [clip_path]

Times Marengo embed in three slices per call:
  upload_ms  — assets.create (HTTP POST + multipart upload)
  embed_ms   — embed.v_2.create (Marengo synchronous wait)
  total_ms   — wall-clock for _call_marengo()

Run order:
  1) cold call (first since process start) — captured once
  2) warm calls — N-1 follow-up calls
Output: markdown table with min / p50 / p95 / max for each slice + cold-vs-warm delta.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

# Make the backend package importable when this file is run directly.
HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))

# Import to trigger config load BEFORE we patch.
from backend import config  # noqa: E402

if config.USE_MOCK_EMBEDDINGS:
    print("WARN: USE_MOCK_EMBEDDINGS=true — Marengo will not be called.", file=sys.stderr)
if not config.TWELVELABS_API_KEY and not config.USE_MOCK_EMBEDDINGS:
    print("ERROR: TWELVELABS_API_KEY missing. Set it or USE_MOCK_EMBEDDINGS=true.", file=sys.stderr)
    sys.exit(2)


def call_once(clip_path: str) -> dict:
    """One real Marengo embed, sliced into upload + embed + total.

    Mirrors backend/pipeline/embed.py::_call_marengo but with per-step timers.
    Does NOT retry — we want raw single-call latency.
    """
    if config.USE_MOCK_EMBEDDINGS:
        # Sanity path so we can validate the harness without spending API credit.
        t0 = time.monotonic()
        time.sleep(0.001)
        t1 = time.monotonic()
        time.sleep(0.001)
        t2 = time.monotonic()
        return {
            "upload_ms": (t1 - t0) * 1000,
            "embed_ms": (t2 - t1) * 1000,
            "total_ms": (t2 - t0) * 1000,
            "ok": True,
            "err": None,
        }

    from twelvelabs import TwelveLabs
    from twelvelabs.types import MediaSource, VideoInputRequest

    client = TwelveLabs(api_key=config.TWELVELABS_API_KEY)
    t0 = time.monotonic()
    try:
        with open(clip_path, "rb") as f:
            asset = client.assets.create(method="direct", file=f)
        t1 = time.monotonic()

        client.embed.v_2.create(
            input_type="video",
            model_name="marengo3.0",
            video=VideoInputRequest(
                media_source=MediaSource(asset_id=asset.id),
                embedding_option=["visual", "audio", "transcription"],
                embedding_scope=["asset"],
                embedding_type=["fused_embedding"],
            ),
        )
        t2 = time.monotonic()
        return {
            "upload_ms": (t1 - t0) * 1000,
            "embed_ms": (t2 - t1) * 1000,
            "total_ms": (t2 - t0) * 1000,
            "ok": True,
            "err": None,
        }
    except Exception as e:
        t2 = time.monotonic()
        return {
            "upload_ms": None,
            "embed_ms": None,
            "total_ms": (t2 - t0) * 1000,
            "ok": False,
            "err": f"{type(e).__name__}: {e}",
        }


def fmt(v: float | None) -> str:
    return f"{v:>8.0f}" if v is not None else "    n/a"


def stats(name: str, vals: list[float]) -> str:
    if not vals:
        return f"| {name:<10} | {'n/a':>8} | {'n/a':>8} | {'n/a':>8} | {'n/a':>8} |"
    s = sorted(vals)
    p50 = s[len(s) // 2]
    p95 = s[max(0, int(len(s) * 0.95) - 1)]
    return (
        f"| {name:<10} | {fmt(min(vals))} | {fmt(p50)} | {fmt(p95)} | {fmt(max(vals))} |"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=10, help="total runs (incl cold). default 10")
    ap.add_argument("--clip", type=str, default=str(Path(REPO) / "backend/seed/demo/realworld-1.mp4"))
    args = ap.parse_args()

    if not Path(args.clip).exists():
        print(f"ERROR: clip not found: {args.clip}", file=sys.stderr)
        sys.exit(2)

    n = max(2, args.runs)
    size_mb = Path(args.clip).stat().st_size / 1e6
    print(f"# Spike 001 — embed-baseline")
    print(f"clip:         {args.clip}  ({size_mb:.2f} MB)")
    print(f"runs:         {n} (1 cold + {n-1} warm)")
    print(f"mock mode:    {config.USE_MOCK_EMBEDDINGS}")
    print()

    results: list[dict] = []
    for i in range(n):
        label = "cold" if i == 0 else f"warm#{i}"
        t = time.monotonic()
        r = call_once(args.clip)
        wall = (time.monotonic() - t) * 1000
        r["label"] = label
        r["wall_ms"] = wall
        results.append(r)
        if r["ok"]:
            print(
                f"  [{label:>7}] upload={fmt(r['upload_ms'])}ms  "
                f"embed={fmt(r['embed_ms'])}ms  total={fmt(r['total_ms'])}ms"
            )
        else:
            print(f"  [{label:>7}] FAILED: {r['err']}")

    ok = [r for r in results if r["ok"]]
    if not ok:
        print("\nNo successful runs. Aborting summary.", file=sys.stderr)
        sys.exit(1)

    cold = ok[0]
    warm = ok[1:]

    print()
    print("## Summary (ms)")
    print()
    print("| stage      |      min |      p50 |      p95 |      max |")
    print("|------------|---------:|---------:|---------:|---------:|")
    print(stats("upload",  [r["upload_ms"] for r in warm if r["upload_ms"] is not None]))
    print(stats("embed",   [r["embed_ms"]  for r in warm if r["embed_ms"]  is not None]))
    print(stats("total",   [r["total_ms"]  for r in warm if r["total_ms"]  is not None]))

    print()
    print("## Cold vs warm")
    print()
    if warm:
        wt = statistics.median([r["total_ms"] for r in warm if r["total_ms"]])
        delta = cold["total_ms"] - wt
        pct = (delta / wt * 100) if wt else 0.0
        print(f"cold total:   {cold['total_ms']:.0f} ms")
        print(f"warm p50:     {wt:.0f} ms")
        print(f"delta:        {delta:+.0f} ms ({pct:+.1f}%)")
    else:
        print("only one run — no warm comparison possible.")

    print()
    print("## Failures")
    failed = [r for r in results if not r["ok"]]
    if failed:
        for r in failed:
            print(f"- [{r['label']}] {r['err']}")
    else:
        print("none")


if __name__ == "__main__":
    main()
