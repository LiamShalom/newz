"""
backend/pipeline/stitch.py — ffmpeg-python concat stage (Phase 4.5).

Public API:
    stitch_clips(clip_refs, output_path) -> str
        Async. Each clip_ref: {"path": str, "start_offset_sec": float, "end_offset_sec": float}.
        Produces a single .webm file at output_path.
        Falls back to first clip_ref["path"] on failure — never raises.
"""

import asyncio
import logging
import os
import tempfile

import ffmpeg

log = logging.getLogger(__name__)


def _sync_stitch(clip_refs: list[dict], output_path: str) -> str:
    """Build ffmpeg concat demuxer file list and run. Returns output_path on success."""
    list_entries = []
    for ref in clip_refs:
        path = ref["path"]
        start = ref.get("start_offset_sec", 0.0)
        end = ref.get("end_offset_sec")
        list_entries.append(f"file '{path}'")
        list_entries.append(f"inpoint {start}")
        if end is not None:
            list_entries.append(f"outpoint {end}")

    concat_content = "\n".join(list_entries) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="newz_stitch_"
    ) as tf:
        tf.write(concat_content)
        list_path = tf.name

    try:
        (
            ffmpeg
            .input(list_path, format="concat", safe=0)
            .output(output_path, vcodec="libvpx-vp9", acodec="libopus", **{"b:v": "1M"})
            .run(overwrite_output=True, quiet=True)
        )
        log.info("stitch ok output=%s", output_path)
        return output_path
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass


async def stitch_clips(clip_refs: list[dict], output_path: str) -> str:
    """Async wrapper around _sync_stitch. Falls back to first clip's path on any failure.

    clip_refs: [{"path": str, "start_offset_sec": float, "end_offset_sec": float | None}, ...]
    output_path: absolute path for the output .webm file.
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
