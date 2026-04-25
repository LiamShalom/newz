# Architecture

**Analysis Date:** 2026-04-24

## Pattern Overview

**Overall:** Single-process FastAPI monolith with asyncio-chained background pipeline

**Key Characteristics:**
- All backend logic runs in one `uvicorn` process — no Redis, no Celery, no Docker Compose
- HTTP handlers return immediately (202); all AI work happens via `asyncio.create_task` after the response
- Server-sent events (SSE) push pipeline state changes to connected React clients in real time
- In-memory cluster index backed by SQLite — rebuilt on startup, no external store

## Layers

**Frontend (React SPA):**
- Purpose: Camera capture, feed rendering, debug overlay
- Location: `frontend/src/`
- Contains: Three view components (`Recorder.tsx`, `Feed.tsx`, `Debug.tsx`), API fetch wrapper (`api.ts`), SSE hook (`sse.ts`), root entry (`App.tsx`)
- Depends on: Backend HTTP API via Vite proxy (`/api → :8000`)
- Used by: End users via browser (iOS Safari primary target)

**HTTP Layer (FastAPI routes):**
- Purpose: Accept uploads, serve feed, stream events, expose debug data
- Location: `backend/app.py`
- Contains: `POST /clips` (202 ingest), `GET /feed`, `GET /events` (SSE), `GET /clusters/:id` (debug)
- Depends on: `db.py`, `events.py`, `pipeline/` modules
- Used by: Frontend

**Background Pipeline (asyncio coroutines):**
- Purpose: Embed → cluster → compile in the background without blocking HTTP
- Location: `backend/pipeline/`
- Contains: `embed.py` (Marengo wrapper), `cluster.py` (composite-score clustering), `compile.py` (Claude Agent SDK 4-subagent pipeline), `tools.py` (@tool functions for agents)
- Depends on: External APIs (Twelve Labs, Anthropic), `db.py`, `events.py`
- Used by: `app.py` via `asyncio.create_task(run_pipeline(clip_id))`

**Event Bus:**
- Purpose: Broadcast pipeline state changes to all connected SSE clients
- Location: `backend/events.py`
- Contains: `asyncio.Queue` per connected client, `broadcast()` function
- Depends on: Nothing (pure asyncio primitives)
- Used by: Pipeline stages, HTTP layer SSE endpoint

**Storage Layer:**
- Purpose: Persist clips and metadata durably
- Location: `backend/db.py` (schema/helpers), `clips/` directory (files), `newz.db` (SQLite)
- Contains: SQLite tables (clips, embeddings, clusters, segments), in-memory `active_clusters` list
- Depends on: `aiosqlite`, local filesystem at `/data` (Railway persistent volume)
- Used by: All pipeline stages and HTTP handlers

**Seed / Demo Layer:**
- Purpose: Pre-recorded staged dataset for demo fallback; pre-computed embeddings for `OFFLINE_DEMO`
- Location: `backend/seed/`
- Contains: `demo_clips/` (3-4 `.webm`/`.mp4` files), `seed.py` (replay script)
- Depends on: `pipeline/`, `db.py`
- Used by: Backend startup lifespan, "Replay Staged Event" button endpoint

## Data Flow

**Hot Path (clip ingest → feed tile):**

1. User stops recording → `MediaRecorder` produces Blob + GPS + timestamp
2. `Recorder.tsx` POSTs multipart to `POST /clips`
3. FastAPI handler writes file to `/data/clips/{clip_id}.{ext}`, inserts SQLite row, broadcasts `clip_added` via SSE
4. Handler returns 202 `{clip_id, status: "processing"}` — user sees "uploaded" immediately
5. `asyncio.create_task(run_pipeline(clip_id))` fires in background
6. `embed.generate(clip_id)`: calls Twelve Labs `marengo3.0`, polls until done (~5–15s), stores 512-d vector as SQLite BLOB
7. `cluster.assign_or_create(clip_id, embedding)`: computes composite score vs. all in-memory cluster centroids, assigns or creates; broadcasts `cluster_updated`
8. `cluster.should_compile(cluster_id)`: True if size >= 2 AND no compile in-flight AND (just hit threshold OR 30s since last arrival)
9. `compile.run(cluster_id)`: 4-subagent Claude Agent SDK pipeline produces segment; broadcasts `segment_published`
10. Frontend SSE handler receives `segment_published` → refetches `GET /feed` → feed re-renders new tile at top

**Feed Query (read path):**

1. `Feed.tsx` calls `GET /feed?lat&lng`
2. FastAPI queries SQLite: `SELECT segments JOIN clusters`
3. Ranks by `haversine(viewer_gps, cluster_centroid) * weight + recency_decay`
4. Returns ordered JSON; no AI in this path

**Real-Time Update Path:**

1. Any pipeline transition calls `events.broadcast({type, ...payload})`
2. `broadcast()` puts event into every connected client's `asyncio.Queue`
3. SSE generator yields `{"data": json}` to client
4. `EventSource.onmessage` in `sse.ts` dispatches to React state update

**Debug Overlay Path:**

1. User clicks cluster → `GET /clusters/:id`
2. FastAPI returns cluster + member clips + per-clip score breakdown (Marengo cosine, GPS distance m, timestamp delta s)
3. `Debug.tsx` renders bar chart of scores

**State Management:**

- Server: SQLite (durable) + in-memory `active_clusters` list (rebuilt from SQLite at startup)
- Frontend: Per-view React state — no global store. `Recorder` holds `{recording, lastClipId}`, `Feed` holds `{segments}`, `Debug` holds `{selectedClusterId, scores}`

## Key Abstractions

**`run_pipeline(clip_id)`:**
- Purpose: The chained background coroutine that runs all three pipeline stages
- Location: `backend/app.py`
- Pattern: `await embed → await cluster → optional await compile`, each stage broadcasting SSE events; wrapped in `try/except` that broadcasts `pipeline_error` on failure

**Composite Clustering Score:**
- Purpose: Single number determining whether a new clip joins an existing cluster
- Location: `backend/pipeline/cluster.py`
- Pattern: `score = 0.55 * visual_score + 0.30 * gps_score + 0.15 * time_score`; threshold `0.55` (env var `CLUSTER_THRESHOLD`); GPS weight collapses to 0 when geolocation unavailable

**Claude Agent SDK 4-Subagent Pipeline:**
- Purpose: Turn a cluster into a published news segment
- Location: `backend/pipeline/compile.py`
- Pattern: Single `query()` call with `agents=AGENTS` dict; orchestrator prompt instructs sequential invocation of Angle Selector → Editor → Caption Writer → Publisher; subagents do not share memory, only the orchestrator loop does

**SSE Event Bus:**
- Purpose: Decouple pipeline stages from connected clients
- Location: `backend/events.py`
- Pattern: `asyncio.Queue` per client appended on SSE connect, removed on disconnect; `broadcast()` puts to all queues; generator yields until disconnect

## Entry Points

**Backend:**
- Location: `backend/app.py`
- Triggers: `uvicorn backend.app:app`
- Responsibilities: Route registration, FastAPI lifespan (DB init, Marengo pre-warm, seed replay), route handlers that fire `asyncio.create_task`

**Frontend:**
- Location: `frontend/src/App.tsx`
- Triggers: Vite dev server or Vercel CDN load
- Responsibilities: React Router setup (two routes: `/` → `Feed.tsx`, `/record` → `Recorder.tsx`), global SSE connection via `sse.ts`

**Demo Seed:**
- Location: `backend/seed/seed.py`
- Triggers: Called during FastAPI lifespan on startup (or via "Replay Staged Event" endpoint)
- Responsibilities: POSTs pre-recorded clips through the pipeline to pre-populate the DB; with `OFFLINE_DEMO=true` serves cached embeddings + cached compile output instead

## Error Handling

**Strategy:** Catch-and-broadcast — pipeline exceptions are caught at the `run_pipeline` level and broadcast as `pipeline_error` SSE events; the UI degrades gracefully (clip stays visible even if clustering/compile fails)

**Patterns:**
- `POST /clips` never fails due to pipeline errors — file write and 202 are the success condition
- `compile.run()` has a 30-second wall-clock hard cap via `asyncio.wait_for`; on `TimeoutError`, fallback to default clip ordering + generic caption
- GPS unavailable: `gps_score` returns 0 and `W_GPS` collapses to 0 so visual similarity carries the cluster
- `OFFLINE_DEMO=true`: embed and compile workers skip external API calls and serve cached responses from `backend/seed/`

## Cross-Cutting Concerns

**Logging:** `log.exception()` in pipeline error handler; embed worker logs latency per call (visible in debug overlay)

**Validation:** Pydantic v2 models in `backend/models.py` for `Clip`, `Cluster`, `Segment`, `ScoreBreakdown`; FastAPI request validation on all route inputs

**Authentication:** None — anonymity is load-bearing. Anonymous session UUID in `localStorage` only, never sent to server as identity

**OFFLINE_DEMO flag:** `OFFLINE_DEMO=true` env var gates all external API calls; embed worker returns cached vectors, compile worker returns cached segment; checked in `backend/config.py`

**MIME ladder (iOS Safari):** `Recorder.tsx` tries `video/mp4;codecs=avc1` → `video/webm;codecs=vp9` → `video/webm` → no mimeType before constructing `MediaRecorder`

---

*Architecture analysis: 2026-04-24*
