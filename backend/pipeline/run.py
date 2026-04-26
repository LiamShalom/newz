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

        # Vote across this upload's children: the cluster that got the most of
        # them is the parent's "home". A clip spanning two events still fires
        # compile on the dominant cluster instead of whichever we iterated first.
        votes: dict[str, int] = {}
        for cid, vec in child_pairs:
            cluster_id = await cluster_worker(cid, vec)
            votes[cluster_id] = votes.get(cluster_id, 0) + 1
            log.info(
                "pipeline cluster done child_id=%s cluster_id=%s",
                cid, cluster_id,
            )

        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "clustered",
        })

        if votes:
            parent_cluster_id = max(votes, key=lambda k: votes[k])
            log.info(
                "pipeline parent home cluster_id=%s votes=%d/%d",
                parent_cluster_id, votes[parent_cluster_id], sum(votes.values()),
            )
            if await _should_compile(parent_cluster_id):
                asyncio.create_task(compile_segment(parent_cluster_id))
                log.info("compile triggered cluster_id=%s", parent_cluster_id)

    except Exception as exc:
        log.exception("pipeline failed clip_id=%s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": _scrub(str(exc))})
