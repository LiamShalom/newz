"""
backend/pipeline/compile_tools.py — @tool definitions for the MCP server used by
the 4-subagent compile pipeline (Phase 4, CMP-02/CMP-03).

These three tools are exposed as mcp__newz_tools__<name> to subagents.
The save_segment tool is the ONLY write path — Publisher is the only subagent
allowed to call it (CMP-03).
"""
import json
import logging

from claude_agent_sdk import tool, create_sdk_mcp_server

from .. import db

log = logging.getLogger(__name__)


@tool(
    "get_cluster_clips",
    "Return all clip metadata for a cluster (clip_ids, lat/lng, ts, paths). Use to get available clips.",
    {"cluster_id": str},
)
async def get_cluster_clips(args: dict) -> dict:
    rows = await db.fetch_cluster_clips(args["cluster_id"])
    return {"content": [{"type": "text", "text": json.dumps(rows)}]}


@tool(
    "get_clip_metadata",
    "Get GPS coordinates, timestamp, and duration for a single clip.",
    {"clip_id": str},
)
async def get_clip_metadata(args: dict) -> dict:
    clip = await db.get_clip(args["clip_id"])
    return {"content": [{"type": "text", "text": json.dumps(clip)}]}


@tool(
    "save_segment",
    (
        "Persist the final compiled segment to the database. "
        "Call EXACTLY ONCE with all five required fields. "
        "Only the Publisher subagent is allowed to call this tool (CMP-03)."
    ),
    {
        "cluster_id":       str,
        "ordered_clip_ids": list[str],
        "caption":          str,
        "location":         str,
        "source_count":     int,
    },
)
async def save_segment(args: dict) -> dict:
    seg_id = await db.insert_segment(
        cluster_id=args["cluster_id"],
        ordered_clip_ids=args["ordered_clip_ids"],
        caption=args["caption"],
        location=args["location"],
        source_count=args["source_count"],
    )
    log.info("save_segment called cluster_id=%s seg_id=%s", args["cluster_id"], seg_id)
    return {"content": [{"type": "text", "text": f"saved:{seg_id}"}]}


newz_tools_server = create_sdk_mcp_server(
    name="newz_tools",
    version="1.0.0",
    tools=[get_cluster_clips, get_clip_metadata, save_segment],
)
