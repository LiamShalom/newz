"""
backend/seed/world/seed_world.py — bulk-upload world FYP seed clips through the live pipeline.

Reads cache/<slug>/angle-{1..N}.mp4 produced by download.py, uploads each via POST /clips
(matching backend/seed/seed_demo.py's pattern: multipart, 0.5s spacing). Per-event GPS is
jittered ~20m and timestamps staggered 5s apart so clustering's GPS+time signals stay
high while visual cosine does the heavy lifting.

A background SSE listener correlates clip_id -> cluster_id -> segment_id from the
/events stream so the script can wait up to 90s per event for a published segment
before moving on.

Usage:
    python -m backend.seed.world.seed_world
    python -m backend.seed.world.seed_world --base-url http://localhost:8000 --wait 120
    python -m backend.seed.world.seed_world --wipe   # rm -rf data/clips + data/newz.db, then exit
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).parent
DEFAULT_MANIFEST = HERE / "manifest.json"
CACHE_DIR = HERE / "cache"
DEG_PER_M = 1.0 / 111_000.0
JITTER_M = 20.0
DELAY_BETWEEN_ANGLES = 0.5
DELAY_BETWEEN_EVENTS = 1.0


class PipelineState:
    """Tracks clip -> cluster -> segment transitions from SSE."""

    def __init__(self) -> None:
        self.clip_to_cluster: dict[str, str] = {}
        self.cluster_to_segment: dict[str, str] = {}
        self.errors: list[dict[str, Any]] = []


async def _sse_listener(base_url: str, state: PipelineState, stop: asyncio.Event) -> None:
    """Subscribe to /events and update state until stop is set. Reconnects on transient errors."""
    while not stop.is_set():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{base_url}/events") as r:
                    r.raise_for_status()
                    data_buf: list[str] = []
                    async for line in r.aiter_lines():
                        if stop.is_set():
                            return
                        if line == "":
                            if data_buf:
                                payload = "".join(data_buf)
                                try:
                                    msg = json.loads(payload)
                                except json.JSONDecodeError:
                                    msg = None
                                if isinstance(msg, dict):
                                    _handle_event(msg, state)
                                data_buf = []
                            continue
                        if line.startswith("data:"):
                            data_buf.append(line[5:].lstrip())
        except (httpx.HTTPError, asyncio.CancelledError):
            if stop.is_set():
                return
            await asyncio.sleep(1.0)


def _handle_event(msg: dict, state: PipelineState) -> None:
    t = msg.get("type")
    if t == "cluster_assigned":
        cid = msg.get("clip_id")
        cluster = msg.get("cluster_id")
        if cid and cluster:
            state.clip_to_cluster[cid] = cluster
    elif t == "segment_published":
        cluster = msg.get("cluster_id")
        seg = msg.get("segment_id")
        if cluster and seg:
            state.cluster_to_segment[cluster] = seg
    elif t == "pipeline_error":
        state.errors.append(msg)


async def _upload(client: httpx.AsyncClient, base_url: str, path: Path,
                  lat: float, lng: float, ts: float) -> str:
    with open(path, "rb") as f:
        files = {"file": (path.name, f.read(), "video/mp4")}
        data = {"lat": str(lat), "lng": str(lng), "ts": str(ts)}
        r = await client.post(f"{base_url}/clips", files=files, data=data, timeout=60.0)
    r.raise_for_status()
    return r.json()["clip_id"]


async def _wait_for_segment(state: PipelineState, clip_ids: list[str], deadline_s: float
                            ) -> tuple[str | None, str | None]:
    """Wait up to deadline_s for a segment whose cluster contains a majority of clip_ids."""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        clusters = [state.clip_to_cluster[c] for c in clip_ids if c in state.clip_to_cluster]
        if clusters:
            cluster_id, count = Counter(clusters).most_common(1)[0]
            if count >= 2 and cluster_id in state.cluster_to_segment:
                return cluster_id, state.cluster_to_segment[cluster_id]
        await asyncio.sleep(0.5)
    clusters = [state.clip_to_cluster[c] for c in clip_ids if c in state.clip_to_cluster]
    cluster_id = Counter(clusters).most_common(1)[0][0] if clusters else None
    return cluster_id, None


async def _seed_event(client: httpx.AsyncClient, base_url: str, event: dict,
                      state: PipelineState, wait_s: float) -> dict:
    slug = event["slug"]
    angles_dir = CACHE_DIR / slug
    angle_paths = sorted(angles_dir.glob("angle-*.mp4"))
    if len(angle_paths) < 2:
        print(f"[{slug}] SKIP — need >=2 angles, found {len(angle_paths)} in {angles_dir}")
        return {"slug": slug, "skipped": True, "reason": "insufficient angles"}

    base_ts = time.time() - max(0, event.get("minutes_ago", 0)) * 60
    clip_ids: list[str] = []
    for i, p in enumerate(angle_paths):
        lat = event["lat"] + (i - 1) * 0.5 * JITTER_M * DEG_PER_M
        lng = event["lng"] + (i - 1) * 0.5 * JITTER_M * DEG_PER_M
        ts = base_ts + i * 5
        try:
            cid = await _upload(client, base_url, p, lat, lng, ts)
        except httpx.HTTPError as e:
            print(f"[{slug}] upload failed for {p.name}: {e}")
            continue
        clip_ids.append(cid)
        print(f"[{slug}] uploaded {p.name} clip_id={cid} lat={lat:.5f} lng={lng:.5f} ts={ts:.0f}")
        await asyncio.sleep(DELAY_BETWEEN_ANGLES)

    if not clip_ids:
        return {"slug": slug, "skipped": True, "reason": "all uploads failed"}

    print(f"[{slug}] waiting up to {wait_s:.0f}s for compiled segment...")
    cluster_id, segment_id = await _wait_for_segment(state, clip_ids, wait_s)
    if segment_id:
        print(f"[{slug}] OK cluster={cluster_id} segment={segment_id}")
    elif cluster_id:
        print(f"[{slug}] TIMEOUT — clustered ({cluster_id}) but no segment yet (compile may still be running)")
    else:
        print(f"[{slug}] TIMEOUT — no cluster assignment seen on SSE")
    return {
        "slug": slug,
        "clip_ids": clip_ids,
        "cluster_id": cluster_id,
        "segment_id": segment_id,
    }


def _wipe() -> None:
    """Delete local data dir contents. Backend in-memory state requires a restart after this."""
    candidates = [Path("./data"), Path("backend/data")]
    found = False
    for d in candidates:
        if d.exists():
            for p in d.glob("clips/*"):
                p.unlink()
            for p in d.glob("newz.db*"):
                p.unlink()
            print(f"wiped: {d}")
            found = True
    if not found:
        print("no local data/ dir found to wipe.")
    print("RESTART the backend before re-seeding (in-memory cluster cache rebuilds on lifespan startup).")


async def main(base_url: str, manifest_path: Path, wait_s: float) -> int:
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text())
    events = manifest["events"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as health_client:
            r = await health_client.get(f"{base_url}/health")
            r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"ERROR: backend not reachable at {base_url} ({e})", file=sys.stderr)
        return 2

    state = PipelineState()
    stop = asyncio.Event()
    listener = asyncio.create_task(_sse_listener(base_url, state, stop))
    await asyncio.sleep(0.5)

    results: list[dict] = []
    try:
        async with httpx.AsyncClient() as client:
            for event in events:
                results.append(await _seed_event(client, base_url, event, state, wait_s))
                await asyncio.sleep(DELAY_BETWEEN_EVENTS)
    finally:
        stop.set()
        listener.cancel()
        try:
            await listener
        except (asyncio.CancelledError, Exception):
            pass

    print("\n=== summary ===")
    seeded = sum(1 for r in results if r.get("segment_id"))
    clustered = sum(1 for r in results if r.get("cluster_id") and not r.get("segment_id"))
    skipped = sum(1 for r in results if r.get("skipped"))
    for r in results:
        if r.get("skipped"):
            print(f"  {r['slug']:30s} SKIPPED ({r.get('reason')})")
        elif r.get("segment_id"):
            print(f"  {r['slug']:30s} OK segment={r['segment_id']}")
        elif r.get("cluster_id"):
            print(f"  {r['slug']:30s} CLUSTER ONLY cluster={r['cluster_id']} (compile pending)")
        else:
            print(f"  {r['slug']:30s} NO CLUSTER (clip(s) uploaded but never assigned)")
    print(f"\n{seeded}/{len(events)} events with published segments. "
          f"{clustered} clustered-but-pending, {skipped} skipped.")
    if state.errors:
        print(f"pipeline_error events seen: {len(state.errors)}")
        for e in state.errors[:5]:
            print(f"  {e}")
    return 0 if seeded > 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000",
                    help="Base URL of the running backend (default: http://localhost:8000)")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help=f"Path to manifest JSON (default: {DEFAULT_MANIFEST})")
    ap.add_argument("--wait", type=float, default=90.0,
                    help="Seconds to wait per event for segment_published (default: 90)")
    ap.add_argument("--wipe", action="store_true",
                    help="Delete local data/clips and data/newz.db, then exit (restart backend after)")
    args = ap.parse_args()
    if args.wipe:
        _wipe()
        sys.exit(0)
    sys.exit(asyncio.run(main(args.base_url, args.manifest, args.wait)))
