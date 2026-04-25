import asyncio
import logging

from .. import db, events
from .embed import embed_worker
from .cluster import cluster_worker
from .compile import compile_segment

log = logging.getLogger(__name__)


async def _should_compile(cluster_id: str) -> bool:
    """CMP-01 + CMP-09: returns True and atomically sets compile_in_flight if eligible.
    Eligible: member_count >= 2 AND not already in-flight within 30s TTL.
    """
    cluster = await db.get_cluster(cluster_id)
    if cluster is None or cluster["member_count"] < 2:
        return False
    return await db.set_compile_in_flight(cluster_id, True, ttl_seconds=30.0)


async def run_pipeline(clip_id: str) -> None:
    """Background pipeline. Fire-and-forget from POST /clips.

    Phase 4.5: embed_worker returns [(child_id, vec), ...] (or [(clip_id, vec)] for short clips).
    Each child/parent is clustered independently so clustering operates at 3s granularity.
    Compile trigger fires for any cluster that reaches size >= 2 after this batch.
    """
    try:
        child_pairs = await embed_worker(clip_id)
        log.info(
            "pipeline embed done clip_id=%s children=%d",
            clip_id, len(child_pairs),
        )
        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "embedded",
        })

        compile_candidates: set[str] = set()
        for cid, vec in child_pairs:
            cluster_id = await cluster_worker(cid, vec)
            compile_candidates.add(cluster_id)
            log.info(
                "pipeline cluster done child_id=%s cluster_id=%s",
                cid, cluster_id,
            )

        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "clustered",
        })

        # Fire compile for any cluster that crossed the threshold — first win takes it
        for cluster_id in compile_candidates:
            if await _should_compile(cluster_id):
                asyncio.create_task(compile_segment(cluster_id))
                log.info("compile triggered cluster_id=%s", cluster_id)
                break  # only one compile per upload batch

    except Exception as exc:
        log.exception("pipeline failed clip_id=%s", clip_id)
        await events.broadcast({
            "type": "pipeline_error",
            "clip_id": clip_id,
            "error": str(exc),
        })
