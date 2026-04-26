"""
backend/pipeline/frames.py — ffmpeg frame extraction for caption pipeline (Phase 4.5).

Public API:
    extract_frames(path, start, end, n=3) -> list[bytes]
        Async. Extracts n evenly-spaced JPEG frames from [start, end] window of video at path.
        Returns list of JPEG bytes. Returns [] on failure (non-fatal).
"""

import asyncio
import logging

import ffmpeg

log = logging.getLogger(__name__)


def _sync_extract_one_frame(path: str, seek_t: float) -> bytes:
    """Extract one JPEG frame at seek_t seconds. Returns raw JPEG bytes."""
    out, _ = (
        ffmpeg
        .input(path, ss=seek_t)
        .output(
            "pipe:",
            vframes=1,
            format="mjpeg",  # outputs raw JPEG bytes to pipe; image2 is file-pattern only
            vf="scale='min(1568,iw)':-2",  # stay under Anthropic's 1568px max-edge recommendation
        )
        .run(capture_stdout=True, quiet=True)
    )
    return out


async def extract_frames(
    path: str,
    start: float,
    end: float,
    n: int = 3,
) -> list[bytes]:
    """Extract n evenly-spaced JPEG frames from the [start, end] window.

    Uses run_in_executor so ffmpeg sync I/O never blocks the event loop.
    Returns [] on any ffmpeg failure (caller treats as no visual context).
    """
    if end <= start:
        log.warning("extract_frames: end=%.1f <= start=%.1f, skipping", end, start)
        return []

    duration = end - start
    if n == 1:
        positions = [start + duration / 2]
    else:
        step = duration / (n - 1)
        positions = [start + i * step for i in range(n)]
        positions = [min(max(p, start + 0.1), end - 0.1) for p in positions]

    loop = asyncio.get_event_loop()
    frames: list[bytes] = []
    for seek_t in positions:
        try:
            frame_bytes = await loop.run_in_executor(
                None, _sync_extract_one_frame, path, seek_t
            )
            if frame_bytes:
                frames.append(frame_bytes)
        except Exception as exc:
            log.warning("extract_frames failed seek_t=%.2f path=%s: %s", seek_t, path, exc)
    return frames
