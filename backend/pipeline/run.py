import asyncio
import logging
import os

from structlog.contextvars import bind_contextvars, unbind_contextvars

from .. import config, db, events
from ..observability.metrics import STAGE_DURATION
from .embed import embed_worker
from .moderate import moderate_clip
from .cluster import cluster_worker
from .compile import compile_segment

log = logging.getLogger(__name__)


def _scrub(msg: str) -> str:
    """Redact secrets from error strings broadcast over the public /events SSE.

    WR-02 — scrub ALL configured secrets, not just TWELVELABS_API_KEY. A stack
    trace string serialized to anonymous SSE subscribers may plausibly contain
    any of:
      - TWELVELABS_API_KEY (Marengo)
      - GEMINI_API_KEY (caption pipeline)
      - ADMIN_TOKEN (/admin/reset, /metrics)
      - SENTRY_DSN (also writeable target — DSN is a credential)
      - ANTHROPIC_API_KEY (Claude Agent SDK; not centralized in config — read env)
    """
    secrets = (
        config.TWELVELABS_API_KEY,
        config.GEMINI_API_KEY,
        config.ADMIN_TOKEN,
        config.SENTRY_DSN,
        os.environ.get("ANTHROPIC_API_KEY", "").strip(),
    )
    for s in secrets:
        if s and s in msg:
            msg = msg.replace(s, "***REDACTED***")
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


async def _should_recompile(cluster_id: str, new_clip_id: str) -> bool:
    """Phase 14 recompile gate: fire compile_segment when a NEW DISTINCT PARENT
    joins a cluster that ALREADY has a published segment.

    Negative cases (intentionally do nothing — short-circuit before CAS):
      1. Feature flag off (config.RECOMPILE_ON_NEW_PARENT=False) -> v1.0 behavior preserved.
      2. new_clip is a child of an existing parent (clip.parent_id is not None) -> no new
         angle, just slicing metadata; the existing compile already had access.
      3. cluster has no segment yet (get_segment_for_cluster returns None) -> first compile
         path; _should_compile owns this case.
      4. Defensive: distinct parent count < 2 (impossible if seg exists, but cheap to check).

    On match, acquires the same CAS lock as _should_compile but with the longer
    RECOMPILE_DEBOUNCE_S TTL so bursts of new parents within the window coalesce
    into exactly one recompile (R1 mitigation per 14-RESEARCH.md).

    Per Phase 11 contract (MOD-01, MOD-06): does NOT re-run moderation. Each clip
    in the cluster individually passed the gate at ingest; soft_flag re-derivation
    runs inside compile_segment (compile.py:629-648) so hate/violence aggregates
    update on the re-emitted segment row.
    """
    if not config.RECOMPILE_ON_NEW_PARENT:
        return False
    clip = await db.get_clip(new_clip_id)
    if clip is None or clip.get("parent_id") is not None:
        return False
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        return False
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    if parent_count < 2:
        return False
    return await db.set_compile_in_flight(
        cluster_id, True, ttl_seconds=config.RECOMPILE_DEBOUNCE_S,
    )


async def run_pipeline(clip_id: str) -> None:
    """Background pipeline. Fire-and-forget from POST /clips.

    Phase 4.6: embed_worker returns exactly one (parent_clip_id, parent_vec) pair.
    cluster_worker is called once per upload using the parent's asset-scope vector.
    Compile fires only when the cluster has >=2 distinct parent uploads (Pivot 2).

    Phase 8 (D-17): stage timing via STAGE_DURATION.labels(stage=...).time().
    Stage enum: ingest|moderate|embed|cluster|compile|stitch.
    `compile` and `stitch` wraps deferred to Plan 13 (those wraps live inside
    backend/pipeline/compile.py and backend/pipeline/stitch.py, which Phase 11
    moderation-gate work also touches — defer to minimize merge friction).

    Phase 11 (D-01, D-06 reconciled): the moderation gate runs first inside
    STAGE_DURATION.labels(stage="moderate"). On decision='blocked' or 'unknown'
    we short-circuit (cluster + compile do not run). On decision='passed' the
    embed_result returned by moderate_clip is reused; if it is None (OFFLINE_DEMO
    short-circuit path) we fall back to running embed_worker directly.

    WR-01: bind `clip_id` into structlog contextvars at entry so every log
    line emitted from this task (including bridged stdlib logs from
    embed_worker / cluster_worker / compile_segment) carries clip_id as a
    top-level structured JSON field, satisfying the PRIV-02 whitelist
    (request_id, session_hash, clip_id) and the contract documented in
    RequestIDAndContextvarsBind. Unbind in finally so the structlog
    contextvars don't leak across asyncio tasks.
    """
    bind_contextvars(clip_id=clip_id)
    try:
        # Phase 11 (D-01): moderation gate runs first. moderate_clip races
        # embed_worker + Gemini classifier in parallel internally; on
        # decision='passed' it returns the embed_result so we don't run
        # embed_worker twice. On 'blocked' / 'unknown' we short-circuit.
        with STAGE_DURATION.labels(stage="moderate").time():
            mod_result = await moderate_clip(clip_id)

        if mod_result.decision == "blocked":
            log.info(
                "pipeline blocked clip_id=%s reason=%s provider=%s",
                clip_id, mod_result.reason, mod_result.provider,
            )
            await events.broadcast({
                "type": "pipeline_blocked",
                "clip_id": clip_id,
                "reason": mod_result.reason,
            })
            return  # cleanup_blocked_clip already called inside moderate_clip on hard-block

        if mod_result.decision == "unknown":
            log.info(
                "pipeline unknown clip_id=%s reason=%s — clip hidden, queued for admin",
                clip_id, mod_result.reason,
            )
            await events.broadcast({
                "type": "pipeline_unknown",
                "clip_id": clip_id,
                "reason": mod_result.reason,
            })
            return  # clustering paused; admin /resume re-enters via _resume_pipeline

        # decision == "passed" — embed task completed inside moderate_clip; pull its result.
        # mod_result.embed_result is (parent_clip_id, parent_vec); under OFFLINE_DEMO it is None
        # because moderate_clip short-circuits before running embed_worker — fall back to
        # running embed_worker now to keep the rest of the pipeline working.
        if mod_result.embed_result is not None:
            parent_clip_id, parent_vec = mod_result.embed_result
        else:
            with STAGE_DURATION.labels(stage="embed").time():
                parent_clip_id, parent_vec = await embed_worker(clip_id)

        log.info(
            "pipeline embed done parent_dims=%d",
            len(parent_vec),
        )
        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "embedded",
        })

        with STAGE_DURATION.labels(stage="cluster").time():
            cluster_id = await cluster_worker(parent_clip_id, parent_vec)
        log.info(
            "pipeline cluster done cluster_id=%s",
            cluster_id,
        )

        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "clustered",
        })

        if await _should_compile(cluster_id):
            asyncio.create_task(compile_segment(cluster_id))
            log.info("compile triggered cluster_id=%s", cluster_id)
        elif await _should_recompile(cluster_id, clip_id):
            asyncio.create_task(compile_segment(cluster_id))
            log.info("recompile triggered cluster_id=%s parent_id=%s", cluster_id, clip_id)

    except Exception as exc:
        log.exception("pipeline failed")
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": _scrub(str(exc))})
    finally:
        unbind_contextvars("clip_id")


async def _resume_pipeline(clip_id: str) -> None:
    """Phase 12 admin endpoint entry — re-enter pipeline after admin clears an unknown clip.

    Per Phase 11 D-06 reconciled: when admin flips clips.is_hidden=False and writes a
    fresh moderation_decisions row with decision='passed', the admin endpoint calls
    this function to re-enter the pipeline at cluster_worker. The parent embedding is
    still persisted on the clips row from the prior gate run (decision='unknown' did
    not block embed_worker from completing inside moderate_clip — D-06).

    The function lives in Phase 11 (this file); the admin endpoint that calls it lives
    in Phase 12 (REPORT-07). Phase 11 itself does NOT expose any HTTP route — the
    admin auth boundary is owned by Phase 12 (T-11-22).
    """
    bind_contextvars(clip_id=clip_id)
    try:
        # Pull the persisted parent embedding. Phase 9 D-04 + DB-04 guarantee it survives
        # across decision='unknown' gate runs (embed_worker writes the embedding row
        # before the moderate gate decides to hide the clip).
        parent_vec = await db.get_embedding(clip_id)
        if parent_vec is None:
            log.warning(
                "_resume_pipeline: no persisted embedding for clip_id=%s; cannot resume",
                clip_id,
            )
            return

        with STAGE_DURATION.labels(stage="cluster").time():
            cluster_id = await cluster_worker(clip_id, parent_vec)
        log.info("resume cluster done cluster_id=%s", cluster_id)

        await events.broadcast({
            "type": "pipeline_progress",
            "clip_id": clip_id,
            "stage": "clustered",
        })

        if await _should_compile(cluster_id):
            asyncio.create_task(compile_segment(cluster_id))
            log.info("resume compile triggered cluster_id=%s", cluster_id)
        elif await _should_recompile(cluster_id, clip_id):
            asyncio.create_task(compile_segment(cluster_id))
            log.info("resume recompile triggered cluster_id=%s parent_id=%s", cluster_id, clip_id)
    except Exception as exc:
        log.exception("resume_pipeline failed")
        await events.broadcast({
            "type": "pipeline_error",
            "clip_id": clip_id,
            "error": _scrub(str(exc)),
        })
    finally:
        unbind_contextvars("clip_id")
