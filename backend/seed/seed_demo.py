"""
backend/seed/seed_demo.py — upload staged demo clips to a running backend.

Usage:
    python -m backend.seed.seed_demo
    python -m backend.seed.seed_demo --base-url http://localhost:8000

Reads backend/seed/demo/clip-*.mp4 (3-4 files committed to repo), uploads each
via POST /clips with hardcoded Caltech-area GPS coords + staggered timestamps so
they flow through the identical pipeline (embed -> cluster) judges' live clips
will use. Sequential uploads with 0.5s sleep between to let pipeline stages
start in order (avoids Pitfall 4 race; cluster_worker also has asyncio.Lock).
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

CALTECH_LAT = 34.1377   # Beckman Mall, approximate
CALTECH_LNG = -118.1253
CLIP_DIR = Path(__file__).parent / "demo"


async def upload_one(client: httpx.AsyncClient, base_url: str, path: Path,
                     lat: float, lng: float, ts: float) -> str:
    with open(path, "rb") as f:
        files = {"file": (path.name, f.read(), "video/mp4")}
        data = {"lat": str(lat), "lng": str(lng), "ts": str(ts)}
        r = await client.post(f"{base_url}/clips", files=files, data=data, timeout=30.0)
    r.raise_for_status()
    return r.json()["clip_id"]


async def main(base_url: str, jitter_lat_m: float = 30.0, jitter_lng_m: float = 30.0) -> None:
    if not CLIP_DIR.exists():
        print(f"ERROR: {CLIP_DIR} does not exist; nothing to upload.", file=sys.stderr)
        sys.exit(1)
    clips = sorted(CLIP_DIR.glob("clip-*.mp4"))
    if not (3 <= len(clips) <= 4):
        print(f"ERROR: expected 3-4 demo clips matching clip-*.mp4 in {CLIP_DIR}, got {len(clips)}.",
              file=sys.stderr)
        sys.exit(1)

    base_ts = time.time() - 60   # all within last minute => high time score
    deg_per_m = 1.0 / 111_000.0  # rough lat conversion (1 deg ~ 111 km)
    coords = [
        (CALTECH_LAT + (i - 1) * 0.5 * jitter_lat_m * deg_per_m,
         CALTECH_LNG + (i - 1) * 0.5 * jitter_lng_m * deg_per_m,
         base_ts + i * 5)
        for i, _ in enumerate(clips)
    ]

    async with httpx.AsyncClient() as client:
        ids: list[str] = []
        for path, (lat, lng, ts) in zip(clips, coords):
            cid = await upload_one(client, base_url, path, lat, lng, ts)
            print(f"uploaded {path.name} -> clip_id={cid} lat={lat:.5f} lng={lng:.5f}")
            ids.append(cid)
            await asyncio.sleep(0.5)
        print(f"done. {len(ids)} clips uploaded. fetch /debug/clusters to inspect.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000",
                    help="Base URL of the running backend (default: http://localhost:8000)")
    args = ap.parse_args()
    asyncio.run(main(args.base_url))
