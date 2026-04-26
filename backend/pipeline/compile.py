"""
backend/pipeline/compile.py — vision-enabled compile pipeline (Phase 4).

Public API:
    compile_segment(cluster_id: str) -> None
        Fire-and-forget coroutine. Called via asyncio.create_task from run.py.
        Hard 60s wall-clock cap (CMP-06). Fallback on timeout or error.

Pipeline:
    1. caption-writer (direct vision query, midpoint keyframe per clip)
    2. orchestrator chain: angle-selector → editor → publisher (subagents)

Caption-writer is a top-level query() with image content blocks rather than a
subagent — claude-agent-sdk 0.1.68 does not propagate image content from MCP
tool returns into a subagent's vision context, so we pre-extract keyframes in
Python and inline them into the user message.

MCP tools (subagents only): get_cluster_clips, get_clip_metadata, save_segment.
"""
import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    ResultMessage,
    AssistantMessage,
    TextBlock,
)

from .. import config, db, events
from .compile_tools import newz_tools_server
from .keyframes import extract_cluster_keyframes
from .stitch import stitch_clips
from .caption_pipeline import generate_caption

log = logging.getLogger(__name__)


CAPTION_WRITER_SYSTEM = """You are the Caption Writer for the Newz news compile pipeline.

You are given:
- Cluster metadata: date, neighborhood (inferable from coords), clip count, GPS coordinates, timestamps
- One keyframe image per clip (midpoint frame), in the same order as the metadata

Write a neutral, AP-wire-style caption grounded in BOTH sources.

Rules:
- Reference ONLY visually verifiable facts from the keyframes (e.g., "people walking with signs", "vehicles on a roadway", "smoke visible") combined with metadata (date, neighborhood, clip count).
- DO NOT infer motive, cause, affiliation, or topic. "Tuition protest" is forbidden; "people gathered with signs" is allowed.
- DO NOT count people unless the count is unambiguous (5 or fewer visible).
- If keyframes are visually ambiguous, default to metadata-only phrasing.

Return ONLY a single JSON object: {"caption": "...", "location": "Neighborhood, City"}.
Caption must be 200 characters or fewer. No text outside the JSON.
"""

ORCHESTRATOR_PROMPT_TEMPLATE = """Compile cluster {cluster_id} into a published news segment.

The caption and location have ALREADY been written by the caption-writer:
  caption: {caption}
  location: {location}

Steps — use the named subagents in this order:
1. Run angle-selector to pick the best 2-4 clips and order them.
2. Run editor on angle-selector's JSON output to validate the clip order.
3. Run publisher with editor's clip_ids and the caption/location above.

Pass each subagent's JSON output verbatim into the next subagent's prompt.
The cluster_id is: {cluster_id}
"""

_MCP = ["newz_tools"]

AGENTS = {
    "angle-selector": AgentDefinition(
        description=(
            "Picks 2-4 best clips from a cluster and orders them: "
            "establishing → action → reaction. Run FIRST."
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

The caption and location are provided by the orchestrator (already written upstream).
Take the editor's validated clip_ids and the provided caption + location.
Call mcp__newz_tools__save_segment EXACTLY ONCE with:
  - cluster_id: provided by the orchestrator
  - ordered_clip_ids: from editor's clip_ids list
  - caption: provided by the orchestrator
  - location: provided by the orchestrator
  - source_count: length of ordered_clip_ids

Return ONLY the segment id string from the tool result.""",
        tools=["mcp__newz_tools__save_segment"],
        mcpServers=_MCP,
        model="haiku",
    ),
}


def _build_caption_user_message(
    cluster_id: str,
    metadata: list[dict],
    frames: list[tuple[str, bytes]],
) -> dict[str, Any]:
    """Build a single user message with text + image content blocks.

    Returned dict matches the SDK's stream-json wire format (see
    claude_agent_sdk/_internal/client.py). The image blocks pass through the
    bundled CLI to the Anthropic API verbatim.
    """
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Cluster ID: {cluster_id}\n"
                f"Cluster metadata (one entry per clip, ordered by timestamp):\n"
                f"{json.dumps(metadata, indent=2)}\n\n"
                f"Below are {len(frames)} keyframe(s), one per clip, in the same order."
            ),
        }
    ]
    for clip_id, png in frames:
        content.append({"type": "text", "text": f"Keyframe for clip {clip_id}:"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(png).decode("ascii"),
            },
        })
    return {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


def _extract_text_from_assistant(msg: AssistantMessage) -> str:
    parts: list[str] = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
    return "".join(parts)


def _parse_caption_json(raw: str) -> dict:
    """Parse the caption-writer's JSON output. Tolerates ```json fences."""
    text = raw.strip()
    if text.startswith("```"):
        # strip code fence
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


async def _run_caption_writer_with_vision(cluster_id: str) -> dict:
    """Direct query() call with image content blocks. Returns {caption, location}.

    Raises if no frames could be extracted or no JSON came back.
    """
    frames = await extract_cluster_keyframes(cluster_id)
    if not frames:
        raise RuntimeError(f"no keyframes extracted for cluster {cluster_id}")

    clips = await db.fetch_cluster_clips(cluster_id)
    metadata = [
        {"id": c["id"], "lat": c["lat"], "lng": c["lng"], "ts": c["ts"]}
        for c in clips
    ]
    user_msg = _build_caption_user_message(cluster_id, metadata, frames)

    async def _prompt_stream():
        yield user_msg

    options = ClaudeAgentOptions(
        system_prompt=CAPTION_WRITER_SYSTEM,
        model="sonnet",
        max_turns=1,
    )

    last_text = ""
    async for msg in query(prompt=_prompt_stream(), options=options):
        if isinstance(msg, AssistantMessage):
            text = _extract_text_from_assistant(msg)
            if text:
                last_text = text
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                raise RuntimeError(
                    f"caption-writer query error cluster_id={cluster_id} "
                    f"errors={msg.errors}"
                )
            break

    if not last_text:
        raise RuntimeError(f"caption-writer returned no text for cluster {cluster_id}")
    data = _parse_caption_json(last_text)
    if "caption" not in data or "location" not in data:
        raise RuntimeError(f"caption-writer JSON missing required keys: {data}")
    return data


async def _run_orchestrator_chain(cluster_id: str, caption_data: dict) -> str:
    """Run angle-selector → editor → publisher with caption pre-injected."""
    options = ClaudeAgentOptions(
        allowed_tools=[
            "Agent",
            "mcp__newz_tools__get_cluster_clips",
            "mcp__newz_tools__get_clip_metadata",
            "mcp__newz_tools__save_segment",
        ],
        agents=AGENTS,
        mcp_servers={"newz_tools": newz_tools_server},
        max_turns=20,
        model="sonnet",
    )
    prompt = ORCHESTRATOR_PROMPT_TEMPLATE.format(
        cluster_id=cluster_id,
        caption=caption_data["caption"],
        location=caption_data["location"],
    )
    async for msg in query(prompt=prompt, options=options):
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
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        raise RuntimeError(
            f"compile finished but no segment row for cluster {cluster_id} — "
            "Publisher may have failed to call save_segment"
        )
    return seg["id"]


async def _run_agents(cluster_id: str) -> str:
    """Run vision caption-writer, then the 3-subagent chain. Returns segment_id."""
    caption_data = await _run_caption_writer_with_vision(cluster_id)
    log.info(
        "compile caption written cluster_id=%s caption=%r location=%r",
        cluster_id, caption_data.get("caption"), caption_data.get("location"),
    )
    return await _run_orchestrator_chain(cluster_id, caption_data)


async def _get_children_with_vecs(cluster_id: str) -> list[dict]:
    """Load child clips for cluster with their embedding vectors attached."""
    rows = await db.fetch_cluster_clips_with_children(cluster_id)
    children = []
    for r in rows:
        vec = await db.get_embedding(r["id"])
        children.append({**r, "vec": vec})
    return children


async def _save_fallback_segment(cluster_id: str, video_url: str | None = None) -> str:
    """CMP-06: idempotent fallback. Chronological order, generic AP-wire caption."""
    existing = await db.get_segment_for_cluster(cluster_id)
    if existing:
        return existing["id"]
    clips = await db.fetch_cluster_clips(cluster_id)
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
        video_url=video_url,
    )


async def compile_segment(cluster_id: str) -> None:
    """Top-level entry. Fire-and-forget via asyncio.create_task. Idempotent (CMP-09).

    Phase 4.5: Three parallel tracks inside a 60s cap:
      Track A: _run_agents() — existing caption-writer + angle-selector → editor → publisher
      Track B: stitch_clips() — ffmpeg concat of selected child slices → .webm file
      Track C: generate_caption() — frame-based Haiku/Sonnet visual caption

    After all tracks complete, insert_segment is called again (idempotent ON CONFLICT)
    to update video_url and vision caption on the row Track A already wrote.
    """
    from .cluster import CLUSTERS  # avoid circular at module level

    started_at = time.time()
    await events.broadcast({
        "type": "compile_started",
        "cluster_id": cluster_id,
        "started_at": started_at,
    })

    video_url: str | None = None
    segment_id: str = ""

    try:
        cluster_cache = CLUSTERS.get(cluster_id)
        children = await _get_children_with_vecs(cluster_id)

        stitch_refs = []
        for child in children:
            if child.get("parent_path") and child.get("end_offset_sec") is not None:
                stitch_refs.append({
                    "path": child["parent_path"],
                    "start_offset_sec": child.get("start_offset_sec", 0.0),
                    "end_offset_sec": child["end_offset_sec"],
                })
        if not stitch_refs:
            clips = await db.fetch_cluster_clips(cluster_id)
            stitch_refs = [
                {"path": c["path"], "start_offset_sec": 0.0, "end_offset_sec": None}
                for c in clips[:3]
            ]

        output_path = str(config.DATA_DIR / "clips" / f"{cluster_id}_compiled.mp4")
        centroid = cluster_cache.centroid if cluster_cache else None

        results = await asyncio.wait_for(
            asyncio.gather(
                _run_agents(cluster_id),
                stitch_clips(stitch_refs, output_path),
                generate_caption(cluster_id, centroid, children) if centroid is not None and children else asyncio.sleep(0),
                return_exceptions=True,
            ),
            timeout=60.0,
        )

        agent_result, stitch_result, caption_result_raw = results

        if isinstance(stitch_result, str) and stitch_result and Path(stitch_result).exists():
            video_url = f"/media/{Path(stitch_result).name}"
        else:
            log.warning("stitch returned no usable path: %s", stitch_result)

        caption_result = caption_result_raw if isinstance(caption_result_raw, dict) else None

        if isinstance(agent_result, Exception):
            log.error("agent track failed: %s — using fallback", agent_result)
            segment_id = await _save_fallback_segment(cluster_id, video_url)
        else:
            segment_id = agent_result

        if video_url or caption_result:
            seg = await db.get_segment_for_cluster(cluster_id)
            if seg:
                clip_ids = json.loads(seg["ordered_clip_ids"]) if isinstance(seg.get("ordered_clip_ids"), str) else seg.get("ordered_clip_ids", [])
                await db.insert_segment(
                    cluster_id=cluster_id,
                    ordered_clip_ids=clip_ids,
                    caption=caption_result["caption"] if caption_result else seg.get("caption", ""),
                    location=caption_result["location"] if caption_result else seg.get("location", ""),
                    source_count=seg.get("source_count", 1),
                    video_url=video_url or seg.get("video_url"),
                )

        elapsed_ms = int((time.time() - started_at) * 1000)
        log.info(
            "compile success cluster_id=%s segment_id=%s elapsed_ms=%d video_url=%s",
            cluster_id, segment_id, elapsed_ms, video_url,
        )

    except asyncio.TimeoutError:
        log.warning("compile TIMEOUT cluster_id=%s after 60s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id, video_url)
    except Exception:
        log.exception("compile FAILED cluster_id=%s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id, video_url)
    finally:
        await db.set_compile_in_flight(cluster_id, False)

    await events.broadcast({
        "type": "segment_published",
        "cluster_id": cluster_id,
        "segment_id": segment_id,
    })
