"""backend/pipeline/runs.py — run detection over already-embedded children.

A "run" is a contiguous span of children within the SAME parent whose
adjacent pairwise cosine similarity meets RUN_THRESHOLD. Runs are transient
(computed on-demand) and identified by f"{parent_id}_run_{idx}".

Public API:
    find_runs(children, threshold) -> list[Run]
        Pure, deterministic. Same input -> same output -> same run IDs.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Run:
    id: str
    parent_id: str
    parent_path: str
    start_offset_sec: float
    end_offset_sec: float
    member_child_ids: list[str]
    vec: np.ndarray  # float32, unit-length, mean of member child vecs


def find_runs(children: list[dict], threshold: float) -> list[Run]:
    raise NotImplementedError
