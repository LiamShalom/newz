import logging

log = logging.getLogger(__name__)


async def run_pipeline(clip_id: str) -> None:
    """Phase 1 stub — fire-and-forget kickoff target. Real pipeline:

    Phase 2: await embed.generate(clip_id)
    Phase 3: cluster_id = await cluster.assign_or_create(...)
    Phase 4: if cluster.should_compile: await compile.run(...)
    """
    log.info("pipeline kicked off clip_id=%s (Phase 1: no-op)", clip_id)
