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
from .runs import compute_runs_for_cluster

log = logging.getLogger(__name__)


@tool(
    "get_cluster_runs",
    (
        "Return all RUNS in a cluster. A run is a contiguous span of similar "
        "3-second slices within a single parent clip — i.e. one continuous "
        "camera angle. Use these as candidates for angle selection. "
        "Each run has: id, parent_id, parent_path, start_offset_sec, "
        "end_offset_sec, duration_sec, lat/lng/ts (from parent), member_child_ids."
    ),
    {"cluster_id": str},
)
async def get_cluster_runs(args: dict) -> dict:
    runs = await compute_runs_for_cluster(args["cluster_id"])
    out: list[dict] = []
    for r in runs:
        parent = await db.get_clip(r.parent_id)
        out.append({
            "id": r.id,
            "parent_id": r.parent_id,
            "parent_path": r.parent_path,
            "start_offset_sec": r.start_offset_sec,
            "end_offset_sec": r.end_offset_sec,
            "duration_sec": round(max(0.0, r.end_offset_sec - r.start_offset_sec), 2),
            "lat": parent.get("lat") if parent else None,
            "lng": parent.get("lng") if parent else None,
            "ts": parent.get("ts") if parent else None,
            "member_child_ids": r.member_child_ids,
        })
    return {"content": [{"type": "text", "text": json.dumps(out)}]}


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
    tools=[get_cluster_runs, get_clip_metadata, save_segment],
)
