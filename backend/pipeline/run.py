import asyncio
import logging

from .. import config, db, events
from .embed import embed_worker
from .cluster import cluster_worker
from .compile import compile_segment

log = logging.getLogger(__name__)


def _scrub(msg: str) -> str:
    """Redact secrets from error strings broadcast over the public /events SSE."""
    key = config.TWELVELABS_API_KEY
    if key and key in msg:
        msg = msg.replace(key, "***REDACTED***")
    return msg


async def _should_compile(cluster_id: str) -> bool:
    """Pivot 2 gate (CMP-01 + CMP-09): compile only when cluster has >=2 distinct
    PARENT uploads. Solo-parent clusters NEVER compile, even with N children.

    The gate runs upstream of compile_segment so we never spend tokens / 60s
    wall-clock budget on a doomed compile. count_distinct_parents_in_cluster
    is the single source of truth — defensive against any stray child cluster_id.
    """
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    if parent_count < 2:
        return False
    return await db.set_compile_in_flight(cluster_id, True, ttl_seconds=30.0)


async def run_pipeline(clip_id: str) -> None:
    """Background pipeline. Fire-and-forget from POST /clips.

    Phase 4.6: embed_worker returns exactly one (parent_clip_id, parent_vec) pair.
    cluster_worker is called once per upload using the parent's asset-scope vector.
    Compile fires only when the cluster has >=2 distinct parent uploads (Pivot 2).
    """
    try:
        parent_clip_id, parent_vec = await embed_worker(clip_id)
        log.info(
            "pipeline embed done clip_id=%s parent_dims=%d",
            clip_id, len(parent_vec),
        )
        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "embedded",
        })

        cluster_id = await cluster_worker(parent_clip_id, parent_vec)
        log.info(
            "pipeline cluster done clip_id=%s cluster_id=%s",
            clip_id, cluster_id,
        )

        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "clustered",
        })

        if await _should_compile(cluster_id):
            asyncio.create_task(compile_segment(cluster_id))
            log.info("compile triggered cluster_id=%s parent=%s", cluster_id, clip_id)

    except Exception as exc:
        log.exception("pipeline failed clip_id=%s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": _scrub(str(exc))})
