"""Phase 10 (amendment 7 / D-15): re-seed demo corpus through POST /clips.

Usage:
    BACKEND_URL=http://localhost:8000 ADMIN_TOKEN=... \
        python -m backend.scripts.seed_demo_to_blob [--reset]

Pre-requisites:
    - Backend running with STORAGE_BACKEND=blob and BLOB_READ_WRITE_TOKEN set.
    - backend/seed/demo/*.mp4 fixtures present.

Idempotency: --reset flag wipes via POST /admin/reset before seeding. Without
--reset, re-running creates duplicate rows (clip_id is uuid; harmless for demo).

Security: ADMIN_TOKEN read from environment, NEVER from argparse (mirror
sqlite_to_postgres.py:16-17 — avoids shell-history capture).
"""
import argparse
import logging
import os
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
DEMO_DIR = Path(__file__).resolve().parent.parent / "seed" / "demo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="POST /admin/reset before seeding")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with httpx.Client(timeout=60.0) as client:
        if args.reset:
            r = client.post(
                f"{BACKEND_URL}/admin/reset",
                params={"mode": "all"},
                headers={"X-Admin-Token": ADMIN_TOKEN},
            )
            log.info("reset status=%s body=%s", r.status_code, r.text[:200])

        for mp4 in sorted(DEMO_DIR.glob("*.mp4")):
            t0 = time.monotonic()
            with mp4.open("rb") as fh:
                r = client.post(
                    f"{BACKEND_URL}/clips",
                    files={"file": (mp4.name, fh, "video/mp4")},
                    data={"lat": "34.14", "lng": "-118.13", "ts": str(time.time())},
                )
            ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "seed path=%s status=%s latency_ms=%d body=%s",
                mp4.name, r.status_code, ms, r.text[:120],
            )


if __name__ == "__main__":
    main()
