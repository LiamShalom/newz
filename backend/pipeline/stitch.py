"""
backend/pipeline/stitch.py — ffmpeg-python concat stage (Phase 4.5).

Public API:
    stitch_clips(clip_refs, output_path) -> str
        Async. Each clip_ref: {"path": str, "start_offset_sec": float, "end_offset_sec": float}.
        Produces a single .mp4 (H.264) file at output_path.
        Falls back to first clip_ref["path"] on failure — never raises.

Encoder: libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -movflags +faststart.
Source clips have mismatched specs (resolution/fps/profile), so we normalize each
input via scale → pad → setsar=1 → fps=30 then concat with ffmpeg's concat filter.
H.264 baseline + yuv420p + faststart is the iOS-Safari-safe combo (CLAUDE.md
hard constraint demo target). Audio is dropped — out of scope.

See .planning/debug/stitch-clips-bottleneck.md for the validated 127x speedup
over the prior VP9 software encode path (66.5s p50 → 0.52s).
"""

import asyncio
import logging
import os
import time

import ffmpeg

log = logging.getLogger(__name__)


def _sync_stitch(clip_refs: list[dict], output_path: str) -> str:
    """Build normalize-and-concat filter graph; encode with H.264 ultrafast.

    Per-input chain: scale (preserving aspect, fitting in 720x1280) → pad to
    720x1280 (centered, black bars) → setsar=1 → fps=30. Then concat n=N v=1 a=0.
    Output: .mp4 (H.264 yuv420p, faststart). Returns output_path on success.

    Re-compile-safe: ffmpeg writes to a sibling .part-<ts> file, then we
    os.replace into output_path. POSIX rename is atomic and preserves any
    open file descriptors via the old inode, so a browser already streaming
    the previous compile keeps reading clean bytes instead of a truncated file.
    """
    if not clip_refs:
        return ""

    W, H, FPS = 720, 1280, 30

    inputs = []
    for ref in clip_refs:
        kwargs = {"ss": ref.get("start_offset_sec", 0.0)}
        if ref.get("end_offset_sec") is not None:
            kwargs["to"] = ref["end_offset_sec"]
        inputs.append(ffmpeg.input(ref["path"], **kwargs))

    norm = [
        inp.video
           .filter("scale", W, H, force_original_aspect_ratio="decrease")
           .filter("pad", W, H, "(ow-iw)/2", "(oh-ih)/2")
           .filter("setsar", 1)
           .filter("fps", FPS)
        for inp in inputs
    ]

    tmp_path = f"{output_path}.part-{int(time.time() * 1000)}-{os.getpid()}"
    try:
        (
            ffmpeg
            .concat(*norm, n=len(norm), v=1, a=0)
            .output(
                tmp_path,
                format="mp4",
                vcodec="libx264",
                preset="ultrafast",
                crf=28,
                pix_fmt="yuv420p",
                movflags="+faststart",
            )
            .run(overwrite_output=True, quiet=True)
        )
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    log.info("stitch ok output=%s", output_path)
    return output_path


async def stitch_clips(clip_refs: list[dict], output_path: str) -> str:
    """Async wrapper around _sync_stitch. Falls back to first clip's path on any failure.

    clip_refs: [{"path": str, "start_offset_sec": float, "end_offset_sec": float | None}, ...]
    output_path: absolute path for the output .mp4 file.
    Returns: output_path on success, first clip's path on failure.
    """
    if not clip_refs:
        log.warning("stitch_clips called with empty clip_refs")
        return ""

    fallback_path = clip_refs[0]["path"]

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _sync_stitch, clip_refs, output_path)
        return result
    except Exception as exc:
        log.warning("stitch FAILED — falling back to first clip path: %s", exc)
        return fallback_path
