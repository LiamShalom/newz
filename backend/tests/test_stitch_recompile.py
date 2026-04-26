"""Regression: stitch_clips must not truncate output_path mid-encode.

Before fix: ffmpeg -y opens output_path with O_TRUNC immediately, so any
HTTP Range read in flight on /media/<file>.mp4 gets zero/garbage bytes.
After fix: ffmpeg writes to a sibling .part-* file; os.replace atomically
publishes the new file, and prior inode stays alive for open FDs.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.pipeline.stitch import _sync_stitch


def _samples() -> list[str]:
    root = Path(__file__).resolve().parent.parent / "seed" / "demo"
    return sorted(str(p) for p in root.glob("realworld-*.mp4") if ".lowres" not in p.name)


def test_stitch_writes_to_tmp_then_atomic_replace(tmp_path):
    samples = _samples()
    if len(samples) < 2:
        pytest.skip(f"need 2+ realworld samples, got {len(samples)}")

    output_path = str(tmp_path / "cluster_compiled.mp4")
    sentinel = b"OLD-COMPILE" * 1024
    Path(output_path).write_bytes(sentinel)
    sentinel_size = len(sentinel)

    captured: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        # At the moment ffmpeg hands off, the live target must still be intact.
        assert os.path.getsize(dst) == sentinel_size, (
            "regression: _sync_stitch truncated output_path before atomic publish"
        )
        captured.append((src, dst))
        real_replace(src, dst)

    clip_refs = [
        {"path": p, "start_offset_sec": 0.0, "end_offset_sec": 2.0}
        for p in samples[:2]
    ]

    with patch("backend.pipeline.stitch.os.replace", side_effect=spy_replace):
        result = _sync_stitch(clip_refs, output_path)

    assert result == output_path
    assert len(captured) == 1, f"expected exactly one os.replace, got {len(captured)}"
    src, dst = captured[0]
    assert dst == output_path
    assert src.startswith(output_path + ".part-"), f"tmp not sibling of target: {src}"
    # New file is a real mp4, not the sentinel
    assert os.path.getsize(output_path) > sentinel_size
    with open(output_path, "rb") as f:
        head = f.read(12)
    assert b"ftyp" in head, f"output_path is not a valid mp4 (head={head!r})"
