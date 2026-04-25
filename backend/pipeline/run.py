import logging

from .. import events
from .embed import embed_worker

log = logging.getLogger(__name__)


async def run_pipeline(clip_id: str) -> None:
    """Background pipeline. Fire-and-forget from POST /clips.

    Phase 2: embed_worker — Marengo 512-d vector, stored in SQLite.
    Phase 3: cluster_worker — composite-score assignment (coming).
    Phase 4: compile_pipeline — Claude Agent SDK segment (coming).
    """
    try:
        vec = await embed_worker(clip_id)
        log.info("pipeline embed done clip_id=%s dims=%d", clip_id, len(vec))
        await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "embedded"})
        # Phase 3 wires in: cluster_id = await cluster_worker(clip_id, vec)
    except Exception as exc:
        log.exception("pipeline failed clip_id=%s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": str(exc)})
