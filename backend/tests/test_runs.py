"""Tests for backend/pipeline/runs.py — run detection over child clips."""
import numpy as np
import pytest

from backend.pipeline.runs import find_runs, Run


def _unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-12
    return v


def test_find_runs_module_imports():
    """Sanity: the public surface exists."""
    assert callable(find_runs)
    assert Run is not None
