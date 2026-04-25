"""
backend/seed/world/download.py — fetch + trim multi-angle clips for the world FYP seed.

For each event in manifest.json: yt-dlp grabs ONE source video (top result of search_query
or explicit source_url), then ffmpeg slices it into N angle clips at the configured
start_sec / duration_sec offsets. All angles share the same source so visual cosine stays
high enough to clear cluster.py:VISUAL_FLOOR (0.80) and fuse into one cluster.

Outputs to cache/<slug>/angle-{1..N}.mp4. Idempotent — existing files are reused unless
--force is passed.

Usage:
    python -m backend.seed.world.download
    python -m backend.seed.world.download --manifest path/to/manifest.json --force
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_MANIFEST = HERE / "manifest.json"
CACHE_DIR = HERE / "cache"


def _which_or_die(name: str) -> str:
    p = shutil.which(name)
    if not p:
        print(f"ERROR: {name} not found on PATH. Install it (brew install {name}).", file=sys.stderr)
        sys.exit(2)
    return p


def _yt_dlp_fetch(target: str, out_path: Path, yt_dlp: str) -> bool:
    """Download a single video to out_path. Returns True on success.

    target: either an https:// URL or 'ytsearch1:<query>'.
    """
    cmd = [
        yt_dlp,
        "--no-playlist",
        "-f", "bv*[height<=720][ext=mp4]+ba/b[height<=720]/best[height<=720]/best",
        "--merge-output-format", "mp4",
        "-o", str(out_path),
        "--quiet", "--no-warnings",
        target,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  yt-dlp failed: {res.stderr.strip().splitlines()[-1] if res.stderr else 'unknown error'}",
              file=sys.stderr)
        return False
    return out_path.exists() and out_path.stat().st_size > 0


def _ffmpeg_slice(src: Path, dst: Path, start_sec: float, duration_sec: float, ffmpeg: str) -> bool:
    """Cut a clip from src into dst. iOS Safari friendly: H.264 baseline, yuv420p, +faststart, no audio."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-ss", str(start_sec),
        "-i", str(src),
        "-t", str(duration_sec),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ffmpeg failed: {res.stderr.strip().splitlines()[-1] if res.stderr else 'unknown error'}",
              file=sys.stderr)
        return False
    return dst.exists() and dst.stat().st_size > 0


def _process_event(event: dict, force: bool, yt_dlp: str, ffmpeg: str) -> tuple[int, int]:
    """Returns (success_count, total_count) for the event's angles."""
    slug = event["slug"]
    angles = event["angles"]
    out_dir = CACHE_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    expected_paths = [out_dir / f"angle-{i + 1}.mp4" for i in range(len(angles))]
    if not force and all(p.exists() and p.stat().st_size > 0 for p in expected_paths):
        print(f"[{slug}] cached — skipping (use --force to re-download)")
        return len(angles), len(angles)

    target = event.get("source_url") or f"ytsearch1:{event['search_query']}"
    print(f"[{slug}] fetching: {target}")

    with tempfile.TemporaryDirectory() as td:
        src_path = Path(td) / "source.mp4"
        if not _yt_dlp_fetch(target, src_path, yt_dlp):
            return 0, len(angles)

        ok = 0
        for i, angle in enumerate(angles):
            dst = expected_paths[i]
            if not force and dst.exists() and dst.stat().st_size > 0:
                ok += 1
                continue
            if _ffmpeg_slice(src_path, dst, angle["start_sec"], angle["duration_sec"], ffmpeg):
                size_mb = dst.stat().st_size / (1024 * 1024)
                print(f"  angle-{i + 1}.mp4 ({size_mb:.1f} MB) start={angle['start_sec']}s dur={angle['duration_sec']}s")
                ok += 1
        return ok, len(angles)


def main(manifest_path: Path, force: bool) -> int:
    yt_dlp = _which_or_die("yt-dlp")
    ffmpeg = _which_or_die("ffmpeg")

    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text())
    events = manifest["events"]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for event in events:
        ok, total = _process_event(event, force, yt_dlp, ffmpeg)
        summary.append((event["slug"], ok, total))

    print("\n=== summary ===")
    complete_events = 0
    for slug, ok, total in summary:
        status = "OK" if ok == total else f"PARTIAL ({ok}/{total})" if ok > 0 else "FAILED"
        print(f"  {slug:30s} {status}")
        if ok == total:
            complete_events += 1
    print(f"\n{complete_events}/{len(events)} events fully downloaded.")
    return 0 if complete_events > 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else None)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help=f"Path to manifest JSON (default: {DEFAULT_MANIFEST})")
    ap.add_argument("--force", action="store_true",
                    help="Re-download/re-trim even if cache files exist")
    args = ap.parse_args()
    sys.exit(main(args.manifest, args.force))
