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

from .. import config

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


async def stitch_clips(
    clip_refs: list[dict], output_path: str, *, run_id: str | None = None,
) -> str:
    """Async wrapper around _sync_stitch. Falls back to first clip's path on any failure.

    clip_refs: [{"path": str, "start_offset_sec": float, "end_offset_sec": float | None}, ...]
    output_path: absolute path for the output .mp4 file.
    run_id: when provided AND blob mode active, upload to runs/{run_id}.mp4 (public)
            and return the absolute Blob URL.
    Returns: output_path on success, first clip's path on failure.
    """
    if not clip_refs:
        log.warning("stitch_clips called with empty clip_refs")
        return ""

    fallback_path = clip_refs[0]["path"]

    try:
        loop = asyncio.get_event_loop()
        local_out = await loop.run_in_executor(None, _sync_stitch, clip_refs, output_path)
    except Exception as exc:
        log.warning("stitch FAILED — falling back to first clip path: %s", exc)
        return fallback_path

    if run_id is None or config.STORAGE_BACKEND != "blob" or config.OFFLINE_DEMO:
        return local_out
    try:
        with open(local_out, "rb") as f:
            body = f.read()
        from ..storage import blob_client
        obj = await blob_client.upload(
            pathname=f"runs/{run_id}.mp4",
            body=body,
            content_type="video/mp4",
            access="public",
        )
        log.info("stitch+upload ok run_id=%s pathname=runs/%s.mp4", run_id, run_id)
        return obj["url"]
    except Exception as exc:
        log.warning("runs/ upload FAILED for run_id=%s — returning local path: %s", run_id, exc)
        return local_out


def _sync_trim(ref: dict, output_path: str) -> str:
    """Fast `-c copy` trim of a single window from one parent file.

    Per-run case (Phase 4.6): runs are always contiguous slices of ONE parent,
    so there's nothing to concatenate across files. A stream-copy trim avoids
    libx264 re-encode entirely (~50-100ms vs. 1-3s for the normalize pipeline).
    iOS Safari plays mp4-from-mp4 trims fine when the source is already H.264
    (MediaRecorder output from iPhone Safari) — `+faststart` ensures the moov
    atom is at the front so playback can start before the file is fully fetched.

    Output is .mp4 regardless of input extension; if input is webm/VP9 the trim
    will produce an mp4 container around VP9 which iOS won't play. That's an
    acceptable trade for the demo target (iPhone Safari producing H.264 .mp4).
    """
    if not ref:
        return ""

    start = float(ref.get("start_offset_sec", 0.0))
    end = ref.get("end_offset_sec")

    tmp_path = f"{output_path}.part-{int(time.time() * 1000)}-{os.getpid()}"
    input_kwargs: dict = {"ss": start}
    if end is not None:
        input_kwargs["to"] = end
    # Phase 10 (amendment 4): forward auth headers to ffmpeg's -headers flag.
    # CRLF terminator is mandatory per ffmpeg HTTP protocol docs (Pitfall 2).
    headers_dict = ref.get("headers")
    if headers_dict:
        input_kwargs["headers"] = "".join(f"{k}: {v}\r\n" for k, v in headers_dict.items())

    try:
        out = (
            ffmpeg
            .input(ref["path"], **input_kwargs)
            .output(
                tmp_path,
                format="mp4",
                vcodec="copy",
                acodec="copy",
                movflags="+faststart",
                avoid_negative_ts="make_zero",
            )
            .global_args("-loglevel", "error")
            .run_async(pipe_stderr=True)
        )
        _, stderr = out.communicate()
        if out.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace")[:500])
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    log.info("trim ok output=%s", output_path)
    return output_path


async def trim_window(ref: dict, output_path: str, *, run_id: str | None = None) -> str:
    """Async wrapper around _sync_trim. Falls back to ref['path'] on any failure.

    Phase 10 (D-10): when run_id is provided AND blob mode is active, the
    finished local .mp4 is uploaded to runs/{run_id}.mp4 (public) and the
    absolute Blob URL is returned. Upload failure falls back to the local
    path — frontend can still play it via /media in mixed mode.
    """
    if not ref:
        return ""
    fallback_path = ref["path"]
    try:
        loop = asyncio.get_event_loop()
        local_out = await loop.run_in_executor(None, _sync_trim, ref, output_path)
    except Exception as exc:
        log.warning("trim FAILED — falling back to source path: %s", exc)
        return fallback_path

    if run_id is None or config.STORAGE_BACKEND != "blob" or config.OFFLINE_DEMO:
        return local_out
    try:
        with open(local_out, "rb") as f:
            body = f.read()
        from ..storage import blob_client
        obj = await blob_client.upload(
            pathname=f"runs/{run_id}.mp4",
            body=body,
            content_type="video/mp4",
            access="public",
        )
        log.info("trim+upload ok run_id=%s pathname=runs/%s.mp4", run_id, run_id)
        return obj["url"]
    except Exception as exc:
        log.warning("runs/ upload FAILED for run_id=%s — returning local path: %s", run_id, exc)
        return local_out
