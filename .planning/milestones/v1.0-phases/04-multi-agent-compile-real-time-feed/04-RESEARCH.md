# Phase 04: Multi-Agent Compile + Real-Time Feed - Research

**Researched:** 2026-04-25
**Domain:** Claude Agent SDK 4-subagent pipeline + FastAPI SSE event bus + TikTok-style segment feed
**Confidence:** HIGH (Agent SDK + SSE + FastAPI patterns verified against current docs and PyPI 2026-04-25); MEDIUM (real wall-clock latency for the 4-agent pipeline is unmeasured — must be benchmarked in Wave 0)

## Summary

Phase 4 is the "Best Use of AI" payload phase: a four-subagent Claude Agent SDK pipeline (Angle Selector + Caption Writer in parallel, then Editor → Publisher) compiles each cluster of size ≥2 into a published news segment within a 30-second wall-clock cap, while a server-sent-events bus streams pipeline state to a TikTok-style autoplay feed that re-renders within 1 second of `segment_published`.

Phase 1-3 already shipped the load-bearing infrastructure: `events.broadcast()` is wired across embed, cluster, and pipeline-progress events but has zero subscribers (events.py:7-19) — Phase 4 must wire `GET /events` as the first subscriber consumer. The clustering stage emits `cluster_assigned` with `member_count` already (cluster.py:188-207), so the compile trigger needs only to read this and decide. The DB schema already has a `segments` table (db.py:53-61) but no helpers to insert/fetch — those are Phase 4 deliverables. The current `/feed` endpoint returns raw clips (db.py:118-138, app.py:97-100), and FeedTile renders raw video without captions or distance overlays (FeedTile.tsx); both upgrade to segment-aware shapes in this phase.

**Primary recommendation:** Use `claude-agent-sdk==0.1.68` (already pinned in CLAUDE.md, verified on PyPI 2026-04-25) with one `query()` call holding the four `AgentDefinition` subagents and a `create_sdk_mcp_server` exposing three custom tools (`get_cluster_clips`, `get_clip_metadata`, `save_segment`). Wrap the entire `query()` iterator in `asyncio.wait_for(..., timeout=30.0)` with a fallback path that synthesizes a default segment. For SSE, install `sse-starlette==3.3.4` (already a transitive dep of claude-agent-sdk) and use `EventSourceResponse` over a per-subscriber `asyncio.Queue` registered in a refactored `events.py`. On the frontend, replace polling with `EventSource` and listen for `segment_published` to refetch `/feed`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Compile trigger detection (cluster.size >= 2 AND no compile in flight) | API / Backend | — | Fires from `cluster_worker` after persistence; needs SQLite `compile_in_flight` flag and asyncio.create_task |
| Multi-agent pipeline orchestration | API / Backend | External (Anthropic) | `claude-agent-sdk.query()` runs in-process; subagents call out to Anthropic over HTTPS |
| 30s wall-clock timeout + fallback | API / Backend | — | `asyncio.wait_for` around `query()` iterator; fallback writes default segment via same `db.insert_segment` helper |
| Segment persistence | Database / Storage | API | New `db.insert_segment` helper writes to existing `segments` table; called via `save_segment` MCP tool |
| SSE endpoint `GET /events` | API / Backend | — | `EventSourceResponse` over per-client asyncio.Queue; subscriber registered/removed on connect/disconnect |
| Event broadcast (clip_added, cluster_assigned, pipeline_progress, segment_published, pipeline_error) | API / Backend | — | `events.broadcast(dict)` already exists; refactor to fan out to all queues |
| EventSource client + auto-reconnect | Browser / Client | — | Native browser API handles reconnect; React `useEffect` registers/closes |
| `/feed` segment proximity sort | API / Backend | Database | SQL JOIN clusters→segments→clips; haversine in Python at query time (small N) |
| FeedTile segment rendering (caption, distance, age, source count) | Browser / Client | — | Pure presentation; consumes new `Segment` type from `/feed` |
| Empty-state pre-seeded staged segment (FED-05) | Database / Storage | API | DB-resident default segment; seed_demo extension OR migration insert |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `claude-agent-sdk` | 0.1.68 | Multi-agent compile pipeline | [VERIFIED: PyPI 2026-04-25] Bundles Claude Code CLI binary in wheel — no Node.js needed on Railway. Pin locked by CLAUDE.md and ROADMAP. Released 2026-04-25 (today). Supports `agents={...}` parameter with `AgentDefinition` and per-agent `model="sonnet"`/`"haiku"` override. |
| `sse-starlette` | 3.3.4 | SSE endpoint for FastAPI | [VERIFIED: PyPI 2026-04-25] Already pulled in transitively by `claude-agent-sdk` 0.1.68 (via `mcp>=0.1.0`). Provides `EventSourceResponse` with built-in ping/heartbeat, disconnect detection via `request.is_disconnected()`. |
| `anthropic` | (transitive) | API client for Claude calls inside subagents | [CITED: research/STACK.md] Already pulled in by claude-agent-sdk; `ANTHROPIC_API_KEY` env var is auth. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiosqlite` | 0.20.0 (already installed) | Async SQLite for segment table | Already used by db.py — extend with `insert_segment`/`fetch_segments` helpers |
| `numpy` | 2.4.0+ (already installed) | Reused only for haversine math | No vector ops in Phase 4 — Phase 3 already pooled vectors |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `claude-agent-sdk` 0.1.68 (locked) | `>=0.2.111` for Opus 4.7 | [CITED: research/STACK.md] 0.2.x supports `claude-opus-4-7` but has incompatible API for `thinking.type.enabled`. Locked at 0.1.68 by CLAUDE.md — Sonnet/Haiku only. Don't switch. |
| `sse-starlette` `EventSourceResponse` | Hand-rolled `StreamingResponse` with `media_type="text/event-stream"` | sse-starlette handles `\n\n` framing, ping heartbeat, disconnect detection. Hand-rolling is 30 extra lines of bug surface. Don't. |
| `EventSource` browser API | WebSocket / Socket.IO | EventSource auto-reconnects on disconnect (RTM-02 free). Bidirectional not needed (uploads are POST). One-tenth the code. |
| Single mega-prompt to one Claude call | Locked: 4 subagents | [CITED: PROJECT.md / Best Use of AI track] Multi-agent narrative is the pitch hook. Don't collapse. |

**Installation:**
```bash
# Add to backend/requirements.txt
claude-agent-sdk==0.1.68

# sse-starlette comes in as transitive dep of claude-agent-sdk's mcp>=0.1.0 dep,
# but pin it explicitly for build reproducibility:
sse-starlette==3.3.4
```

**Version verification:** Verified on PyPI 2026-04-25:
- `claude-agent-sdk==0.1.68` — released 2026-04-25 (today's date, `pip index versions claude-agent-sdk` returned 0.1.68 as the latest of 70+ available versions)
- `sse-starlette==3.3.4` — latest on PyPI as of 2026-04-25
- Per-PyPI page: claude-agent-sdk 0.1.68 requires Python `>=3.10` and bundles the Claude Code CLI ("automatically bundled with the package — no separate installation required")

**Day-1 REPL gate:**
```python
import claude_agent_sdk
print([n for n in dir(claude_agent_sdk) if not n.startswith("_")])
# Must include: query, ClaudeAgentOptions, AgentDefinition, tool, create_sdk_mcp_server
# Plus message types: AssistantMessage, ResultMessage, TextBlock
```

## Architecture Patterns

### System Architecture Diagram

```
                          ┌──────────────────────────────────┐
                          │        Anthropic API             │
                          │  Sonnet 4.5 (subagents)          │
                          │  Haiku    (publisher tool-call)  │
                          └──────────────▲───────────────────┘
                                         │ HTTPS, ANTHROPIC_API_KEY
                                         │
┌─────────────────────────────────┐    ┌─┴───────────────────────────────────────┐
│  Browser (React)                │    │  FastAPI Monolith (one uvicorn process) │
│                                 │    │                                          │
│  Feed.tsx                       │    │  POST /clips ───┐                        │
│   ├─ EventSource("/events") ◀───┼────┤                 │                        │
│   ├─ on "segment_published"     │    │                 ▼                        │
│   │   → refetchFeed()           │    │  asyncio.create_task(run_pipeline)       │
│   ├─ on "cluster_assigned"      │    │     embed → cluster ──┐                  │
│   │   → debug overlay update    │    │                       │                  │
│   └─ FeedShell                  │    │                       ▼                  │
│       └─ FeedTile (segment)     │    │   if cluster.size >= 2 AND               │
│           ├─ <video autoplay>   │    │      not compile_in_flight:              │
│           ├─ caption            │    │      asyncio.create_task(compile_segment)│
│           ├─ distance overlay   │    │                       │                  │
│           ├─ age overlay        │    │                       ▼                  │
│           └─ source count       │    │   asyncio.wait_for(query(...), 30.0)     │
│                                 │    │     ├─ Angle Selector ─┐                 │
│  RecordFAB ──── POST /clips ────┼────┤     │                  ├─ Editor         │
│                                 │    │     ├─ Caption Writer ─┘   │             │
│                                 │    │                            ▼             │
│                                 │    │                         Publisher        │
│                                 │    │                         (haiku, MCP tool)│
│  GET /feed?lat&lng ◀────────────┼────┤                            │             │
│                                 │    │                            ▼             │
│                                 │    │   db.insert_segment + broadcast          │
│                                 │    │   {"type":"segment_published",...}       │
└─────────────────────────────────┘    │                            │             │
                                       │  ┌─────────────────────────┼──────────┐  │
                                       │  │ events.py               ▼          │  │
                                       │  │   _subscribers: list[Queue]        │  │
                                       │  │   broadcast() fan-out to all       │  │
                                       │  │   GET /events ──→ EventSourceResp  │  │
                                       │  └────────────────────────────────────┘  │
                                       │                                          │
                                       │  ┌────────────────────────────────────┐  │
                                       │  │ SQLite (newz.db, WAL)              │  │
                                       │  │   clips, clip_embeddings,          │  │
                                       │  │   clusters, segments               │  │
                                       │  └────────────────────────────────────┘  │
                                       └──────────────────────────────────────────┘

Data flow (compile path):
  cluster_worker emits cluster_assigned (existing)
  ↓ (same coroutine, after broadcast)
  if member_count >= 2 AND segments table has no row for cluster_id AND compile_in_flight=0:
     await db.set_compile_in_flight(cluster_id, True)
     asyncio.create_task(compile_segment(cluster_id))   ← non-blocking
  ↓
  compile_segment:
    broadcast {"type":"compile_started", cluster_id, started_at}
    try:
      result = await asyncio.wait_for(_run_agents(cluster_id), timeout=30.0)
      segment_id = await db.insert_segment(cluster_id, ordered_clip_ids, caption, location, source_count)
    except asyncio.TimeoutError:
      segment_id = await _save_fallback_segment(cluster_id)
    finally:
      await db.set_compile_in_flight(cluster_id, False)
    broadcast {"type":"segment_published", segment_id, cluster_id}
```

### Recommended Project Structure

```
backend/
├── app.py                          # ADD: GET /events endpoint, /feed switches to segments
├── db.py                           # ADD: insert_segment, fetch_segments, set_compile_in_flight, get_segment_for_cluster
├── events.py                       # MODIFY: subscribe()/unsubscribe() helpers; broadcast() unchanged shape
├── pipeline/
│   ├── compile.py                  # NEW: 4-subagent pipeline + fallback (~200 lines)
│   ├── compile_tools.py            # NEW: @tool definitions for MCP server (~80 lines)
│   ├── compile_trigger.py          # NEW (or inline in cluster.py): debounced trigger (~40 lines)
│   ├── cluster.py                  # MODIFY: trigger compile after cluster_assigned broadcast
│   └── run.py                      # unchanged (compile is fire-and-forget from cluster_worker)
├── seed/
│   └── demo_segment.py             # NEW: FED-05 pre-seeded staged demo segment loader
└── tests/
    ├── test_compile.py             # NEW: mock query() responses; verify save_segment called
    ├── test_compile_timeout.py     # NEW: asyncio.wait_for timeout path → fallback
    ├── test_events_sse.py          # NEW: subscribe, broadcast, EventSourceResponse framing
    ├── test_segments_db.py         # NEW: insert_segment, fetch_segments, set_compile_in_flight
    └── test_feed_segments.py       # NEW: GET /feed returns segments with proximity sort

frontend/src/
├── views/
│   └── Feed.tsx                    # MODIFY: replace location.key refetch with EventSource hook
├── components/
│   ├── FeedTile.tsx                # MODIFY: render Segment, not Clip — caption, distance, age, source count
│   ├── FeedShell.tsx               # MODIFY: snap-scroll TikTok-style if not already; passes Segment[]
│   └── EmptyState.tsx              # MODIFY: render the pre-seeded staged segment as fallback
├── api.ts                          # MODIFY: fetchFeed returns Segment[] (URLs prefixed); new fetchSegments(lat, lng)
├── hooks/
│   └── useEventSource.ts           # NEW: EventSource wrapper with auto-reconnect (built-in browser, but expose readyState)
├── types.ts                        # MODIFY: add Segment, ServerEvent union types
└── distance.ts                     # NEW: haversine + "2 blocks away" / "0.4 mi" formatter
```

### Pattern 1: Four-Subagent Pipeline via Single `query()` Call

**What:** One top-level `claude_agent_sdk.query()` call passes an orchestrator prompt and four `AgentDefinition` subagents. The orchestrator (top-level Claude) decides invocation order from its prompt; the SDK invokes subagents through the `Agent` tool.

**When to use:** This phase, exactly. The subagent pattern is the locked design (CMP-02/CMP-03/CMP-04). Hand-rolling four sequential `anthropic.messages.create` calls would forfeit subagent context isolation and the "Best Use of AI" narrative.

**Critical rules from official docs ([CITED: code.claude.com/docs/en/agent-sdk/subagents], 2026-04-25):**

1. **`Agent` MUST be in `allowed_tools`** at the top level. Without it, the orchestrator cannot delegate.
2. **Subagents cannot spawn their own subagents.** Don't include `Agent` in any `AgentDefinition.tools` array.
3. **Subagents start with fresh context.** The only channel from parent to subagent is the prompt string the orchestrator constructs at delegation time. Pass cluster_id and any IDs/context explicitly in the orchestrator prompt — the subagents only see what's in their `prompt` field plus whatever the orchestrator passes via the Agent tool call.
4. **Per-agent model override** via `AgentDefinition(model="sonnet" | "haiku" | "opus")`. For 0.1.68, sonnet/haiku only (locked by CLAUDE.md).
5. **MCP custom tools** via `create_sdk_mcp_server(name=..., tools=[@tool-decorated-fns])` registered in `ClaudeAgentOptions(mcp_servers={"newz_tools": server})`. Tools are addressable as `mcp__newz_tools__<tool_name>` in `allowed_tools`.

**Example (verified shape from official docs):**

```python
# backend/pipeline/compile.py
# Source: code.claude.com/docs/en/agent-sdk/subagents (2026-04-25)
# Source: code.claude.com/docs/en/agent-sdk/python (2026-04-25)
import asyncio
import json
import time

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from .. import db, events
from . import compile_tools  # imports @tool functions

# ---------- MCP server with custom tools ----------
@tool(
    "get_cluster_clips",
    "Return all clip metadata for a cluster (clip_ids, lat/lng, ts, paths)",
    {"cluster_id": str},
)
async def get_cluster_clips(args):
    rows = await db.fetch_cluster_clips(args["cluster_id"])
    return {"content": [{"type": "text", "text": json.dumps(rows)}]}

@tool(
    "get_clip_metadata",
    "Get GPS, timestamp, duration for a single clip",
    {"clip_id": str},
)
async def get_clip_metadata(args):
    clip = await db.get_clip(args["clip_id"])
    return {"content": [{"type": "text", "text": json.dumps(clip)}]}

@tool(
    "save_segment",
    "Persist the final compiled segment (terminal Publisher tool)",
    {
        "cluster_id": str,
        "ordered_clip_ids": list,
        "caption": str,
        "location": str,
        "source_count": int,
    },
)
async def save_segment(args):
    seg_id = await db.insert_segment(
        cluster_id=args["cluster_id"],
        ordered_clip_ids=args["ordered_clip_ids"],
        caption=args["caption"],
        location=args["location"],
        source_count=args["source_count"],
    )
    return {"content": [{"type": "text", "text": f"saved:{seg_id}"}]}

newz_tools_server = create_sdk_mcp_server(
    name="newz_tools",
    version="1.0.0",
    tools=[get_cluster_clips, get_clip_metadata, save_segment],
)

# ---------- Subagents ----------
AGENTS = {
    "angle-selector": AgentDefinition(
        description="Picks 2-4 best clips from a cluster and orders them: establishing → action → reaction. Use FIRST. Independent of caption-writer.",
        prompt="""You are the Angle Selector for the Newz news compile pipeline.

Given a cluster of multi-angle clips of one event, choose 2-4 clips that together tell the most complete story.
Order: establishing shot first, action peak in the middle, reaction or aftermath last.

You have access to mcp__newz_tools__get_cluster_clips and mcp__newz_tools__get_clip_metadata.
Return ONLY a single JSON object: {"clip_ids": ["...", "..."], "rationale": "..."}.
Do not include any text outside the JSON.""",
        tools=["mcp__newz_tools__get_cluster_clips", "mcp__newz_tools__get_clip_metadata"],
        model="sonnet",
    ),
    "caption-writer": AgentDefinition(
        description="Writes a 1-2 sentence AP-wire-style caption with date and neighborhood. Independent of angle-selector — runs in parallel.",
        prompt="""You are the Caption Writer for the Newz news compile pipeline.

Given a cluster of clips with GPS coordinates and timestamps, write a neutral, AP-wire-style caption.
Reference ONLY what is verifiable from the metadata: date, neighborhood, and the count of clips.
Do NOT invent participant counts, motives, or context not present in the input.

Return ONLY a single JSON object: {"caption": "...", "location": "Neighborhood, City"}.
Caption ≤200 chars. Do not include any text outside the JSON.""",
        tools=["mcp__newz_tools__get_cluster_clips", "mcp__newz_tools__get_clip_metadata"],
        model="sonnet",
    ),
    "editor": AgentDefinition(
        description="Validates the angle selector's ordering. Runs AFTER angle-selector and caption-writer complete.",
        prompt="""You are the Editor for the Newz news compile pipeline.

Review the Angle Selector's clip ordering. Confirm the order makes editorial sense:
no jarring cuts, sufficient temporal coverage, the chosen clips tell the story.

Return ONLY a single JSON object: {"clip_ids": ["..."], "edit_notes": "..."}.""",
        tools=["mcp__newz_tools__get_clip_metadata"],
        model="sonnet",
    ),
    "publisher": AgentDefinition(
        description="Persists the finished segment to the database via save_segment. Use LAST. Just calls the tool with the editor's clip order and the caption-writer's caption.",
        prompt="""You are the Publisher for the Newz news compile pipeline.

Take the editor's validated clip_ids and the caption-writer's caption + location.
Call mcp__newz_tools__save_segment EXACTLY ONCE with:
  - cluster_id (from the orchestrator's prompt)
  - ordered_clip_ids (from editor)
  - caption (from caption-writer)
  - location (from caption-writer)
  - source_count (len of ordered_clip_ids)

Return ONLY the segment id from the tool result.""",
        tools=["mcp__newz_tools__save_segment"],
        model="haiku",  # cheap, deterministic — just a tool call
    ),
}

ORCHESTRATOR_PROMPT_TEMPLATE = """Compile cluster {cluster_id} into a published news segment.

Steps (use the named subagents):
1. Run angle-selector AND caption-writer in parallel (they are independent).
2. Run editor on angle-selector's output to validate the clip order.
3. Run publisher with editor's clip_ids and caption-writer's caption+location.

Pass each subagent's JSON output verbatim into the next subagent's prompt.
The cluster_id is: {cluster_id}
"""

async def _run_agents(cluster_id: str) -> str:
    """Run the 4-subagent pipeline. Returns segment_id or raises."""
    options = ClaudeAgentOptions(
        # Agent tool MUST be in allowed_tools for subagent invocation
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
    final_text = ""
    async for msg in query(
        prompt=ORCHESTRATOR_PROMPT_TEMPLATE.format(cluster_id=cluster_id),
        options=options,
    ):
        if isinstance(msg, ResultMessage):
            final_text = msg.result or ""
            break
    # save_segment already wrote to DB; just confirm a row exists
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        raise RuntimeError(f"compile finished but no segment row for cluster {cluster_id}")
    return seg["id"]
```

### Pattern 2: 30-Second Hard Cap with `asyncio.wait_for` Fallback

**What:** Wrap the entire `_run_agents()` coroutine in `asyncio.wait_for(coro, timeout=30.0)`. On `asyncio.TimeoutError`, synthesize a fallback segment with default ordering and a generic caption.

**When to use:** Always — CMP-06 is non-negotiable.

**Critical:** `asyncio.wait_for` cancels the inner task on timeout. The Agent SDK's HTTP calls to Anthropic should respect cancellation, but the in-flight subagent's tool calls may have already mutated state (e.g., `save_segment` already wrote a row). The compile_segment wrapper must be idempotent: check `db.get_segment_for_cluster(cluster_id)` first; only write fallback if no row exists.

**Example:**

```python
async def compile_segment(cluster_id: str) -> None:
    """Top-level entry. Fire-and-forget from cluster_worker. Idempotent."""
    started_at = time.time()
    await events.broadcast({
        "type": "compile_started",
        "cluster_id": cluster_id,
        "started_at": started_at,
    })
    segment_id: str
    try:
        segment_id = await asyncio.wait_for(_run_agents(cluster_id), timeout=30.0)
        elapsed_ms = int((time.time() - started_at) * 1000)
        log.info("compile success cluster_id=%s segment_id=%s elapsed_ms=%d",
                 cluster_id, segment_id, elapsed_ms)
    except asyncio.TimeoutError:
        log.warning("compile TIMEOUT cluster_id=%s — falling back to default ordering", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id)
    except Exception as exc:
        log.exception("compile failed cluster_id=%s — falling back", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id)
    finally:
        await db.set_compile_in_flight(cluster_id, False)
    await events.broadcast({
        "type": "segment_published",
        "cluster_id": cluster_id,
        "segment_id": segment_id,
    })

async def _save_fallback_segment(cluster_id: str) -> str:
    """CMP-06: idempotent fallback. Default ordering = chronological by ts. Generic caption."""
    existing = await db.get_segment_for_cluster(cluster_id)
    if existing:
        return existing["id"]
    clips = await db.fetch_cluster_clips(cluster_id)  # ordered by ts ASC
    clip_ids = [c["id"] for c in clips]
    # Generic caption — grounded, references only metadata
    from datetime import datetime, timezone
    when = datetime.fromtimestamp(clips[0]["ts"], tz=timezone.utc).strftime("%b %-d, %Y")
    caption = f"Multi-angle event captured by {len(clip_ids)} contributors on {when}."
    return await db.insert_segment(
        cluster_id=cluster_id,
        ordered_clip_ids=clip_ids,
        caption=caption,
        location="Pasadena, CA",  # Caltech demo default; D-05 in CONTEXT may override
        source_count=len(clip_ids),
    )
```

### Pattern 3: SSE Event Bus with Per-Subscriber asyncio.Queue

**What:** `events.py` holds a module-level `_subscribers: list[asyncio.Queue]`. `GET /events` registers a fresh queue, yields each dequeued event as an SSE frame, and removes the queue on disconnect. `events.broadcast(event)` fan-outs `put_nowait` to every subscriber.

**Already partially built:** `backend/events.py:7-19` has the broadcast function and `_subscribers` list. Phase 4 adds the subscribe/unsubscribe lifecycle and the FastAPI route.

**Critical rules ([CITED: github.com/sysid/sse-starlette + MDN EventSource], 2026-04-25):**
1. **Always check `request.is_disconnected()`** in the generator loop — clients hang up without warning.
2. **Use `asyncio.wait_for(queue.get(), timeout=1.0)`** so the loop wakes to check `is_disconnected()` even when no events.
3. **Set `EventSourceResponse(ping=15)`** — sends a comment-only `:` heartbeat every 15s to keep proxies and mobile networks from killing idle TCP.
4. **Cleanup in `finally`** — remove the queue from `_subscribers` regardless of how the loop exits.
5. **HTTP/1.1 has a 6-connection-per-domain hard limit** in browsers. Open exactly ONE EventSource per tab. If user opens 6+ tabs, later tabs will starve. Mention in pitfalls.
6. **CORS: `EventSourceResponse` inherits app CORS middleware**, but remember that EventSource cannot send custom headers — `X-Session-Id` will not be sent by the browser on the SSE connection. Pass session id as a query param if needed: `?session=...`.

**Example:**

```python
# backend/events.py
import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue] = []
_LOCK = asyncio.Lock()  # protects subscriber list mutation

async def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)  # bounded — drop if a slow client backs up
    async with _LOCK:
        _subscribers.append(q)
    log.info("sse subscribe count=%d", len(_subscribers))
    return q

async def unsubscribe(q: asyncio.Queue) -> None:
    async with _LOCK:
        if q in _subscribers:
            _subscribers.remove(q)
    log.info("sse unsubscribe count=%d", len(_subscribers))

async def broadcast(event: dict[str, Any]) -> None:
    """Fan-out to all subscribers. Drops events for slow clients (QueueFull)."""
    log.info("event %s", event.get("type"))
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("sse subscriber queue full — dropping event %s", event.get("type"))
```

```python
# backend/app.py (added to existing routes)
import json
from sse_starlette.sse import EventSourceResponse
from fastapi import Request

@app.get("/events")
async def sse_events(request: Request):
    q = await events.subscribe()

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield {"event": event.get("type", "message"), "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    continue  # loop again to check is_disconnected()
        finally:
            await events.unsubscribe(q)

    return EventSourceResponse(event_stream(), ping=15)
```

### Pattern 4: Compile Trigger from `cluster_worker` (CMP-01, CMP-09)

**What:** Immediately after `cluster_worker` broadcasts `cluster_assigned`, evaluate the trigger. If `member_count >= 2 AND no compile in flight AND no segment yet`, fire-and-forget `compile_segment(cluster_id)` via `asyncio.create_task`.

**Debounce rule (CMP-09):** Re-compile when a new clip joins an existing cluster, but debounce 30s. Implementation: `db.set_compile_in_flight(cluster_id, True, ttl_seconds=30)` returns False if already true within TTL — don't fire.

**Where it goes:** Either inline at the bottom of `cluster_worker` in `cluster.py`, OR in `run.py` after `cluster_worker` returns. Putting it in `run.py` keeps `cluster.py` pure and makes the trigger easy to mock in tests. Recommend `run.py`.

**Trade-off:** A compile triggered from `run.py` won't fire if `cluster_worker` is called outside `run_pipeline` (e.g., from a future bulk re-cluster). Acceptable for hackathon scope; document the constraint.

**Example:**

```python
# backend/pipeline/run.py (modified)
import asyncio
import logging
import time
from .. import events, db
from .embed import embed_worker
from .cluster import cluster_worker
from .compile import compile_segment

log = logging.getLogger(__name__)

async def run_pipeline(clip_id: str) -> None:
    try:
        vec = await embed_worker(clip_id)
        await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "embedded"})
        cluster_id = await cluster_worker(clip_id, vec)
        await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "clustered"})

        # Phase 4: CMP-01 + CMP-09 trigger
        if await _should_compile(cluster_id):
            asyncio.create_task(compile_segment(cluster_id))  # fire-and-forget
    except Exception as exc:
        log.exception("pipeline failed clip_id=%s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": str(exc)})

async def _should_compile(cluster_id: str) -> bool:
    """CMP-01: size >= 2 AND no compile in flight.
    CMP-09: re-compile on new arrivals, debounced 30s via in_flight TTL.
    """
    cluster = await db.get_cluster(cluster_id)
    if cluster["member_count"] < 2:
        return False
    in_flight = await db.is_compile_in_flight(cluster_id, ttl_seconds=30)
    if in_flight:
        return False
    # mark in flight under same lock (CAS-style); db helper does INSERT-or-UPDATE atomically
    return await db.set_compile_in_flight(cluster_id, True)
```

### Pattern 5: Frontend EventSource Hook

**What:** A React `useEventSource` hook opens a single `EventSource` to `/events`, dispatches incoming events to typed handlers, and cleans up on unmount. The browser handles auto-reconnect natively (RTM-02 free).

**When to use:** Mount on `Feed.tsx` (and only there — one EventSource per tab to avoid the 6-connection-per-domain limit).

**Example:**

```typescript
// frontend/src/hooks/useEventSource.ts
import { useEffect, useRef } from "react";
import { API_BASE } from "../api";

export type ServerEvent =
  | { type: "clip_added"; clip_id: string }
  | { type: "pipeline_progress"; clip_id: string; stage: "embedded" | "clustered" }
  | { type: "cluster_assigned"; clip_id: string; cluster_id: string; is_new_cluster: boolean; member_count: number; score_breakdown: any }
  | { type: "compile_started"; cluster_id: string; started_at: number }
  | { type: "segment_published"; cluster_id: string; segment_id: string }
  | { type: "pipeline_error"; clip_id: string; error: string };

export function useEventSource(onEvent: (e: ServerEvent) => void): void {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/events`);
    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as ServerEvent;
        handlerRef.current(ev);
      } catch {
        /* ignore malformed */
      }
    };
    es.onerror = () => {
      // browser auto-reconnects unless readyState === CLOSED (server returned non-200)
      // no manual reconnect needed (RTM-02)
    };
    return () => es.close();
  }, []);
}
```

```typescript
// frontend/src/views/Feed.tsx (modified)
import { useEventSource } from "../hooks/useEventSource";

useEventSource((ev) => {
  if (ev.type === "segment_published") {
    refetchFeed();  // RTM-03: feed re-renders within 1s
  }
});
```

### Anti-Patterns to Avoid

- **Holding the asyncio.Lock across `events.broadcast`:** Phase 3 already broadcasts outside the cluster lock for this reason. Phase 4 must do the same — broadcast may yield, and a slow SSE subscriber should not deadlock the compile worker.
- **Running `query()` synchronously in the request handler:** `POST /clips` returns 202 in <100ms. The compile pipeline is fire-and-forget from `cluster_worker`, NOT from the HTTP handler. Don't accidentally `await compile_segment(...)` from `app.ingest_clip`.
- **Making the Publisher subagent rewrite captions:** Per CMP-03, Publisher's tool set is `[mcp__newz_tools__save_segment]` only. It cannot edit captions. This is by design.
- **Polling `/feed` AND opening EventSource:** Pick one. After Phase 4, polling is removed (Feed.tsx:55 location.key refetch stays as a navigation refresh, but no setInterval).
- **Multiple EventSources per tab:** Browser limit is 6 per domain on HTTP/1.1. One per tab, mounted at the top-level `Feed.tsx`.
- **Mega-prompts trying to do all four agents in one Claude call:** [CITED: research/PITFALLS.md anti-pattern 4] Loses the multi-agent narrative — the load-bearing pitch hook.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multi-agent orchestration with shared state | Custom asyncio.gather of `anthropic.messages.create` calls | `claude_agent_sdk.query()` with `agents={...}` | Subagent context isolation, Agent tool routing, per-agent model override, transcript persistence — all built in. Also: hand-rolled forfeits the "Best Use of AI" pitch hook. |
| SSE response framing | Hand-rolled `StreamingResponse` with `\n\n` boundaries | `sse-starlette.EventSourceResponse` | Handles framing, ping heartbeat, disconnect detection, `Last-Event-ID` semantics. Already a transitive dep. |
| Auto-reconnect on SSE disconnect | Custom retry loop with exponential backoff | Browser's native `EventSource` | Browser auto-reconnects on transport failure. RTM-02 is free with `new EventSource(url)`. |
| Token-stream caption-writer with progressive UI | Streaming token UI in React | Just render the final caption in one go | Locked OUT of scope per PROJECT.md / WOW-02 deferred. Don't build. |
| Multi-agent status banner | "Angle Selector: done · Editor: working..." live UI | Don't render status banner in v1 | WOW-03 is deferred. CMP-07 emits status events for SSE so Phase 5 can build it later, but Phase 4 frontend should NOT render the banner. |
| Wow-factor "snap" cluster animation | CSS keyframes + DOM measurement to show clips merging | Don't build | WOW-01 deferred per ROADMAP. |
| Distance string formatting | Custom geocoding lookup | Inline haversine + simple "X mi" or "X blocks" formatter | "1 block ≈ 100m" approximation for hyperlocal — judge-readable, no API. |
| Vector search for "best clips" | FAISS/Qdrant nearest-neighbor | Just `ORDER BY ts ASC` for default ordering — Angle Selector picks intelligent order | Locked: NumPy-only at this scale (research/STACK.md) |

**Key insight:** Phase 4 deliberately keeps the frontend dumb. The pitch is the BACKEND multi-agent pipeline plus the LIVE feed update. Animations, streaming captions, status banners, and cluster snap-effects are explicitly out of scope (PROJECT.md WOW-01..04). Don't sneak them in.

## Runtime State Inventory

> Phase 4 is a greenfield additive phase — no rename/refactor. State inventory not required. New runtime state introduced:

| Category | Item | Who Owns It |
|----------|------|-------------|
| Stored data (NEW) | `segments` rows in SQLite (table already exists, no rows yet) | `db.insert_segment` only writes; readers via `fetch_segments`, `get_segment_for_cluster` |
| Stored data (NEW) | `compile_in_flight` and `last_compile_at` columns on `clusters` (schema migration) | `db.set_compile_in_flight`, `db.is_compile_in_flight` |
| Live service config | None | — |
| OS-registered state | None | — |
| Secrets/env vars (existing) | `ANTHROPIC_API_KEY` (already required by claude-agent-sdk) | Phase 4 confirms it's set; lifespan should fail loudly if missing AND `OFFLINE_DEMO=false` |
| Build artifacts | claude-agent-sdk wheel bundles Claude Code CLI binary into site-packages — installed at `pip install` time, no separate step | requirements.txt pin handles it |

**Schema migration needed:** `clusters` table currently lacks `compile_in_flight` and `last_compile_at` columns. CMP-01/CMP-09 need them. Add via `ALTER TABLE clusters ADD COLUMN ...` in `db.init()` (idempotent — `IF NOT EXISTS` not supported by SQLite for ALTER TABLE; use `PRAGMA table_info()` check OR catch the OperationalError on duplicate-column).

## Common Pitfalls

### Pitfall 1: Compile pipeline exceeds 30s wall-clock
**What goes wrong:** Sonnet calls take 8-15s each; sequential 4-agent run hits 40-60s; demo dies.
**Why it happens:** Default subagent invocation is sequential. Without explicit "run in parallel" instruction in the orchestrator prompt, Claude invokes them one at a time via the Agent tool.
**How to avoid:**
1. Orchestrator prompt explicitly says "Run angle-selector AND caption-writer in parallel" (Pattern 1).
2. Use Sonnet (not Opus) for subagents; Haiku for Publisher — locked by CLAUDE.md.
3. Hard timeout via `asyncio.wait_for(coro, 30.0)` (CMP-06).
4. Trim subagent prompts — each is currently <500 tokens. Don't grow them.
5. Pre-warm Anthropic API on FastAPI startup with a one-token query (analogous to Marengo pre-warm at app.py:18-34).
**Warning signs:** Local dry-run wall-clock >25s. ResultMessage.duration_ms >25000.
**Source:** [VERIFIED: research/PITFALLS.md pitfall 5; CITED: code.claude.com/docs/en/agent-sdk/subagents 2026-04-25 — "Multiple subagents can run concurrently, dramatically speeding up complex workflows."]

### Pitfall 2: Caption hallucination (CMP-08)
**What goes wrong:** Claude generates "hundreds gather to protest tuition hikes" when clips show 4 people in a hallway. Demo embarrassment.
**Why it happens:** Caption Writer's prompt is too open-ended; Claude pattern-matches to news training data.
**How to avoid:** Caption Writer prompt explicitly: "Reference ONLY what is verifiable from the metadata: date, neighborhood, count of clips. Do NOT invent participant counts, motives, or context." Keep caption ≤200 chars to physically constrain hallucination surface. Test with a single-angle cluster — caption must NOT claim "multi-angle" something.
**Warning signs:** Caption mentions specific numbers (people, vehicles, etc.) not in the metadata. Caption uses speculative verbs ("appears to", "suggests", "reportedly").
**Source:** [VERIFIED: research/PITFALLS.md pitfall 12]

### Pitfall 3: SSE connection limit (HTTP/1.1 6-per-domain)
**What goes wrong:** Judge opens the demo in 7 tabs to compare; 7th tab's EventSource hangs on CONNECTING. Demo looks broken.
**Why it happens:** Browsers cap 6 simultaneous connections per origin on HTTP/1.1. SSE counts.
**How to avoid:**
1. Mount `useEventSource` ONLY on `Feed.tsx`, not on every component.
2. Document in a comment that one tab = one EventSource.
3. Railway's reverse proxy uses HTTP/2 by default — verify in Wave 0 with `curl -v --http2`. If HTTP/2 is on, the limit is ~100, not 6, and the issue is moot.
**Warning signs:** EventSource readyState stuck at 0 (CONNECTING) on later-opened tabs.
**Source:** [CITED: developer.mozilla.org/en-US/docs/Web/API/EventSource 2026-04-25]

### Pitfall 4: Compile fires twice for the same cluster
**What goes wrong:** Two clips arrive within milliseconds; both `cluster_worker` invocations return the same cluster_id; both `_should_compile` checks pass; two `compile_segment` tasks race; two segments inserted; feed shows duplicate.
**Why it happens:** `member_count >= 2 AND not compile_in_flight` is a check-then-act race without a DB-level lock.
**How to avoid:**
1. `db.set_compile_in_flight(cluster_id, True)` should be a single atomic SQL statement (`UPDATE clusters SET compile_in_flight = 1 WHERE id = ? AND compile_in_flight = 0` — `cursor.rowcount == 1` means we got the lock; `0` means someone else did).
2. `compile_segment` always checks `db.get_segment_for_cluster` first (idempotent fallback).
3. Schema: add `UNIQUE(cluster_id)` constraint on `segments.cluster_id` so a duplicate insert hits SQLite-level error rather than silently inserting two rows. (NB: this means re-compile on new clip arrivals must UPDATE not INSERT — adjust `db.insert_segment` to be `INSERT ... ON CONFLICT(cluster_id) DO UPDATE`.)
**Warning signs:** Two `compile_started` events for the same cluster_id within 100ms.
**Source:** [VERIFIED: research/PITFALLS.md pitfall 11 (related: adversarial cluster collision); ASSUMED: race-window analysis specific to Phase 4 design]

### Pitfall 5: Agent SDK cold start at demo
**What goes wrong:** First Claude API call after idle takes 5-10s longer than warm; first compile of the demo blows the 30s budget.
**Why it happens:** Anthropic-side connection warmup; SDK process spawn (the bundled CLI binary).
**How to avoid:**
1. Pre-warm in `app.lifespan` with a one-token Sonnet query (~1-2s cost), parallel with Marengo pre-warm.
2. Skip pre-warm if `OFFLINE_DEMO=true` (matches existing Marengo pre-warm pattern at app.py:18-34).
3. The pre-warm query should NOT use the full agents config — just `query(prompt="ok", options=ClaudeAgentOptions(model="sonnet"))` to warm the connection.
**Warning signs:** First `compile_segment` of the day takes 35s+; subsequent ones <20s.
**Source:** [VERIFIED: research/PITFALLS.md pitfall 5; CITED: research/STACK.md "Pre-warm everything"]

### Pitfall 6: `save_segment` MCP tool can't see clip data
**What goes wrong:** Publisher subagent has `tools=["mcp__newz_tools__save_segment"]` — restricted by design (CMP-03). But it ALSO needs `cluster_id`, `ordered_clip_ids`, `caption`, `location`, `source_count` from the orchestrator's prompt. If orchestrator forgets to pass them, Publisher cannot improvise (no read tool).
**Why it happens:** Subagent context isolation. The orchestrator's prompt is the ONLY input to the subagent. Per official docs: "include any file paths, error messages, or decisions the subagent needs directly in that prompt."
**How to avoid:** The orchestrator prompt template MUST include the cluster_id. The orchestrator must pass each preceding subagent's JSON output verbatim into the next. The Publisher prompt explicitly enumerates the 5 fields it needs and where each comes from.
**Warning signs:** Test where Publisher emits a tool call missing one of the 5 required `save_segment` arguments.
**Source:** [CITED: code.claude.com/docs/en/agent-sdk/subagents — "What subagents inherit" section, 2026-04-25]

### Pitfall 7: Empty feed first impression (FED-05)
**What goes wrong:** Judge opens app, no segments yet (no clips submitted), feed is blank. First impression is "broken."
**Why it happens:** No pre-seeded segment.
**How to avoid:** Insert a single staged demo segment into the `segments` table at db.init time IF `segments` is empty. Use the staged demo clips from `backend/seed/demo/` (Phase 3 placeholders) — even if those are zero-byte placeholders today, Phase 5 will replace them with real clips. The empty-state segment can reference a static thumbnail/video served from `backend/seed/demo/staged.mp4` to be added in Phase 5.
**Warning signs:** Test where DB is empty and `/feed` returns `[]` — should return `[the_staged_segment]`.
**Source:** [VERIFIED: REQUIREMENTS.md FED-05]

### Pitfall 8: Slow SSE subscriber backs up the broadcast queue
**What goes wrong:** A judge's iPhone is on flaky wifi; SSE queue fills; broadcast hangs; cluster_worker can't broadcast; pipeline freezes.
**Why it happens:** Unbounded `asyncio.Queue` + slow consumer = memory grows AND `await q.put(event)` blocks. With bounded queue, `q.put_nowait` raises `QueueFull`.
**How to avoid:**
1. `asyncio.Queue(maxsize=64)` — bounded.
2. `broadcast()` uses `put_nowait` and catches `QueueFull` (Phase 3 already does this — events.py:18 — keep it).
3. Drop events for slow subscribers; they'll re-fetch on the next `segment_published` they DO get, or on navigate.
**Warning signs:** Logs show `QueueFull` warnings during demo.
**Source:** [CITED: events.py:18 existing behavior; VERIFIED: design choice from Phase 1]

## Code Examples

### Example: SQLite schema migration for compile_in_flight

```python
# backend/db.py — extend init()
async def init() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.executescript(SCHEMA_SQL)
        # Phase 4 migration: add compile tracking columns to clusters.
        # SQLite doesn't support ADD COLUMN IF NOT EXISTS — check via PRAGMA.
        async with conn.execute("PRAGMA table_info(clusters)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "compile_in_flight" not in cols:
            await conn.execute("ALTER TABLE clusters ADD COLUMN compile_in_flight INTEGER NOT NULL DEFAULT 0")
        if "last_compile_at" not in cols:
            await conn.execute("ALTER TABLE clusters ADD COLUMN last_compile_at REAL")
        await conn.commit()
    log.info("db.init: schema ready at %s", DB_PATH)
```

### Example: Atomic compile-in-flight CAS

```python
# backend/db.py — added helpers
async def set_compile_in_flight(cluster_id: str, value: bool, ttl_seconds: float = 30.0) -> bool:
    """Atomic compare-and-set. Returns True if we acquired the flag, False if already held.
    For value=True: only sets if currently 0 OR last_compile_at is older than ttl_seconds.
    For value=False: always clears.
    """
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        if value:
            cursor = await conn.execute(
                """UPDATE clusters
                   SET compile_in_flight = 1, last_compile_at = ?
                   WHERE id = ?
                     AND (compile_in_flight = 0 OR last_compile_at < ?)""",
                (now, cluster_id, now - ttl_seconds),
            )
            await conn.commit()
            return cursor.rowcount == 1
        else:
            await conn.execute(
                "UPDATE clusters SET compile_in_flight = 0 WHERE id = ?",
                (cluster_id,),
            )
            await conn.commit()
            return True

async def is_compile_in_flight(cluster_id: str, ttl_seconds: float = 30.0) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT compile_in_flight, last_compile_at FROM clusters WHERE id = ?",
            (cluster_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    flag, last = row
    if not flag:
        return False
    if last is None or time.time() - last > ttl_seconds:
        return False
    return True
```

### Example: Segment insert with conflict-on-cluster-id

```python
# backend/db.py — added
async def insert_segment(
    cluster_id: str,
    ordered_clip_ids: list[str],
    caption: str,
    location: str,
    source_count: int,
) -> str:
    """Idempotent: one segment per cluster. ON CONFLICT updates (CMP-09 re-compile)."""
    seg_id = uuid.uuid4().hex
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        # NOTE: schema must declare segments.cluster_id UNIQUE for this to work.
        # Add via migration in init() if not present:
        # CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_cluster_id ON segments(cluster_id);
        cur = await conn.execute(
            """INSERT INTO segments (id, cluster_id, ordered_clip_ids, caption, location, source_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cluster_id) DO UPDATE SET
                 ordered_clip_ids = excluded.ordered_clip_ids,
                 caption = excluded.caption,
                 location = excluded.location,
                 source_count = excluded.source_count
               RETURNING id""",
            (seg_id, cluster_id, json.dumps(ordered_clip_ids), caption, location, source_count, now),
        )
        row = await cur.fetchone()
        await conn.commit()
    return row[0]
```

(`segments.cluster_id` UNIQUE constraint must be added — Phase 4 schema migration.)

### Example: GET /feed proximity sort

```python
# backend/app.py — modified
import math
from fastapi import Query

@app.get("/feed")
async def feed(lat: float | None = Query(None), lng: float | None = Query(None)):
    """FED-01: proximity + recency sort. If lat/lng absent (no GPS), fall back to recency."""
    rows = await db.fetch_recent_segments(limit=50)
    if lat is None or lng is None:
        return {"segments": rows}

    def score(seg):
        d_m = haversine_m(lat, lng, seg["centroid_lat"], seg["centroid_lng"]) \
              if seg["centroid_lat"] is not None else 1e9
        age_s = max(1.0, time.time() - seg["created_at"])
        # Lower distance and lower age = higher score
        return -(d_m / 1000.0) - (age_s / 3600.0) * 0.5  # 1km ≈ 30min weight
    rows.sort(key=score, reverse=True)
    return {"segments": rows}
```

### Example: FeedTile segment card

```typescript
// frontend/src/components/FeedTile.tsx — modified
import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";

export function FeedTile({ segment, viewerLat, viewerLng }: {
  segment: Segment;
  viewerLat?: number;
  viewerLng?: number;
}) {
  const primaryClip = segment.ordered_clips[0];
  return (
    <div className="bg-[#1A1A1A] border-y border-[#262626]">
      <video
        src={primaryClip.url}
        autoPlay
        muted
        playsInline
        loop
        preload="metadata"
        className="w-full max-h-[80vh] bg-black"
      />
      <div className="px-4 py-3 space-y-2">
        <p className="text-white text-base leading-snug">{segment.caption}</p>
        <div className="flex justify-between text-xs text-[#A3A3A3]">
          <span>
            {viewerLat !== undefined && segment.centroid_lat !== null
              ? distanceLabel(viewerLat, viewerLng!, segment.centroid_lat, segment.centroid_lng!)
              : segment.location}
            {" · "}
            {relativeTime(segment.created_at)}
          </span>
          <span className="bg-[#262626] px-2 py-0.5 rounded-full">
            Compiled from {segment.source_count} angles
          </span>
        </div>
      </div>
    </div>
  );
}
```

### Example: Frontend distance helper

```typescript
// frontend/src/distance.ts (new)
export function haversineMeters(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function distanceLabel(viewLat: number, viewLng: number, segLat: number, segLng: number): string {
  const m = haversineMeters(viewLat, viewLng, segLat, segLng);
  if (m < 50) return "right here";
  if (m < 250) return `${Math.round(m / 100)} block${m < 150 ? "" : "s"} away`;
  if (m < 1600) return `${(m / 1609).toFixed(1)} mi away`;
  return `${(m / 1609).toFixed(0)} mi away`;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Sequential 4-Claude-call pipeline | `claude-agent-sdk` `agents={...}` with parallel hint | SDK 0.1.x stabilized late 2025 / early 2026 | Subagents run concurrently when the orchestrator decides — gives parallelism without manual asyncio.gather |
| WebSockets for one-way server push | Native `EventSource` + `sse-starlette` | Stable for 5+ years | Half the code, browser auto-reconnect, native HTTP/2 multiplexing |
| `BackgroundTasks` for fire-and-forget | `asyncio.create_task` | FastAPI docs warn since 0.95+ | Phase 1 already uses create_task — keep it |
| Polling `/feed` every 3s | EventSource subscribe to `/events` | 1-day deliverable | Polling traffic eliminated; <1s latency on segment_published; feed view is single source of truth |

**Deprecated/outdated:**
- `Marengo-retrieval-2.7` model name — sunset 2026-03-30 (already locked: `marengo3.0` lowercase per CLAUDE.md, EMB-01).
- `claude-agent-sdk` < 0.1.6x — pre-stabilization API surface, do not use.
- Hand-rolled SSE in FastAPI without `sse-starlette` — error-prone framing.

## Project Constraints (from CLAUDE.md)

The following directives from `CLAUDE.md` apply to Phase 4 and MUST be honored by the planner:

1. **Stack pin: `claude-agent-sdk==0.1.68`** — bundles CLI binary, no Node.js. Don't upgrade to 0.2.x.
2. **Models: Sonnet for subagents, Haiku for Publisher.** No Opus (would need 0.2.111+).
3. **Single-process FastAPI monolith.** Compile pipeline runs as `asyncio.create_task` from `cluster_worker`. NO Celery, NO Redis, NO message broker.
4. **SSE for real-time updates** (RTM-01..03). NOT WebSocket.
5. **Anonymity load-bearing.** No accounts, no profiles, no usernames in segment captions, no IP logging.
6. **iOS Safari is demo target.** FeedTile must use `playsInline muted autoPlay` (already in current FeedTile.tsx — preserve).
7. **30-second hard cap on compile pipeline wall-clock.** Fallback to default ordering + generic caption on timeout. CMP-06 non-negotiable.
8. **Pre-warm Anthropic on backend startup** (mirror existing Marengo pre-warm at app.py:18-34). Cold-start = dead demo.
9. **Live-first demo with staged-clip fallback.** `OFFLINE_DEMO=true` env flag must work — Phase 4 design must allow short-circuiting compile_segment to a cached result when this flag is on. Wire in Phase 5; Phase 4 just ensures the code path is mockable.
10. **Out of scope (do not propose):** wow-factor snap animation (WOW-01), streaming caption tokens (WOW-02), multi-agent status banner (WOW-03), permanent score overlay on feed (WOW-04). All deferred.
11. **Hot path latency:** `POST /clips` returns 202 in <100ms (ING-02). Compile must be fire-and-forget — never `await compile_segment` from a request handler.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CMP-01 | Compile triggered when cluster size >= 2 AND no compile in flight | Pattern 4 (compile trigger from `run.py`); `db.set_compile_in_flight` atomic CAS |
| CMP-02 | Claude Agent SDK orchestrator with 4 sub-agents | Pattern 1 + verified `AgentDefinition` API from official docs |
| CMP-03 | Each sub-agent has constrained tool set (Publisher is the only one that writes) | Pattern 1: Publisher has `tools=["mcp__newz_tools__save_segment"]` only |
| CMP-04 | Angle Selector and Caption Writer run in parallel; Editor → Publisher sequential | Pattern 1: orchestrator prompt explicitly says "in parallel" |
| CMP-05 | Pipeline produces a segment record: ordered clip IDs, AP-wire caption, source clip count | `db.insert_segment` schema; `save_segment` MCP tool signature |
| CMP-06 | Hard 30-second wall-clock cap; fallback to default ordering + generic caption | Pattern 2: `asyncio.wait_for(_run_agents(...), 30.0)` + `_save_fallback_segment` |
| CMP-07 | Pipeline status (current agent, elapsed time) emitted as events for SSE | `compile_started`, `segment_published` events; subagent invocation detection from official docs (parent_tool_use_id) |
| CMP-08 | Caption is grounded — references only what is in the clips' metadata | Caption Writer prompt explicit: "Reference ONLY what is verifiable from the metadata" |
| CMP-09 | Re-compiles when new clip joins existing cluster (debounced 30s) | Pattern 4: `is_compile_in_flight(ttl_seconds=30)` + `INSERT...ON CONFLICT(cluster_id) DO UPDATE` |
| FED-01 | `GET /feed?lat&lng` returns published segments sorted by proximity to viewer + recency | "GET /feed proximity sort" example (haversine + recency_decay) |
| FED-02 | Vertical full-screen feed with autoplay-on-scroll (TikTok-style) | FeedShell already vertical-scroll; add `<video autoPlay loop>`; CSS scroll-snap |
| FED-03 | Each segment card shows: video, AI caption, distance overlay, age overlay, source count badge | "FeedTile segment card" example |
| FED-04 | One-tap pivot from feed to camera (FAB visible on every feed view) | RecordFAB already mounted in current Feed.tsx:64 — preserve |
| FED-05 | Empty state shows pre-seeded staged demo segment so feed is never blank | Pitfall 7: insert at db.init when segments empty |
| RTM-01 | `GET /events` SSE endpoint streams pipeline events | Pattern 3 + sse-starlette EventSourceResponse |
| RTM-02 | Frontend EventSource auto-reconnects on disconnect | Pattern 5: native browser behavior, free |
| RTM-03 | Feed re-renders new segment at top within 1 second of `segment_published` event | Pattern 5: `useEventSource` → `refetchFeed()` on segment_published |

## Validation Architecture

> Skipped per `.planning/config.json` workflow.nyquist_validation = false.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Anonymous-by-default; no auth surface in Phase 4. Session UUID is opaque, never used as identity. |
| V3 Session Management | partial | `X-Session-Id` already attached to clip uploads (Phase 1, ING-06). EventSource cannot send custom headers — pass session via query param ONLY if needed (it isn't, for Phase 4). |
| V4 Access Control | yes | `GET /events` and `GET /feed` are public-by-design (anonymous content). `POST /clips` already validates MIME + size (app.py:81-89). New `GET /debug/clusters` (Phase 3) already `include_in_schema=False`. |
| V5 Input Validation | yes | Subagents receive ONLY content from the orchestrator prompt. `cluster_id` validated as 32-char hex (uuid4 format) before insertion into orchestrator prompt — prevents prompt injection via crafted cluster_ids. Pydantic models for segment fields. |
| V6 Cryptography | no | No new crypto; HTTPS via Vercel/Railway. Anthropic & TwelveLabs API keys server-side only. |
| V7 Error Handling | yes | Compile failures (timeout, exception) emit `pipeline_error` SSE event but body should NOT leak stack traces or internal paths. Existing run.py:27 already does this — preserve. |
| V14 Configuration | yes | `ANTHROPIC_API_KEY` must be set when `OFFLINE_DEMO=false`. Lifespan should fail loudly with a clear log message if missing. Don't fail startup if missing — log + degrade. |

### Known Threat Patterns for Phase 4 Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via clip metadata (e.g., user-controlled location string) | Tampering | Phase 4 reads no user-controlled strings — clip metadata is GPS lat/lng (numeric, validated 0-90 / 0-180 in app.py:83-84) and ts (numeric). No text input from clips. |
| Caption hallucination → defamation/misinformation | Information Disclosure | CMP-08: grounded prompt. Operator review before public deploy (Day-2 work, acknowledged in pitch). |
| API key exfiltration via subagent | Spoofing | Subagents have `tools` restricted; no `Bash` / `Read` / `Write` in any agent. Tools list is whitelist-only. |
| Segment ID enumeration → user clip linkage | Information Disclosure | `segment_id = uuid4().hex` (32 chars, non-derivable). `cluster_id` already same pattern. No PII in segment fields. |
| SSE connection exhaustion (DoS) | Denial of Service | `_subscribers` is in-process list; no persistence of identity. Bounded `Queue(maxsize=64)` drops events for slow clients (events.broadcast already does put_nowait). At hackathon scale (≤10 concurrent judges), not a real risk. |
| Broadcast loop spam (e.g., compile_started fires 1000x/sec) | Denial of Service | `compile_in_flight` flag with 30s TTL prevents this (CMP-09 debounce). |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `claude-agent-sdk` | CMP-02..09 | will install | 0.1.68 (PyPI 2026-04-25) | If install fails on Railway: `OFFLINE_DEMO=true` short-circuits to cached segment |
| `sse-starlette` | RTM-01..03 | will install (transitive of claude-agent-sdk) | 3.3.4 | None — pin explicitly |
| `ANTHROPIC_API_KEY` env var | CMP-02 (Claude calls) | unknown | — | `OFFLINE_DEMO=true` short-circuits compile to cached/fallback segment |
| Python 3.10+ runtime | claude-agent-sdk | confirmed (Railway uses Python 3.11) | 3.11 | — |
| Node.js | NOT required | — | — | claude-agent-sdk 0.1.68 bundles CLI binary in wheel |
| `aiosqlite` | new db helpers | confirmed (already in requirements.txt) | 0.20.0 | — |
| HTTP/2 reverse proxy on Railway | SSE >6 connections | needs Wave-0 verify | — | If HTTP/1.1: tell users to use one tab only |

**Missing dependencies with no fallback:**
- None — all blocking deps install via pip.

**Missing dependencies with fallback:**
- `ANTHROPIC_API_KEY` not set → `OFFLINE_DEMO=true` path serves cached segment (Phase 5 deliverable; Phase 4 ensures the trigger respects the flag and short-circuits to fallback before calling `query()`).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Sonnet 4.5 wall-clock per subagent is ~5-15s; parallel angle-selector + caption-writer + sequential editor + publisher fits under 30s | Pitfall 1 | If real latency is 25s+ per agent, the 30s cap will trigger fallback every time. Wave 0 must measure with one cluster. If too slow, plan a sub-agent reduction (drop Editor; have Angle Selector also do its own validation) before locking the design. |
| A2 | `claude-agent-sdk==0.1.68` supports `model="sonnet"` and `model="haiku"` strings on `AgentDefinition` | Standard Stack | Verified by [CITED: code.claude.com/docs/en/agent-sdk/python] showing `model: 'sonnet' \| 'opus' \| 'haiku' \| 'inherit'` and the same string format in the subagents docs. LOW risk — but 30-second REPL check on day 1 can confirm: `from claude_agent_sdk import AgentDefinition; AgentDefinition(description="x", prompt="y", model="sonnet")` should not raise. |
| A3 | The orchestrator's prompt-level instruction "Run angle-selector AND caption-writer in parallel" is sufficient to get parallel subagent invocation | Pattern 1 | If Claude invokes them sequentially anyway, the wall-clock doubles for those two stages. Mitigation: structure the prompt so caption-writer doesn't depend on angle-selector output, then if Claude is too cautious, compile.py can `asyncio.gather` two separate `query()` calls — but this loses single-orchestrator narrative. Wave 0 must measure. |
| A4 | "1 block ≈ 100m" is acceptable approximation for the distance overlay | distance.ts example | If judges nitpick "Pasadena blocks are 130m", the copy is wrong. Acceptable hack-day quality. |
| A5 | Pre-warm Anthropic with a one-token Sonnet query is sufficient to avoid the cold-start 5-10s penalty | Pitfall 5 | If Anthropic still cold-starts on first compile after a warm pre-warm, fallback covers it. LOW impact. |
| A6 | `segments.cluster_id` UNIQUE constraint is acceptable design (one segment per cluster, INSERT...ON CONFLICT updates) | Pattern 4 + Schema migration | If the product later wants segment history (multiple compiled segments per cluster as it grows), this constraint blocks it. For Phase 4 / hackathon: fine. Document for Phase 5+. |
| A7 | The current `backend/seed/demo/clip-{1,2,3}.mp4` placeholders (zero-byte from Phase 3) will be replaced with real clips in Phase 5; Phase 4 should NOT block on real clips existing | FED-05 + Wave 0 plan | If Wave 0 tests hit zero-byte files, a generic placeholder thumbnail is fine. The pre-seeded segment uses a `caption` and `source_count` that don't require real video to render in the FeedTile during Wave 0 unit tests. |
| A8 | `EventSource` browser API alone provides RTM-02 auto-reconnect — no library needed | Pattern 5 | Native browser behavior; verified from MDN. LOW risk. |
| A9 | The SDK's bundled CLI binary works on Railway's Python 3.11 image without additional system packages (libc compatibility) | Environment Availability | If Railway's image is too minimal (e.g., Alpine), the CLI binary may fail to spawn. Wave 0 should `pip install claude-agent-sdk` in CI and run a smoke `query(prompt="hi")`. Fallback: switch Railway to a larger base image. |

## Open Questions

1. **Which staged demo clip serves as the FED-05 empty-state segment's primary video URL?**
   - What we know: `backend/seed/demo/clip-{1,2,3}.mp4` are zero-byte placeholders (Phase 3 deferred). Real clips must be filmed at Caltech venue.
   - What's unclear: Should Phase 4 ship a generic "Welcome — submit a clip" segment with no video (just caption), or wait for Phase 5's real clips?
   - Recommendation: Phase 4 ships an empty-state SEGMENT that references one of the placeholder paths; Phase 5's filming task replaces the bytes. The frontend FeedTile's `<video src=...>` will gracefully show a black box on a 0-byte file (no error). The caption + source_count + location render fine.

2. **Where is the orchestrator prompt's "run in parallel" instruction enforced?**
   - What we know: Official docs say multiple subagents *can* run concurrently. Whether Claude actually does so depends on its planning.
   - What's unclear: Is the parallel-execution latency win measurable, or does Claude default to sequential anyway?
   - Recommendation: Wave 0 spike — instrument compile.py to log subagent invocation timestamps and measure overlap. If Claude is sequential, evaluate whether to run angle-selector and caption-writer as TWO separate `query()` calls via `asyncio.gather` (sacrifices single-orchestrator narrative for guaranteed parallelism). Decision belongs in CONTEXT.md.

3. **Should `compile_started` be a per-subagent event (CMP-07 "current agent")?**
   - What we know: CMP-07 says "current agent, elapsed time emitted as events." Phase 4 design above only emits `compile_started` and `segment_published`, not per-subagent transitions.
   - What's unclear: Is per-subagent SSE worth the complexity? Detecting subagent invocation requires inspecting `tool_use` blocks where `name == "Agent"` (per official docs).
   - Recommendation: Phase 4 emits `compile_started` + `segment_published` only. Per-subagent events are nice-to-have but the user-visible status banner is OUT OF SCOPE (WOW-03). If CMP-07 is interpreted strictly, add an `agent_started` event by inspecting `block.input.subagent_type` (per official docs Code Snippet on detecting subagent invocation). Decision belongs in CONTEXT.md.

4. **Should `_save_fallback_segment` use the actual cluster's centroid_lat/lng for `location` string, or a hardcoded "Pasadena, CA"?**
   - What we know: Pattern 2 example uses hardcoded "Pasadena, CA" for simplicity. Real clusters have centroid_lat/lng (cluster.py:55-58).
   - What's unclear: Reverse-geocoding lat/lng → "Neighborhood, City" requires either a hardcoded local lookup table, an external API (out of scope), or a hardcoded city based on demo venue.
   - Recommendation: For hackathon at Caltech, hardcode "Pasadena, CA" in fallback. The Caption Writer's real path can do better only because Sonnet has world knowledge of Caltech's location. Document as DEM-05 demo-mode behavior.

5. **Does the existing `cluster_assigned` SSE event already include enough info for the frontend debug overlay (RTM-04)?**
   - What we know: Phase 3's `cluster_assigned` payload includes `score_breakdown` with visual/gps/time/composite (cluster.py:188-207). RTM-04 is "Debug overlay updates similarity scores live" — already mapped to Phase 3 in REQUIREMENTS.md, not Phase 4.
   - What's unclear: Was RTM-04 fully delivered in Phase 3, or does Phase 4's SSE wiring complete it?
   - Answer: Per ROADMAP.md line 212, RTM-04 is a Phase 3 requirement, but the SSE endpoint that *delivers* the event lives in Phase 4. Phase 4 SSE wiring is the missing piece. Document this in the plan.

## Sources

### Primary (HIGH confidence)
- [code.claude.com/docs/en/agent-sdk/subagents](https://code.claude.com/docs/en/agent-sdk/subagents) — fetched 2026-04-25 — `AgentDefinition` fields, `Agent` tool requirement, subagent context isolation, parallel execution rationale
- [code.claude.com/docs/en/agent-sdk/python](https://code.claude.com/docs/en/agent-sdk/python) — fetched 2026-04-25 — `query()` signature, `ClaudeAgentOptions` parameters, message types (`ResultMessage`, `AssistantMessage`, `TextBlock`), MCP server creation, model override per agent
- [pypi.org/project/claude-agent-sdk/0.1.68/](https://pypi.org/project/claude-agent-sdk/0.1.68/) — fetched 2026-04-25 — release date 2026-04-25, Python 3.10+ requirement, bundled CLI binary
- [github.com/sysid/sse-starlette](https://github.com/sysid/sse-starlette) — fetched 2026-04-25 — `EventSourceResponse` signature, ping heartbeat, `request.is_disconnected()` pattern
- [developer.mozilla.org/en-US/docs/Web/API/EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource) — fetched 2026-04-25 — auto-reconnect behavior, 6-connection-per-domain HTTP/1.1 limit
- `pip index versions claude-agent-sdk` — local 2026-04-25 — confirmed 0.1.68 is current
- `pip index versions sse-starlette` — local 2026-04-25 — confirmed 3.3.4 is current
- `.planning/research/STACK.md` — Claude Agent SDK + Marengo locked decisions
- `.planning/research/ARCHITECTURE.md` — pipeline shape, single-process monolith, fire-and-forget pattern, full reference compile.py shape
- `.planning/research/PITFALLS.md` — Pitfall 5 (compile too slow), Pitfall 6 (WiFi), Pitfall 12 (caption hallucination), Tier 1-5 demo fallback
- `.planning/research/SUMMARY.md` — load-bearing decisions, build-order checkpoints
- `backend/events.py` — existing broadcast() shape; Phase 4 extends with subscribe/unsubscribe
- `backend/pipeline/cluster.py:188-207` — existing `cluster_assigned` event shape; Phase 4 reads `member_count` for trigger
- `backend/db.py:53-61` — existing `segments` table schema
- `backend/app.py:18-34` — existing Marengo pre-warm pattern; Phase 4 mirrors for Anthropic
- `backend/pipeline/run.py` — existing pipeline chain; Phase 4 extends with compile trigger

### Secondary (MEDIUM confidence)
- `.planning/phases/03-clustering-debug-overlay/03-01-SUMMARY.md` — confirmation that broadcast happens outside the asyncio.Lock; this pattern continues into Phase 4
- `.planning/phases/03-clustering-debug-overlay/03-02-SUMMARY.md` — TestClient + lifespan + AsyncMock pattern needed for Phase 4 tests too

### Tertiary (LOW confidence)
- Wall-clock benchmark estimates for Sonnet 4.5 subagent latency (5-15s/agent) — based on 2026-Q1 community reports; UNVERIFIED on the actual project's Anthropic account. **Wave 0 MUST measure this.**

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pip index verified versions today (2026-04-25); claude-agent-sdk 0.1.68 released today; sse-starlette 3.3.4 latest
- Architecture / Subagent API: HIGH — verified against official docs fetched 2026-04-25; matches research/ARCHITECTURE.md reference shape
- Wall-clock latency assumption: LOW — empirical measurement deferred to Wave 0
- Pitfalls: HIGH — derived from existing PITFALLS.md (already verified) plus Phase-4-specific race-condition analysis

**Research date:** 2026-04-25
**Valid until:** 2026-05-09 (14 days — claude-agent-sdk is on a fast release cycle; sse-starlette stable)

**Recommended Wave 0 spikes for Phase 4 plan:**
1. **30s budget benchmark** — install claude-agent-sdk locally, run a single `query()` with 4 dummy subagents on a synthetic cluster, measure ResultMessage.duration_ms. If >25s, raise immediately as a CONTEXT.md decision: drop Editor agent? Run angle-selector and caption-writer as two separate query() calls with asyncio.gather?
2. **HTTP/2 verification on Railway** — `curl -v --http2 https://newz-api.up.railway.app/health` and confirm `HTTP/2 200`. If HTTP/1.1, document the 6-tab limit.
3. **`AgentDefinition(model="sonnet")` smoke test** — confirm the literal string is accepted (not enum), confirm sub-agent receives the right model.
4. **`save_segment` MCP tool address** — confirm the `mcp__newz_tools__save_segment` whitelisting in `allowed_tools` actually permits Publisher to call it (per official docs convention).
