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
    """CMP-01 + CMP-09: returns True and atomically sets compile_in_flight if eligible.
    Eligible: member_count >= 2 AND not already in-flight within 30s TTL.
    """
    cluster = await db.get_cluster(cluster_id)
    if cluster is None or cluster["member_count"] < 2:
        return False
    return await db.set_compile_in_flight(cluster_id, True, ttl_seconds=30.0)


async def run_pipeline(clip_id: str) -> None:
    """Background pipeline. Fire-and-forget from POST /clips.

    Phase 2: embed_worker — Marengo 512-d vector, stored in SQLite.
    Phase 3: cluster_worker — composite-score assignment.
    Phase 4: compile trigger — Claude Agent SDK segment (CMP-01/CMP-09).
    """
    try:
        vec = await embed_worker(clip_id)
        log.info("pipeline embed done clip_id=%s dims=%d", clip_id, len(vec))
        await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "embedded"})

        cluster_id = await cluster_worker(clip_id, vec)
        log.info("pipeline cluster done clip_id=%s cluster_id=%s", clip_id, cluster_id)
        await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "clustered"})

        # Phase 4: CMP-01 + CMP-09 compile trigger — fire-and-forget, never awaited here
        if await _should_compile(cluster_id):
            asyncio.create_task(compile_segment(cluster_id))
            log.info("compile triggered cluster_id=%s", cluster_id)
    except Exception as exc:
        log.exception("pipeline failed clip_id=%s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": _scrub(str(exc))})
