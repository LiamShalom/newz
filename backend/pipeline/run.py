import asyncio
import logging

from .. import config, db, events
from ..observability.metrics import STAGE_DURATION
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

    Phase 8 (D-17): stage timing via STAGE_DURATION.labels(stage=...).time().
    Stage enum: ingest|embed|cluster|compile|stitch.
    `compile` and `stitch` wraps deferred to Plan 13 (those wraps live inside
    backend/pipeline/compile.py and backend/pipeline/stitch.py, which Phase 11
    moderation-gate work also touches — defer to minimize merge friction).
    """
    try:
        with STAGE_DURATION.labels(stage="embed").time():
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

        with STAGE_DURATION.labels(stage="cluster").time():
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
