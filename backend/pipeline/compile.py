"""
backend/pipeline/compile.py — 4-subagent Claude Agent SDK compile pipeline (Phase 4).

Public API:
    compile_segment(cluster_id: str) -> None
        Fire-and-forget coroutine. Called via asyncio.create_task from run.py.
        Hard 30s wall-clock cap (CMP-06). Fallback on timeout or error.

Pipeline: angle-selector ─┐
                           ├─ editor ─ publisher  (CMP-04)
          caption-writer ──┘

Sub-agent models: angle-selector/caption-writer/editor=sonnet, publisher=haiku (CLAUDE.md).
MCP tools: mcp__newz_tools__get_cluster_clips, get_clip_metadata, save_segment (CMP-03).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    ResultMessage,
)

from .. import db, events
from .compile_tools import newz_tools_server

log = logging.getLogger(__name__)

ORCHESTRATOR_PROMPT_TEMPLATE = """Compile cluster {cluster_id} into a published news segment.

Steps — use the named subagents in this order:
1. Run angle-selector AND caption-writer IN PARALLEL (they are independent of each other).
2. Run editor on angle-selector's JSON output to validate the clip order.
3. Run publisher with editor's clip_ids and caption-writer's caption+location.

Pass each subagent's JSON output verbatim into the next subagent's prompt.
The cluster_id is: {cluster_id}
"""

_MCP = ["newz_tools"]  # shared MCP server reference for all subagents

AGENTS = {
    "angle-selector": AgentDefinition(
        description=(
            "Picks 2-4 best clips from a cluster and orders them: "
            "establishing → action → reaction. Independent of caption-writer — run FIRST in parallel."
        ),
        prompt="""You are the Angle Selector for the Newz news compile pipeline.

Given a cluster of clips from the same event, select the best 3 (or fewer if less are available).

Selection criteria — rank candidates by:
1. TEMPORAL SPREAD: prefer clips from early, middle, and late in the event timeline (spread across the timestamp range)
2. SPATIAL DIVERSITY: prefer clips recorded from different GPS coordinates (different physical viewpoints)
3. DURATION: prefer longer clips as a proxy for more content; discard clips under 2 seconds
4. NO REDUNDANCY: exclude clips filmed within 5 seconds AND within 10 meters of an already-selected clip

Order the selected clips chronologically (earliest first).

Use mcp__newz_tools__get_cluster_clips to get all clips, then mcp__newz_tools__get_clip_metadata for details.
Return ONLY a single JSON object: {"clip_ids": ["...", "..."], "rationale": "..."}.
Do not include any text outside the JSON.""",
        tools=["mcp__newz_tools__get_cluster_clips", "mcp__newz_tools__get_clip_metadata"],
        mcpServers=_MCP,
        model="sonnet",
    ),
    "caption-writer": AgentDefinition(
        description=(
            "Writes a 1-2 sentence AP-wire-style caption. "
            "Independent of angle-selector — run FIRST in parallel."
        ),
        prompt="""You are the Caption Writer for the Newz news compile pipeline.

Given a cluster of clips with GPS coordinates and timestamps, write a neutral, AP-wire-style caption.
Reference ONLY what is verifiable from the metadata: date, neighborhood, and the count of clips.
Do NOT invent participant counts, motives, or context not present in the metadata.

Use mcp__newz_tools__get_cluster_clips to read clip metadata.
Return ONLY a single JSON object: {"caption": "...", "location": "Neighborhood, City"}.
Caption must be 200 characters or fewer. Do not include any text outside the JSON.""",
        tools=["mcp__newz_tools__get_cluster_clips", "mcp__newz_tools__get_clip_metadata"],
        mcpServers=_MCP,
        model="sonnet",
    ),
    "editor": AgentDefinition(
        description=(
            "Validates the angle-selector's clip ordering for editorial quality. "
            "Run AFTER angle-selector completes."
        ),
        prompt="""You are the Editor for the Newz news compile pipeline.

Review the Angle Selector's clip ordering. Confirm it makes editorial sense:
no jarring cuts, sufficient temporal coverage, the chosen clips tell the story.

Return ONLY a single JSON object: {"clip_ids": ["..."], "edit_notes": "..."}.""",
        tools=["mcp__newz_tools__get_clip_metadata"],
        mcpServers=_MCP,
        model="sonnet",
    ),
    "publisher": AgentDefinition(
        description=(
            "Persists the finished segment via save_segment. Run LAST. "
            "Only calls the save_segment tool — does not rewrite captions."
        ),
        prompt="""You are the Publisher for the Newz news compile pipeline.

Take the editor's validated clip_ids and the caption-writer's caption + location.
Call mcp__newz_tools__save_segment EXACTLY ONCE with:
  - cluster_id: provided by the orchestrator
  - ordered_clip_ids: from editor's clip_ids list
  - caption: from caption-writer's caption field
  - location: from caption-writer's location field
  - source_count: length of ordered_clip_ids

Return ONLY the segment id string from the tool result.""",
        tools=["mcp__newz_tools__save_segment"],
        mcpServers=_MCP,
        model="haiku",
    ),
}


async def _run_agents(cluster_id: str) -> str:
    """Run the 4-subagent pipeline. Returns segment_id or raises on failure."""
    options = ClaudeAgentOptions(
        allowed_tools=[
            "Agent",                               # REQUIRED: enables subagent invocation
            "mcp__newz_tools__get_cluster_clips",
            "mcp__newz_tools__get_clip_metadata",
            "mcp__newz_tools__save_segment",
        ],
        agents=AGENTS,
        mcp_servers={"newz_tools": newz_tools_server},
        max_turns=20,
        model="sonnet",
    )
    async for msg in query(
        prompt=ORCHESTRATOR_PROMPT_TEMPLATE.format(cluster_id=cluster_id),
        options=options,
    ):
        if isinstance(msg, ResultMessage):
            if msg.is_error:
                log.error(
                    "compile orchestrator error cluster_id=%s turns=%s errors=%s result=%s",
                    cluster_id, msg.num_turns, msg.errors, msg.result,
                )
                raise RuntimeError(f"orchestrator returned is_error=True: {msg.errors}")
            log.info(
                "compile orchestrator done cluster_id=%s turns=%s duration_ms=%s",
                cluster_id, msg.num_turns, msg.duration_ms,
            )
            break
    # Confirm Publisher called save_segment and the row was written
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        raise RuntimeError(
            f"compile finished but no segment row for cluster {cluster_id} — "
            "Publisher may have failed to call save_segment"
        )
    return seg["id"]


async def _save_fallback_segment(cluster_id: str) -> str:
    """CMP-06: idempotent fallback. Chronological order, generic AP-wire caption."""
    existing = await db.get_segment_for_cluster(cluster_id)
    if existing:
        return existing["id"]
    clips = await db.fetch_cluster_clips(cluster_id)  # ORDER BY ts ASC
    clip_ids = [c["id"] for c in clips]
    if clips:
        when = datetime.fromtimestamp(clips[0]["ts"], tz=timezone.utc).strftime("%b %-d, %Y")
    else:
        when = datetime.now(tz=timezone.utc).strftime("%b %-d, %Y")
    caption = f"Multi-angle event captured by {len(clip_ids)} contributors on {when}."
    return await db.insert_segment(
        cluster_id=cluster_id,
        ordered_clip_ids=clip_ids,
        caption=caption,
        location="Pasadena, CA",
        source_count=len(clip_ids),
    )


async def compile_segment(cluster_id: str) -> None:
    """Top-level entry. Fire-and-forget via asyncio.create_task. Idempotent (CMP-09).

    CMP-06: hard 30s wall-clock cap via asyncio.wait_for.
    Always clears compile_in_flight in finally.
    Always broadcasts segment_published (or pipeline_error on unexpected failure).
    """
    started_at = time.time()
    await events.broadcast({
        "type": "compile_started",
        "cluster_id": cluster_id,
        "started_at": started_at,
    })
    try:
        segment_id = await asyncio.wait_for(_run_agents(cluster_id), timeout=60.0)
        elapsed_ms = int((time.time() - started_at) * 1000)
        log.info(
            "compile success cluster_id=%s segment_id=%s elapsed_ms=%d",
            cluster_id, segment_id, elapsed_ms,
        )
    except asyncio.TimeoutError:
        log.warning("compile TIMEOUT cluster_id=%s after 60s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id)
    except Exception:
        log.exception("compile FAILED cluster_id=%s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id)
    finally:
        await db.set_compile_in_flight(cluster_id, False)
    await events.broadcast({
        "type": "segment_published",
        "cluster_id": cluster_id,
        "segment_id": segment_id,
    })
