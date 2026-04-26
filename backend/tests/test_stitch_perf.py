"""Smoke perf test for stitch_clips — guards against regression to libvpx-vp9.

NOT a replacement for the spike 002 bench (which is the canonical p50 < 5s
measurement). This test asserts a generous wall-clock bound (< 10s for 3
short clips) so CI catches a >10x regression even on a slow runner. Skips
when sample clips are not present (fresh CI checkout).
"""
from __future__ import annotations

import asyncio
import glob
import os
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_sample_clips() -> list[str]:
    """Locate up to 3 sample mp4 clips. Search known locations for portability."""
    candidate_globs = [
        str(REPO_ROOT / "data" / "realworld-*.mp4"),
        str(REPO_ROOT / "backend" / "seed" / "demo" / "realworld-*.mp4"),
        str(REPO_ROOT / "data" / "*.mp4"),
        str(REPO_ROOT / "backend" / "seed" / "demo" / "*.mp4"),
    ]
    found: list[str] = []
    for pattern in candidate_globs:
        for path in sorted(glob.glob(pattern)):
            if path not in found:
                found.append(path)
            if len(found) >= 3:
                return found[:3]
    return found[:3]


def test_stitch_clips_under_10s(tmp_path):
    """3 short clip slices should stitch in < 10s wall-clock; output > 100KB."""
    samples = _find_sample_clips()
    if len(samples) < 3:
        pytest.skip(f"need 3+ sample mp4 clips, found {len(samples)}")

    from backend.pipeline.stitch import stitch_clips

    clip_refs = [
        {"path": samples[i], "start_offset_sec": 0.0, "end_offset_sec": 5.0}
        for i in range(3)
    ]
    output_path = str(tmp_path / "stitch_perf_test.mp4")

    try:
        t0 = time.monotonic()
        result = asyncio.run(stitch_clips(clip_refs, output_path))
        elapsed = time.monotonic() - t0

        assert elapsed < 10.0, f"stitch wall-clock {elapsed:.2f}s exceeds 10s smoke bound"
        assert result == output_path, f"expected {output_path}, got {result}"
        assert os.path.exists(output_path), f"output missing: {output_path}"
        size = os.path.getsize(output_path)
        assert size > 100_000, f"output too small: {size} bytes"
    finally:
        try:
            if os.path.exists(output_path):
                os.unlink(output_path)
        except OSError:
            pass
