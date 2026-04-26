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
    """Group children into runs.

    Children are bucketed by parent_id, sorted by start_offset_sec, then walked
    pairwise: a new run starts when adjacent cosine drops below threshold.
    Each run's vec is the renormalized mean of member vecs.
    """
    if not children:
        return []

    by_parent: dict[str, list[dict]] = {}
    for c in children:
        by_parent.setdefault(c["parent_id"], []).append(c)

    out: list[Run] = []
    for parent_id, group in by_parent.items():
        group.sort(key=lambda c: float(c.get("start_offset_sec") or 0.0))
        run_groups: list[list[dict]] = [[group[0]]]
        for prev, cur in zip(group, group[1:]):
            cos = float(np.dot(prev["vec"], cur["vec"]))
            if cos >= threshold:
                run_groups[-1].append(cur)
            else:
                run_groups.append([cur])

        parent_path = group[0].get("parent_path", "")
        for idx, members in enumerate(run_groups):
            stack = np.stack([m["vec"].astype(np.float32) for m in members], axis=0)
            mean = stack.mean(axis=0)
            mean /= np.linalg.norm(mean) + 1e-12
            out.append(Run(
                id=f"{parent_id}_run_{idx}",
                parent_id=parent_id,
                parent_path=parent_path,
                start_offset_sec=float(members[0]["start_offset_sec"]),
                end_offset_sec=float(members[-1]["end_offset_sec"]),
                member_child_ids=[m["id"] for m in members],
                vec=mean.astype(np.float32),
            ))
    return out
