"""Codec-aware branching in `_sync_trim` (quick task 260502-h26).

Pure-function tests for `_pick_trim_output_kwargs` plus mocked-probe tests for
`_probe_video_codec`. No real ffmpeg invocation here — keeps the suite fast and
free of sample-file dependencies. The hot path (`test_stitch_perf.py`) still
exercises real H.264 sources end-to-end.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.pipeline.stitch import (
    _pick_trim_output_kwargs,
    _probe_video_codec,
)


# -----------------------------------------------------------------------------
# _pick_trim_output_kwargs — pure function, no I/O
# -----------------------------------------------------------------------------

def test_h264_source_uses_stream_copy():
    """iPhone Safari MediaRecorder hot path stays on `-c copy`."""
    kw = _pick_trim_output_kwargs("h264")
    assert kw["vcodec"] == "copy"
    assert kw["acodec"] == "copy"
    assert kw["format"] == "mp4"
    assert kw["movflags"] == "+faststart"


def test_vp9_source_re_encodes_with_libx264():
    """Chromebook / desktop Chrome WebM source goes through libx264 + AAC."""
    kw = _pick_trim_output_kwargs("vp9")
    assert kw["vcodec"] == "libx264"
    assert kw["acodec"] == "aac"
    assert kw["pix_fmt"] == "yuv420p"
    assert kw["movflags"] == "+faststart"
    assert kw["preset"] == "ultrafast"


def test_vp8_source_re_encodes_with_libx264():
    """Older Chrome MediaRecorder default — same fallback as VP9."""
    kw = _pick_trim_output_kwargs("vp8")
    assert kw["vcodec"] == "libx264"
    assert kw["acodec"] == "aac"


def test_unknown_codec_falls_through_to_libx264():
    """Probe failure → empty codec name → safe re-encode default."""
    kw = _pick_trim_output_kwargs("")
    assert kw["vcodec"] == "libx264"
    assert kw["pix_fmt"] == "yuv420p"


def test_av1_source_falls_through_to_libx264():
    """Anything that isn't literally 'h264' takes the re-encode path."""
    kw = _pick_trim_output_kwargs("av1")
    assert kw["vcodec"] == "libx264"


def test_h264_kwargs_have_no_libx264_specific_options():
    """Stream-copy mustn't carry encoder-specific knobs (would error)."""
    kw = _pick_trim_output_kwargs("h264")
    assert "preset" not in kw
    assert "crf" not in kw
    assert "pix_fmt" not in kw


# -----------------------------------------------------------------------------
# _probe_video_codec — wraps ffmpeg.probe; mock the subprocess hop
# -----------------------------------------------------------------------------

def test_probe_returns_codec_name_for_h264():
    fake = {"streams": [{"codec_name": "h264", "codec_type": "video"}]}
    with patch("backend.pipeline.stitch.ffmpeg.probe", return_value=fake):
        assert _probe_video_codec("/tmp/example.mp4") == "h264"


def test_probe_returns_codec_name_for_vp9():
    fake = {"streams": [{"codec_name": "vp9", "codec_type": "video"}]}
    with patch("backend.pipeline.stitch.ffmpeg.probe", return_value=fake):
        assert _probe_video_codec("/tmp/example.webm") == "vp9"


def test_probe_returns_empty_when_ffmpeg_raises():
    """Corrupt file / 404 / network glitch on Blob URL — fail safe."""
    with patch("backend.pipeline.stitch.ffmpeg.probe", side_effect=RuntimeError("boom")):
        assert _probe_video_codec("/tmp/missing.mp4") == ""


def test_probe_returns_empty_when_no_streams():
    """File parsed but has no video streams — caller will re-encode safely."""
    with patch("backend.pipeline.stitch.ffmpeg.probe", return_value={"streams": []}):
        assert _probe_video_codec("/tmp/audio-only.m4a") == ""


def test_probe_returns_empty_when_streams_field_missing():
    """ffprobe returned a malformed dict — same fail-safe behavior."""
    with patch("backend.pipeline.stitch.ffmpeg.probe", return_value={}):
        assert _probe_video_codec("/tmp/weird.bin") == ""


def test_probe_returns_empty_when_codec_name_missing():
    """Stream present but no codec_name field — empty result, re-encode."""
    fake = {"streams": [{"codec_type": "video"}]}  # no codec_name key
    with patch("backend.pipeline.stitch.ffmpeg.probe", return_value=fake):
        assert _probe_video_codec("/tmp/odd.mp4") == ""


def test_probe_forwards_headers_for_remote_inputs():
    """Blob-hosted clips need auth headers on the probe call too."""
    captured: dict = {}

    def fake_probe(path: str, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {"streams": [{"codec_name": "h264"}]}

    with patch("backend.pipeline.stitch.ffmpeg.probe", side_effect=fake_probe):
        result = _probe_video_codec(
            "https://example.com/runs/abc.mp4",
            headers={"Authorization": "Bearer secret"},
        )

    assert result == "h264"
    # CRLF-terminated, matches the convention in _sync_trim's input_kwargs.
    assert "Authorization: Bearer secret\r\n" in captured["kwargs"]["headers"]
    assert captured["kwargs"]["select_streams"] == "v:0"


# -----------------------------------------------------------------------------
# Sanity: imports + symbol exports
# -----------------------------------------------------------------------------

def test_helpers_are_importable_module_level():
    """Test exists to catch accidental rename/removal of the public-ish helpers."""
    from backend.pipeline import stitch
    assert callable(stitch._pick_trim_output_kwargs)
    assert callable(stitch._probe_video_codec)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
