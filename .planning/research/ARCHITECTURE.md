# Architecture Research

**Domain:** Hyperlocal AI-native news platform (Newz) — anonymous video clip ingest + multimodal clustering + agentic editorial compile
**Researched:** 2026-04-24
**Confidence:** HIGH for component shape, FastAPI/SDK patterns, clustering math; MEDIUM for live-demo failure mode hardening (untested in pressure)
**Optimization target:** Live demo robustness in 24-48hr build window. "Boring tech, working demo" beats "exciting tech, broken demo."

---

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Browser (React)                             │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐     │
│  │ Recorder View  │  │   Feed View    │  │  Debug Overlay     │     │
│  │ MediaRecorder  │  │ <video> grid   │  │ similarity / GPS / │     │
│  │ + Geolocation  │  │ SSE subscribe  │  │ timestamp deltas   │     │
│  └────────┬───────┘  └────────┬───────┘  └─────────┬──────────┘     │
│           │ POST multipart    │ GET /events (SSE)  │ GET /clusters  │
└───────────┼────────────────────┼────────────────────┼────────────────┘
            │                    │                    │
┌───────────▼────────────────────▼────────────────────▼───────────────┐
│                     FastAPI Monolith (single process)                │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ HTTP Layer:                                                   │   │
│  │   POST /clips         (returns 202 + clip_id immediately)     │   │
│  │   GET  /feed?lat&lng  (proximity-sorted segments)             │   │
│  │   GET  /events        (SSE: clip_added, cluster_updated,      │   │
│  │                        segment_published)                     │   │
│  │   GET  /clusters/:id  (debug: scores, members)                │   │
│  └────────────────────────┬─────────────────────────────────────┘   │
│                           │ schedule via asyncio.create_task        │
│  ┌────────────────────────▼─────────────────────────────────────┐   │
│  │ Background Pipeline (in-process asyncio coroutines):          │   │
│  │   embed_worker  ──▶  cluster_worker  ──▶  compile_worker      │   │
│  │   (poll TL task)     (assign or new)     (Agent SDK pipeline) │   │
│  └────────────────────────┬─────────────────────────────────────┘   │
│  ┌────────────────────────▼─────────────────────────────────────┐   │
│  │ Event Bus: asyncio.Queue per connected SSE client             │   │
│  └───────────────────────────────────────────────────────────────┘   │
└──────────────┬─────────────────────┬──────────────┬─────────────────┘
               │                     │              │
┌──────────────▼─────────┐ ┌─────────▼──────┐ ┌────▼────────────────┐
│   Local FS / clips/    │ │  SQLite DB     │ │ External APIs        │
│   {clip_id}.webm       │ │  (single file) │ │ - Twelve Labs        │
│   served as static     │ │  WAL mode      │ │   Marengo 3.0 embed  │
│                        │ │                │ │ - Anthropic Claude   │
│                        │ │  clips,        │ │   Agent SDK          │
│                        │ │  embeddings,   │ │                      │
│                        │ │  clusters,     │ │                      │
│                        │ │  segments      │ │                      │
└────────────────────────┘ └────────────────┘ └──────────────────────┘
```

**Single process.** No Redis, no Celery, no separate workers, no Docker compose. One `uvicorn` command runs the entire backend. This is a deliberate hackathon trade-off — every dependency you add is a thing that can fail in front of judges.

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| **React frontend** | Camera capture, GPS, feed render, debug overlay | Single SPA, Vite dev server, MediaRecorder + Geolocation APIs |
| **FastAPI HTTP layer** | Accept uploads, serve feed, stream events, expose debug data | Synchronous routes that return 202 immediately + schedule background work |
| **Embed worker** | Submit clip to Marengo, poll until done, store embedding | `asyncio` task, polls `task.wait_for_done(sleep_interval=2)` |
| **Cluster worker** | Compare new embedding against existing clusters, assign or create | In-memory cluster index + SQLite write, runs in same loop |
| **Compile worker** | Run Claude Agent SDK pipeline on cluster, produce segment | Triggered when cluster reaches min_clip threshold (e.g. 2 clips) or after debounce (e.g. 30s of no new arrivals) |
| **Event bus** | Notify connected clients of state changes | `asyncio.Queue` per SSE connection, broadcast on each pipeline transition |
| **Storage layer** | Clips on disk, metadata in SQLite | `clips/` directory served via FastAPI `StaticFiles`; SQLite via `aiosqlite` |
| **Twelve Labs API** | Generate 512-d Marengo 3.0 multimodal embeddings | External HTTP, async via official `twelvelabs` Python SDK |
| **Claude Agent SDK** | Multi-agent compile (4 subagents: Selector, Editor, Captioner, Publisher) | `claude_agent_sdk.query()` with `agents={...}` param |

---

## Recommended Project Structure

```
newz/
├── backend/
│   ├── app.py                  # FastAPI app, route definitions, lifespan
│   ├── config.py               # env vars: TL_API_KEY, ANTHROPIC_API_KEY, paths
│   ├── db.py                   # SQLite init, schema, async helpers
│   ├── models.py               # Pydantic: Clip, Cluster, Segment, ScoreBreakdown
│   ├── pipeline/
│   │   ├── embed.py            # Twelve Labs Marengo 3.0 wrapper
│   │   ├── cluster.py          # Online clustering algorithm + score formula
│   │   ├── compile.py          # Claude Agent SDK multi-agent pipeline
│   │   └── tools.py            # @tool functions exposed to agents
│   ├── events.py               # SSE event bus (asyncio.Queue per client)
│   ├── feed.py                 # Proximity + recency feed ranking
│   └── seed/
│       ├── demo_clips/         # 3-4 pre-recorded clips of staged event
│       └── seed.py             # Replay script: posts demo clips on startup
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── views/
│   │   │   ├── Recorder.tsx    # MediaRecorder + GPS + POST /clips
│   │   │   ├── Feed.tsx        # SSE listener + segment grid
│   │   │   └── Debug.tsx       # Score breakdown overlay
│   │   ├── api.ts              # fetch wrappers
│   │   └── sse.ts              # EventSource wrapper hook
│   └── vite.config.ts          # proxy /api → FastAPI :8000
├── clips/                      # gitignored — local clip storage
├── newz.db                     # gitignored — SQLite file
└── requirements.txt
```

### Structure Rationale

- **`backend/pipeline/` is the heart.** Each file is one stage. Each is independently testable with a mock clip path. If `compile.py` blows up in front of judges, `cluster.py` still works and you fall back to "here are the clustered clips, the AI compile is post-hackathon polish."
- **`seed/demo_clips/`** is load-bearing for the demo. Three or four mp4/webm files of the staged event, replayed via `seed.py` to populate the DB on startup. This is the canonical "magic moment" path — must work even with zero internet.
- **Frontend is split by view**, not by component primitive. At 24hr scope, premature componentization wastes time. Three files (Recorder, Feed, Debug) own their state.
- **`clips/` on local FS, not S3.** S3 adds creds, region config, CORS, and a network dependency in the hot path. A local directory served via FastAPI `StaticFiles` is one line and never fails.

---

## Architectural Patterns

### Pattern 1: Fire-and-Forget Async Pipeline (asyncio.create_task)

**What:** HTTP handler accepts upload, persists clip metadata + bytes, returns 202 with `clip_id` immediately, then schedules embed → cluster → compile as a chained background coroutine.

**When to use:** Any latency-sensitive ingest where the user doesn't need to block on processing. Newz fits perfectly: the camera view returns to capture mode the instant the upload finishes, and the feed updates via SSE when each pipeline stage completes.

**Trade-offs:**
- ✅ Zero infrastructure (no Redis/Celery/RabbitMQ)
- ✅ Same process = same memory = no serialization overhead for the in-memory cluster index
- ✅ Easy to debug (single logfile, single process)
- ❌ If the FastAPI process dies mid-pipeline, in-flight work is lost (acceptable: re-run seed script)
- ❌ Doesn't scale past one machine (irrelevant for hackathon demo)

**Example:**
```python
# backend/app.py
from fastapi import FastAPI, UploadFile, BackgroundTasks
import asyncio

app = FastAPI()

@app.post("/clips", status_code=202)
async def ingest_clip(file: UploadFile, lat: float, lng: float, ts: float):
    clip_id = await db.insert_clip(file, lat, lng, ts)
    await events.broadcast({"type": "clip_added", "clip_id": clip_id})
    # Fire and forget — the HTTP response returns now, pipeline runs in background
    asyncio.create_task(run_pipeline(clip_id))
    return {"clip_id": clip_id, "status": "processing"}

async def run_pipeline(clip_id: str):
    try:
        embedding = await embed.generate(clip_id)        # ~5-15s on Marengo
        cluster_id = await cluster.assign_or_create(clip_id, embedding)
        await events.broadcast({"type": "cluster_updated", "cluster_id": cluster_id})
        if await cluster.should_compile(cluster_id):
            segment = await compile.run(cluster_id)
            await events.broadcast({"type": "segment_published", "segment_id": segment.id})
    except Exception as e:
        log.exception("pipeline failed for %s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": str(e)})
```

**Why not `BackgroundTasks`:** FastAPI's `BackgroundTasks` runs after response is sent but BEFORE the request lifecycle ends — long-running tasks block worker threads. `asyncio.create_task` is genuinely fire-and-forget on the event loop and is the right primitive here.

**Why not Celery:** Celery requires Redis, a worker process, separate logs, and a serialization story for clip data. For 24-48hr ship + single-laptop demo, that's pure cost.

### Pattern 2: Online Single-Pass Clustering with Composite Score

**What:** Maintain a small in-memory list of active clusters (each holding member clip embeddings + centroid GPS + median timestamp). For each new clip, compute composite similarity against every existing cluster, attach to the best match if it crosses threshold, else create a new cluster.

**When to use:** Small-scale (< few hundred active clusters), low-latency, no need for global reclustering, where new arrivals dominate the workload. For Newz hackathon scope (one staged event + a handful of judge submissions), this is the entire algorithm. No DBSCAN, no spectral clustering, no faiss index needed at this scale.

**Trade-offs:**
- ✅ O(N) per new clip where N = active clusters; trivially fast for N < 100
- ✅ Streams naturally — every new arrival immediately joins or forms a cluster
- ✅ Easy to surface scores for debug overlay
- ❌ Order-dependent: a clip arriving "early" may seed a cluster that should have merged into a later one
- ❌ No automatic cluster splitting if embeddings drift

For mitigation of order-dependence, see Pattern 3 below.

### Pattern 3: Sequential Multi-Agent Pipeline via Claude Agent SDK Subagents

**What:** A single `query()` call with four `AgentDefinition` subagents (Angle Selector, Editor, Caption Writer, Publisher). The orchestrator's prompt instructs Claude to invoke them in sequence, each receiving the prior agent's output as part of its input prompt.

**When to use:** When you want narrative-strength "multi-agent AI" framing AND each role has distinct expertise/tools. The Claude Agent SDK explicitly supports this — `agents={...}` in `ClaudeAgentOptions` plus `Agent` in `allowed_tools` gives you delegation.

**Trade-offs:**
- ✅ Each agent has its own system prompt + restricted tool set (Captioner can read clip metadata but cannot publish; Publisher can write segment record but cannot edit captions)
- ✅ Strong demo narrative ("watch four AI agents collaborate")
- ✅ Subagent transcripts persist independently — debug overlay can show what each agent decided
- ❌ More expensive per compile than one big prompt (4 subagent invocations + orchestrator)
- ❌ Subagents cannot spawn their own subagents (one-level nesting only)

**Example:**
```python
# backend/pipeline/compile.py
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition, tool, create_sdk_mcp_server

# ---------- Custom tools the agents can call ----------
@tool("get_cluster_clips", "Return all clips in a cluster with metadata", {"cluster_id": str})
async def get_cluster_clips(args):
    rows = await db.fetch_cluster(args["cluster_id"])
    return {"content": [{"type": "text", "text": json.dumps(rows)}]}

@tool("save_segment", "Persist the final compiled segment", {
    "cluster_id": str, "headline": str, "caption": str, "ordered_clip_ids": list, "location": str
})
async def save_segment(args):
    seg_id = await db.insert_segment(**args)
    return {"content": [{"type": "text", "text": f"saved:{seg_id}"}]}

@tool("get_clip_metadata", "Get GPS, timestamp, duration for a single clip", {"clip_id": str})
async def get_clip_metadata(args):
    return {"content": [{"type": "text", "text": json.dumps(await db.fetch_clip(args["clip_id"]))}]}

newz_tools = create_sdk_mcp_server(
    name="newz_tools",
    tools=[get_cluster_clips, save_segment, get_clip_metadata],
)

# ---------- The four subagents ----------
AGENTS = {
    "angle-selector": AgentDefinition(
        description="Picks which clips to include and in what order. Use first.",
        prompt="""You are the Angle Selector. Given a cluster of clips covering the same event from different angles, choose 2-4 clips that together tell the most complete story. Order them: establishing shot first, action peak in the middle, reaction or aftermath last. Return a JSON object: {"clip_ids": [...], "rationale": "..."}.""",
        tools=["mcp__newz_tools__get_cluster_clips", "mcp__newz_tools__get_clip_metadata"],
        model="sonnet",
    ),
    "editor": AgentDefinition(
        description="Validates the angle selector's ordering and produces the final shot list.",
        prompt="""You are the Editor. Review the Angle Selector's choice. Confirm it makes editorial sense (no jarring cuts, sufficient temporal coverage). Return the validated ordered list as JSON: {"clip_ids": [...], "edit_notes": "..."}.""",
        tools=["mcp__newz_tools__get_clip_metadata"],
        model="sonnet",
    ),
    "caption-writer": AgentDefinition(
        description="Writes a headline and 1-2 sentence caption with date and neighborhood.",
        prompt="""You are the Caption Writer. Given the cluster's GPS coordinates and timestamp, plus the editor's shot list, write a headline (<60 chars) and a caption (<200 chars). Include date and neighborhood-level location. Be neutral and factual. Return JSON: {"headline": "...", "caption": "...", "location": "..."}.""",
        tools=["mcp__newz_tools__get_clip_metadata"],
        model="sonnet",
    ),
    "publisher": AgentDefinition(
        description="Persists the finished segment to the database. Use last.",
        prompt="""You are the Publisher. Take the editor's shot list and the caption writer's headline+caption and call save_segment exactly once. Return only the segment id.""",
        tools=["mcp__newz_tools__save_segment"],
        model="haiku",  # cheap, deterministic, just a tool call
    ),
}

async def run(cluster_id: str) -> Segment:
    orchestrator_prompt = f"""Compile cluster {cluster_id} into a published news segment.

Steps (use the named subagents in this exact order):
1. Use the angle-selector agent to choose and order 2-4 clips.
2. Use the editor agent to validate the selection.
3. Use the caption-writer agent to produce a headline, caption, and location string.
4. Use the publisher agent to persist the final segment.

Pass each agent's JSON output into the next agent's prompt verbatim.
"""
    async for msg in query(
        prompt=orchestrator_prompt,
        options=ClaudeAgentOptions(
            allowed_tools=["Agent"],          # required for subagent invocation
            agents=AGENTS,
            mcp_servers={"newz_tools": newz_tools},
            max_turns=20,
        ),
    ):
        if hasattr(msg, "result"):
            return await db.fetch_latest_segment(cluster_id)
```

**State passing:** The orchestrator agent (the top-level Claude in the `query()` call) holds the conversation. Each subagent's final message is returned to the orchestrator as the `Agent` tool result. The orchestrator then constructs the next subagent's input prompt by quoting the prior result. **Subagents do not share memory** — only the orchestrator's main loop does. This is by design.

### Pattern 4: SSE-Driven Real-Time Feed (Single-Way, Not WebSocket)

**What:** Frontend opens one `EventSource` to `GET /events`, receives a stream of JSON-encoded events (`clip_added`, `cluster_updated`, `segment_published`, `pipeline_error`), and re-renders the feed on each.

**When to use:** Server-to-client streaming where the client never pushes mid-session. Newz fits exactly — clip uploads use a separate POST. SSE auto-reconnects on disconnect (browser handles it), serializes cleanly through any HTTP proxy, and is one-tenth the code of a WebSocket setup.

**Trade-offs:**
- ✅ ~30 lines server, ~15 lines client
- ✅ Native browser support (no socket.io dep)
- ✅ Auto-reconnect handled by browser
- ❌ Strictly server→client (fine here)
- ❌ Some corporate proxies buffer SSE — irrelevant for hackathon laptop wifi

**Example:**
```python
# backend/events.py
from sse_starlette.sse import EventSourceResponse
import asyncio, json

_subscribers: list[asyncio.Queue] = []

async def broadcast(event: dict):
    for q in _subscribers:
        await q.put(event)

@app.get("/events")
async def events():
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)
    async def gen():
        try:
            while True:
                event = await q.get()
                yield {"data": json.dumps(event)}
        finally:
            _subscribers.remove(q)
    return EventSourceResponse(gen())
```

```typescript
// frontend/src/sse.ts
useEffect(() => {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "segment_published") refetchFeed();
    if (ev.type === "cluster_updated") refetchDebug(ev.cluster_id);
  };
  return () => es.close();
}, []);
```

---

## Data Flow

### The Hot Path: Camera Tap → Feed Tile

```
[User taps record + stop]
      │
      ▼ (browser)
MediaRecorder.stop() → Blob (webm)
  + navigator.geolocation.getCurrentPosition()
  + Date.now()
      │
      ▼ POST /clips (multipart: file, lat, lng, ts)
FastAPI handler:
  1. Write blob to clips/{clip_id}.webm                  (~50ms)
  2. INSERT INTO clips ...                                (~5ms)
  3. broadcast {"type": "clip_added", clip_id}            (~1ms)
  4. asyncio.create_task(run_pipeline(clip_id))
  5. return 202 {"clip_id": ...}                          ← user sees "uploaded" here
      │
      ▼ background pipeline
[embed.generate(clip_id)]
  client.embed.task.create(model_name="Marengo-retrieval-3.0", video_file=path)
  task.wait_for_done(sleep_interval=2)                    (~5-15s)
  result.video_embedding.segments[*].embeddings_float     ← 512-d vectors
  Store: one row per (clip_id, segment_idx, vector)
      │
      ▼
[cluster.assign_or_create(clip_id, embedding)]
  # Pool segment vectors → single clip vector (mean of segment vectors)
  # Compare against centroid of every active cluster
  # Composite score formula (see Clustering Algorithm below)
  # Assign to best match if score > 0.55, else new cluster
      │
      ▼ broadcast {"type": "cluster_updated", cluster_id}
[cluster.should_compile(cluster_id)?]
  # True if cluster.size >= 2 AND no compile in flight AND
  # (cluster.size just hit threshold OR 30s since last new arrival)
      │
      ▼ if yes
[compile.run(cluster_id)] (~10-30s, 4-agent pipeline)
      │
      ▼ broadcast {"type": "segment_published", segment_id}
Frontend SSE handler refetches /feed
Feed re-renders with new segment tile at top
```

### State Management

```
Server-side:
  SQLite (durable)              In-memory caches (per-process)
  ┌──────────┐                  ┌──────────────────────┐
  │ clips    │  ←── reads ───── │ active_clusters: list│
  │ embeds   │  ←── reads ───── │   [(centroid_vec,    │
  │ clusters │  ─── writes ──→  │    centroid_gps,     │
  │ segments │                  │    median_ts,        │
  └──────────┘                  │    member_clip_ids)] │
                                └──────────────────────┘
Frontend:
  React state (per view, no global store needed at this scale)
    Recorder: { recording: bool, lastClipId: string }
    Feed:     { segments: Segment[] }
    Debug:    { selectedClusterId: string, scores: Map<...> }
```

### Key Data Flows

1. **Clip ingest:** `Browser → POST /clips → FS write → SQLite insert → 202 → background pipeline kick → SSE broadcast`. The POST returns in <100ms; the user does not wait on Marengo.

2. **Feed query:** `Browser → GET /feed?lat&lng → SQLite SELECT segments JOIN clusters → rank by haversine(viewer, cluster.centroid_gps) * weight + recency_decay → JSON`. Pure query, no AI in the hot path.

3. **Real-time updates:** `Background pipeline transitions → events.broadcast() → asyncio.Queue per SSE client → EventSource onmessage → React state update → re-render`.

4. **Debug overlay:** `User clicks cluster → GET /clusters/:id → SQLite returns cluster + member clips + per-clip score breakdown → render bar chart`.

---

## Clustering Algorithm (Concrete Proposal)

This is the core "magic" of the demo. Be opinionated. Show your work in the debug overlay.

### Inputs Per New Clip

- `e_new`: 512-d embedding vector (mean-pooled across Marengo segments for the clip — Marengo returns one vector per ~6s segment; pool to a single clip-level vector)
- `gps_new`: (lat, lng) tuple
- `ts_new`: unix epoch seconds

### Per Existing Cluster (cached in memory)

- `e_centroid`: mean of member clip vectors
- `gps_centroid`: mean of member GPS coordinates
- `ts_median`: median of member timestamps

### Component Scores (each normalized to [0, 1])

```python
import numpy as np
from haversine import haversine, Unit

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    # Marengo embeddings are L2-normalized but be defensive
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def visual_score(e_new, e_centroid) -> float:
    # Marengo cosine sim is typically [0.0, 1.0] in practice; clamp negatives
    return max(0.0, cosine_sim(e_new, e_centroid))

def gps_score(gps_new, gps_centroid, radius_m=200.0) -> float:
    # Hyperlocal: 200m radius is "same event" floor; >500m is "different event"
    d_m = haversine(gps_new, gps_centroid, unit=Unit.METERS)
    return max(0.0, 1.0 - d_m / radius_m)  # 1.0 at 0m, 0.0 at 200m+

def time_score(ts_new, ts_median, window_s=600.0) -> float:
    # Same-event window: 10 minutes
    delta_s = abs(ts_new - ts_median)
    return max(0.0, 1.0 - delta_s / window_s)
```

### Composite Score (Weighted Sum)

```python
W_VISUAL = 0.55   # Marengo is the strongest signal — multimodal includes audio + speech
W_GPS    = 0.30   # GPS is highly discriminating for hyperlocal
W_TIME   = 0.15   # Time prevents merging the same intersection's morning + evening events
THRESHOLD = 0.55  # Tune live during demo prep with the staged dataset

def composite(e_new, gps_new, ts_new, cluster) -> ScoreBreakdown:
    v = visual_score(e_new, cluster.e_centroid)
    g = gps_score(gps_new, cluster.gps_centroid)
    t = time_score(ts_new, cluster.ts_median)
    score = W_VISUAL * v + W_GPS * g + W_TIME * t
    return ScoreBreakdown(visual=v, gps=g, time=t, composite=score)
```

### Assignment Decision

```python
async def assign_or_create(clip_id, embedding, gps, ts):
    candidates = [(cluster, composite(embedding, gps, ts, cluster))
                  for cluster in active_clusters]
    if candidates:
        best_cluster, best_breakdown = max(candidates, key=lambda x: x[1].composite)
        if best_breakdown.composite >= THRESHOLD:
            await add_to_cluster(best_cluster.id, clip_id)
            update_centroid(best_cluster, embedding, gps, ts)
            return best_cluster.id, best_breakdown
    # No good match → new cluster
    new_id = await create_cluster(clip_id, embedding, gps, ts)
    return new_id, None
```

### Why these weights

- **Visual at 55%:** Marengo 3.0 multimodal embeddings already encode audio + speech + motion + visual. Two clips of the same event from different angles should still be highly similar in this space — that's the whole bet of using Marengo over a vision-only model. If we underweight it we lose the AI narrative.
- **GPS at 30%:** Decisive signal for hyperlocal. Two visually similar events (e.g., two protests, two car accidents) at different intersections should NOT cluster.
- **Time at 15%:** Prevents pathological merges across hours/days at the same location. Lower weight because GPS already heavily disambiguates.
- **Threshold 0.55:** With visual dominating, two clips of the same event will typically score visual ≥0.7, GPS ≥0.8, time ≥0.9, composite ≈0.83. Two unrelated clips at the same corner score visual ≈0.3, GPS ≈0.9, time ≈0.5, composite ≈0.51 → just below threshold. **Validate this empirically with the staged demo dataset before locking it.**

### Online vs Batch

**Online assignment, no batch reclustering.** Order-dependence is acceptable for the demo because:
1. The staged demo clips arrive in controlled order
2. Judge-submitted clips are few enough to inspect manually
3. Adding offline reclustering doubles the code surface for marginal demo win

If a misclustering happens during the demo, the debug overlay (showing low score) is itself a feature: "the system shows its work."

### When to Compile

```python
async def should_compile(cluster_id: str) -> bool:
    c = await db.get_cluster(cluster_id)
    if c.segment_id is not None:
        return False  # already compiled
    if len(c.member_clip_ids) < 2:
        return False  # need at least 2 angles for "multi-angle" claim
    if c.compile_in_flight:
        return False  # don't double-fire
    # Compile when (a) we just hit 3 clips OR (b) 30s of quiet after 2 clips
    if len(c.member_clip_ids) >= 3:
        return True
    return (time.time() - c.last_addition_ts) > 30
```

---

## Storage

### Clips: Local Filesystem

`clips/{clip_id}.webm` served via `app.mount("/clips", StaticFiles(directory="clips"))`. Browser plays clips by URL directly — no streaming server, no transcoding. WebM with VP9 codec is the MediaRecorder default in Chrome and plays back natively in `<video>`.

**Why not S3:** Adds region/credentials/CORS configuration, network round-trip in the upload hot path, and a failure mode that's hard to debug under demo pressure. Local FS is one mount line and never fails.

**Demo robustness implication:** If we lose network mid-demo, clips already on disk still play. The feed degrades gracefully to "compiled segments serving from cache."

### Embeddings: SQLite Column (BLOB)

```sql
CREATE TABLE clip_embeddings (
  clip_id TEXT NOT NULL,
  segment_idx INTEGER NOT NULL,
  start_offset_sec REAL NOT NULL,
  end_offset_sec REAL NOT NULL,
  vector BLOB NOT NULL,           -- np.float32 bytes, 512 dims = 2048 bytes
  PRIMARY KEY (clip_id, segment_idx),
  FOREIGN KEY (clip_id) REFERENCES clips(id)
);

CREATE TABLE clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL,  -- pending | done | failed
  cluster_id TEXT,
  created_at REAL NOT NULL
);

CREATE TABLE clusters (
  id TEXT PRIMARY KEY,
  centroid_vec BLOB,
  centroid_lat REAL,
  centroid_lng REAL,
  median_ts REAL,
  segment_id TEXT,
  last_addition_ts REAL,
  compile_in_flight INTEGER DEFAULT 0
);

CREATE TABLE segments (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  headline TEXT,
  caption TEXT,
  location_str TEXT,
  ordered_clip_ids TEXT,  -- JSON array
  created_at REAL NOT NULL
);

CREATE INDEX idx_clusters_segment ON clusters(segment_id) WHERE segment_id IS NOT NULL;
CREATE INDEX idx_clips_cluster ON clips(cluster_id);
```

**Why not a vector DB (Qdrant, Pinecone, Chroma):** At hackathon scale (< few hundred vectors), brute-force cosine similarity in NumPy over an in-memory list is faster than any vector DB round-trip and removes a dependency. We compute composite scores in pure Python anyway — the vector index buys us nothing.

**Why SQLite over Postgres:** Zero setup, single file, WAL mode handles concurrent reads + occasional writes fine. Use `aiosqlite` for async access from FastAPI.

### Active Clusters: In-Memory + SQLite Mirror

Keep `active_clusters: list[ClusterCache]` in process memory (rebuilt from SQLite at startup via lifespan event). Update both on each cluster mutation. SQLite is the source of truth; in-memory is the speed cache for the assignment loop.

---

## Build Order (Optimized for Shippable Demo at Every Checkpoint)

This is the most important section. Each checkpoint produces a working, demoable artifact. If you stop at any checkpoint, you have *something* to show.

### Checkpoint 0: Skeleton (1-2hr)
- `npm create vite@latest`, `pip install fastapi uvicorn sse-starlette aiosqlite numpy haversine`
- `app.py` with `/health` and a hardcoded `/clips` returning a fake clip_id
- React with two views (Recorder, Feed) wired to a router
- **Demo-able:** "Here's the shell"

### Checkpoint 1: Capture + Playback (3-4hr) ← FIRST DEMO-CAPABLE SLICE
- MediaRecorder in Recorder.tsx, GPS via `navigator.geolocation`, POST as multipart
- `/clips` writes file to disk + SQLite row
- Feed.tsx polls `/feed` every 3 seconds and renders raw clip URLs in a `<video>` grid
- **Demo-able:** "Record on phone, see it appear in the feed." This is the floor — if everything else fails, we have this.

### Checkpoint 2: Marengo Embedding (3-4hr)
- `pipeline/embed.py` with `twelvelabs.TwelveLabs(api_key=...)`, `client.embed.task.create(model_name="Marengo-retrieval-3.0", video_file=path)`, polling
- Store vectors in SQLite `clip_embeddings` table
- Add embedding status to `/clips` response and feed
- **Demo-able:** "Each clip gets a 512-d multimodal embedding from Marengo 3.0" (show table)

### Checkpoint 3: Clustering + Debug Overlay (4-5hr) ← THE MAGIC MOMENT
- `pipeline/cluster.py` with composite score + threshold
- Seed script that replays 3-4 staged clips on startup
- Debug.tsx overlay showing per-clip score breakdown (visual / GPS / time / composite)
- Feed groups clips by cluster
- **Demo-able:** "Here's the staged event clustered correctly with score breakdown." **This is the pitch.** Even if everything past this fails, we have the load-bearing demo.

### Checkpoint 4: Multi-Agent Compile (4-5hr)
- `pipeline/compile.py` with the four `AgentDefinition` subagents
- Custom tools: `get_cluster_clips`, `get_clip_metadata`, `save_segment`
- Trigger on cluster size ≥ 2 with debounce
- Render compiled segments (headline + caption + ordered clips) in feed
- **Demo-able:** "Four agents collaborate to produce a finished segment" — full Best Use of AI narrative

### Checkpoint 5: SSE + Real-Time Feed (2-3hr)
- Replace 3s feed polling with EventSource
- Broadcast on each pipeline transition
- Feed updates live as clips arrive and compile completes
- **Demo-able:** "Watch the feed update in real time as we submit clips"

### Checkpoint 6: Polish (remaining time)
- Proximity-based feed sort (haversine from viewer GPS to cluster centroid)
- Recency decay
- Demo dataset replay button on Debug view ("Replay Staged Event")
- Pre-warm Marengo with one clip on startup so the first demo embed is fast
- Loading states, error toasts, dark mode

### Why this order

- **Capture + raw playback first** because it's the visible "this is a real product" moment. Even with no AI, you can show video flowing end-to-end.
- **Marengo before clustering** because clustering depends on it; doing them in the wrong order means you implement clustering against fake vectors first, which is wasted code.
- **Debug overlay alongside clustering, not after,** because the debug overlay IS the pitch. "Show the scores" is what makes the magic legible.
- **Compile pipeline AFTER clustering works** because if clustering is broken the compile output is gibberish and you'll waste time debugging the wrong layer.
- **SSE last among core features** because polling at 3s is fine for demos. Real-time is polish, not core.

---

## Demo Robustness Strategy (Graceful Degradation)

Every external dependency can fail. Build a degradation ladder:

| Layer | If it fails | Demo still works because |
|-------|-------------|--------------------------|
| WiFi entirely | Show pre-recorded screencast as backup | Have one ready |
| Twelve Labs API | Cached embeddings for staged clips loaded from `seed/embeddings.json` at startup | Pre-compute and ship them |
| Anthropic API | Cached compile output for staged cluster loaded from `seed/segment.json` | Pre-compute and ship it |
| Clustering threshold mis-tunes | Debug overlay shows scores anyway; pivot pitch to "the scores are the demo" | Honest framing |
| Compile pipeline 502s mid-demo | Feed still shows clustered clips; segment fails gracefully with "compiling..." | Pipeline error never blocks feed |
| Live capture fails (judge's phone won't grant camera) | "Replay Staged Event" button on Debug view re-injects pre-recorded clips | Always have the button |
| FastAPI process crashes | `uvicorn --reload` auto-restarts; clips on disk persist; clusters rebuild from SQLite at startup | Idempotent startup |

### Concrete robustness tactics

1. **Pre-warm everything.** On FastAPI startup: hit Marengo with one tiny clip to warm the connection, hit Anthropic with a 1-token query to warm that connection. The first real demo call should never be the cold-start call.

2. **Cache the demo path.** The 3-4 staged clips are deterministic. After your first successful run, save their embeddings + the compiled segment to disk. On startup, if cached results exist, prefer them. The demo path becomes "load from disk" with the API as a fallback for live additions.

3. **Idempotent pipeline.** Every stage checks `if already_done: skip`. Re-running `run_pipeline(clip_id)` should be a no-op if the work completed. This makes "panic, restart server, re-fire" a viable mid-demo recovery.

4. **Feed never blocks on compile.** Feed shows clusters with status `compiling | published | failed`. A failed compile shows the raw clipped clips with "compile failed, retrying..." Don't gate the feed on AI output.

5. **The Debug overlay is your judge-facing receipts.** If something breaks, pivot to "let me show you what's happening under the hood" — the overlay's score table is more impressive than any compiled segment.

6. **Single `make demo` command.** One entry point that starts FastAPI + Vite + seeds the DB + opens the browser. The fewer commands you remember at demo time, the less can go wrong.

---

## Anti-Patterns

### Anti-Pattern 1: Microservices for the Pipeline

**What people do:** Split embed, cluster, compile into separate FastAPI services with HTTP-between-them or message queues.
**Why it's wrong:** 3x the deploy surface, 3x the failure modes, and the in-memory cluster index becomes a distributed-state nightmare. At hackathon scale, this is pure cost.
**Do this instead:** One monolith, asyncio coroutines for the pipeline. Components are *modules*, not services.

### Anti-Pattern 2: Real Vector DB at this Scale

**What people do:** Spin up Qdrant or Pinecone "for the embeddings."
**Why it's wrong:** Adds a service to manage, network latency on every cluster assignment, and irrelevant features (HNSW indexing) for N < 1000 vectors. Brute-force NumPy is faster.
**Do this instead:** Store vectors in SQLite BLOBs, hold active cluster centroids in memory, do brute-force cosine in NumPy.

### Anti-Pattern 3: Live Streaming the Camera

**What people do:** WebRTC, HLS, "let users go live."
**Why it's wrong:** Hours of fiddly browser/STUN/TURN/codec work, none of which adds to the multi-angle clustering pitch. Out of scope per PROJECT.md.
**Do this instead:** MediaRecorder records to a Blob, POST as a normal multipart upload. Done in 30 lines.

### Anti-Pattern 4: One Mega-Prompt Compile

**What people do:** Send the cluster's metadata to one Claude call with a giant prompt asking for headline + caption + clip ordering all at once.
**Why it's wrong:** Loses the multi-agent narrative that's load-bearing for the Best Use of AI track. Also, one massive prompt is harder to debug than four focused ones.
**Do this instead:** Four subagents via Claude Agent SDK as shown in Pattern 3. The narrative IS the differentiator.

### Anti-Pattern 5: User Auth "Just for the Demo"

**What people do:** Add a quick username field "to track who uploaded what."
**Why it's wrong:** Anonymity is load-bearing per PROJECT.md. Adding even an optional name field signals to judges that the founders don't actually believe their own thesis.
**Do this instead:** No accounts. Period. Random clip IDs. The pitch hangs on this.

### Anti-Pattern 6: WebSocket for One-Way Updates

**What people do:** Reach for socket.io because "we need real-time."
**Why it's wrong:** WebSockets are bidirectional and stateful. SSE is server→client only, has native browser support, and is half the code. Newz never needs the client to push mid-session (uploads are separate POSTs).
**Do this instead:** SSE via `sse-starlette` and `EventSource`. See Pattern 4.

### Anti-Pattern 7: Skipping the Pre-Recorded Demo Path

**What people do:** "We'll just record live in front of judges, it's more impressive."
**Why it's wrong:** Live demo failures are the #1 hackathon loss mode. Cameras won't get permissions, networks fail, embeddings take longer than expected.
**Do this instead:** Pre-recorded staged clips are the canonical demo path. Live recording is a *bonus* if everything is going well, not the primary moment.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes / Gotchas |
|---------|---------------------|-----------------|
| Twelve Labs Marengo 3.0 | `twelvelabs` Python SDK, `embed.task.create(model_name="Marengo-retrieval-3.0", video_file=path)`, `task.wait_for_done(sleep_interval=2)`, `task.retrieve(task.id)` | 512-d vectors (3.0); 1024-d if you accidentally request 2.7. Async polling can take 5-30s per clip. Pre-warm with a dummy clip on startup. Webhooks exist but are not worth the ngrok overhead for the hackathon. |
| Anthropic Claude Agent SDK | `claude_agent_sdk.query()` with `ClaudeAgentOptions(agents={...}, mcp_servers={...}, allowed_tools=["Agent", "mcp__newz_tools__*"])` | The `Agent` tool MUST be in `allowed_tools` for subagents to be invokable. Subagents cannot spawn their own subagents. State passes only through the orchestrator's prompt construction. Use `model="haiku"` on the Publisher agent for cost — it's just a tool call. |
| Browser MediaRecorder | `new MediaRecorder(stream, {mimeType: "video/webm;codecs=vp9"})` → `recorder.ondataavailable` → Blob → multipart POST | iOS Safari support is partial (mp4/h264 fallback). For demo on Mac/PC Chrome, VP9/WebM is fine. Cap recording at 15s for sane upload sizes. |
| Browser Geolocation | `navigator.geolocation.getCurrentPosition(success, error, {enableHighAccuracy: true, timeout: 5000})` | Requires HTTPS or `localhost`. Ngrok or `localhost.run` for mobile demo. Have a manual lat/lng input as a fallback. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| HTTP routes ↔ pipeline | `asyncio.create_task(run_pipeline(clip_id))` — fire-and-forget | Routes return immediately; pipeline owns its lifecycle |
| Pipeline stages | Direct `await` calls between `embed → cluster → compile` modules | Each stage idempotent; safe to re-run |
| Pipeline ↔ frontend | SSE event broadcasts via shared `events.broadcast()` | One-way, async, lossy on disconnect (acceptable) |
| Pipeline ↔ DB | `aiosqlite` connection per request/task; no pooling needed at this scale | WAL mode handles concurrent readers |
| Agents ↔ DB | Agents call custom tools (`get_cluster_clips`, `save_segment`) which call DB | Tools are the *only* way agents touch state |

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-100 clips/day (demo + post-hackathon) | Current architecture — single FastAPI process, SQLite, in-memory clusters |
| 100-10k clips/day (small launch) | Move clip storage to S3/R2, swap SQLite for Postgres, add Redis for SSE pubsub across multiple workers, batch nightly recluster job for cluster cleanup |
| 10k+ clips/day | Vector DB (Qdrant/Pinecone) for embedding search, separate compile worker pool, CDN for clip delivery, geospatial index for proximity queries (PostGIS or Redis GEO) |

### Scaling Priorities (post-hackathon)

1. **First bottleneck: clip storage on local FS.** Move to S3/R2 the moment you have a second machine. ~30 lines of code.
2. **Second bottleneck: Marengo cost + latency.** Batch embeddings; use webhooks instead of polling; consider a smaller embedding model for negative cases.
3. **Third bottleneck: cluster index in memory.** When `len(active_clusters) > ~5000`, add an HNSW index (faiss or qdrant) with a sliding "active window" of the last 24hr of clusters.
4. **Fourth bottleneck: compile cost.** Cache compiled segments aggressively; only re-compile when a cluster gains a clip that materially changes the score breakdown.

For the hackathon: **none of this matters.** Single laptop. Single process. Don't over-engineer.

---

## Sources

- **Twelve Labs Marengo 3.0 docs** (HIGH confidence): [Marengo 3.0 release blog](https://www.twelvelabs.io/blog/marengo-3-0), [Embed API guide](https://docs.twelvelabs.io/docs/guides/create-embeddings/video), [Twelve Labs + Qdrant Python example](https://qdrant.tech/documentation/embeddings/twelvelabs/) — confirms 512-d vectors, async embed task lifecycle (`task.create` → `wait_for_done` → `retrieve`), segment-level vector output.
- **Claude Agent SDK** (HIGH confidence): [Subagents in the SDK](https://code.claude.com/docs/en/agent-sdk/subagents), [Custom tools](https://platform.claude.com/docs/en/agent-sdk/custom-tools), [Agent SDK Python reference](https://code.claude.com/docs/en/agent-sdk/python) — confirms `agents={...}` parameter, `Agent` tool requirement, subagent context isolation, custom tools via `@tool` + `create_sdk_mcp_server`.
- **FastAPI background patterns** (HIGH confidence): [FastAPI BackgroundTasks docs](https://fastapi.tiangolo.com/tutorial/background-tasks/), [Comparison with Celery](https://medium.com/@komalbaparmar007/fastapi-background-tasks-vs-celery-vs-arq-picking-the-right-asynchronous-workhorse-b6e0478ecf4a) — confirms `asyncio.create_task` is the correct primitive for true fire-and-forget vs. `BackgroundTasks` (which can block) vs. Celery (overkill for single-process).
- **SSE with FastAPI + React** (HIGH confidence): [FastAPI SSE docs](https://fastapi.tiangolo.com/tutorial/server-sent-events/), [SSE with FastAPI and React tutorial](https://www.softgrade.org/sse-with-fastapi-react-langgraph/) — confirms `sse-starlette`'s `EventSourceResponse` pattern and React `EventSource` integration.
- **Geospatial distance** (HIGH confidence): [Haversine PyPI](https://pypi.org/project/haversine/) — confirms `haversine` package API and accuracy for hyperlocal (<1km) distances.
- **Online clustering with cosine similarity** (MEDIUM confidence): [Links Online Clustering algorithm](https://github.com/QEDan/links_clustering), [Incremental spectral clustering paper](https://ieeexplore.ieee.org/document/10411707/) — confirms single-pass cluster assignment with composite score is a standard pattern at small scale; weights are domain-specific and must be empirically validated against the staged demo dataset.

---
*Architecture research for: Newz hackathon MVP*
*Researched: 2026-04-24*
