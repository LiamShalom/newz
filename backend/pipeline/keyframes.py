"""
backend/pipeline/keyframes.py — extract midpoint keyframes from clips for vision input.

Used by the vision-enabled caption-writer (compile.py) to ground captions in what's
actually visible in the footage, not just metadata.

Failures are non-fatal: a corrupt clip drops out, the rest still flow through.
If every frame fails, extract_cluster_keyframes returns [] and the caller falls
back to metadata-only behavior.
"""
import asyncio
import logging
import os
import subprocess
import tempfile

from imageio_ffmpeg import get_ffmpeg_exe

from .. import db

log = logging.getLogger(__name__)

FFMPEG = get_ffmpeg_exe()
DEFAULT_DURATION_SEC = 4.0
MAX_LONG_EDGE_PX = 512
EXTRACT_TIMEOUT_SEC = 5.0


async def _fetch_cluster_clips_with_duration(cluster_id: str) -> list[dict]:
    """Fetch clips for a cluster including duration_sec — needed for midpoint seek.

    Mirrors db.fetch_cluster_clips but adds duration_sec without changing the
    public MCP surface used by subagents.
    """
    rows = await db.get_pool().fetch(
        """
        SELECT c.id,
               COALESCE(NULLIF(c.path, ''), p.path) AS path,
               c.duration_sec,
               c.start_offset_sec,
               c.end_offset_sec
        FROM clips c
        LEFT JOIN clips p ON c.parent_id = p.id
        WHERE c.cluster_id = $1 ORDER BY c.ts ASC
        """,
        cluster_id,
    )
    return [dict(r) for r in rows]


def _run_ffmpeg(clip_path: str, midpoint: float, out_path: str) -> None:
    subprocess.run(
        [
            FFMPEG,
            "-ss", f"{midpoint:.2f}",
            "-i", clip_path,
            "-frames:v", "1",
            "-vf", f"scale='min({MAX_LONG_EDGE_PX},iw)':-2",
            "-f", "image2",
            "-c:v", "png",
            "-y", out_path,
        ],
        check=True,
        capture_output=True,
        timeout=EXTRACT_TIMEOUT_SEC,
    )


async def _extract_one(clip_path: str, duration_sec: float | None) -> bytes | None:
    midpoint = max(0.0, (duration_sec or DEFAULT_DURATION_SEC) / 2)
    fd, out_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        await asyncio.to_thread(_run_ffmpeg, clip_path, midpoint, out_path)
        with open(out_path, "rb") as fh:
            return fh.read()
    except Exception as e:
        log.warning("keyframe extract failed clip=%s err=%s", clip_path, e)
        return None
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


async def extract_cluster_keyframes(cluster_id: str) -> list[tuple[str, bytes]]:
    """Return (clip_id, png_bytes) for each clip with a successfully extracted frame.

    Order matches clips ORDER BY ts ASC. Clips that fail extraction are dropped.
    """
    clips = await _fetch_cluster_clips_with_duration(cluster_id)
    if not clips:
        return []
    pngs = await asyncio.gather(
        *[_extract_one(c["path"], c.get("duration_sec")) for c in clips]
    )
    return [(clips[i]["id"], png) for i, png in enumerate(pngs) if png]
