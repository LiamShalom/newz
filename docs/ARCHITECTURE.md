<!-- generated-by: gsd-doc-writer -->
# Architecture

How Newz turns anonymous crowdsourced clips into compiled news segments. For project vision, scope decisions, and out-of-scope reasoning see [`.planning/PROJECT.md`](../.planning/PROJECT.md). For day-to-day project context see [CLAUDE.md](../CLAUDE.md). For iOS Safari hardware verification see [docs/IPHONE-GATE.md](./IPHONE-GATE.md).

## Overview

Two sibling apps, one event-driven hot path:

```
iPhone Safari (frontend)
    │  POST /clips (multipart: blob, lat, lng, ts)
    ▼
FastAPI single-process monolith (backend)
    │  202 Accepted → asyncio.create_task(run_pipeline)
    ├── embed   (Marengo 3.0, 512-d, native 3s segmentation)
    ├── cluster (composite score: 0.55*cos + 0.30*gps + 0.15*time)
    └── compile (4-agent Claude SDK + ffmpeg stitch + vision caption, 60s cap)
    │
    └── SSE /events fan-out → Feed re-fetches GET /feed
```

No queues, no broker, no worker pool. Stages chain via `asyncio.create_task`. SQLite + local FS persist everything; an in-memory `CLUSTERS` dict caches active clusters and is rebuilt from sqlite on lifespan startup.

## Stack

| Layer        | Choice                                                                |
| ------------ | --------------------------------------------------------------------- |
| Frontend     | React 18 + Vite + TypeScript + Tailwind 4 → Vercel                    |
| Backend      | FastAPI 0.115 + Uvicorn (Python 3.11) → Railway w/ persistent volume  |
| Video AI     | Twelve Labs `marengo3.0` via `twelvelabs==1.2.3` (512-d fused vec)    |
| Multi-agent  | `claude-agent-sdk==0.1.68` (bundles CLI binary, no Node on backend)   |
| Storage      | aiosqlite (WAL) + local FS (`${DATA_DIR}/clips/`)                     |
| Vector search| NumPy in-memory cosine over normalized 512-d unit vectors             |
| Realtime     | `sse-starlette==2.1.3` server-sent events; native browser `EventSource`|
| Video I/O    | `ffmpeg-python` + `imageio-ffmpeg` (bundled binary; no system ffmpeg) |

No Postgres, no Redis, no Celery, no Pinecone, no S3. Hackathon scale.

## Pipeline

`backend/pipeline/run.py:30 run_pipeline(clip_id)` is the fire-and-forget background coroutine kicked off from `backend/app.py:125` after every `POST /clips`. Three stages:

### 1. Embed — `backend/pipeline/embed.py`

- `embed_worker` (`embed.py:135`) reads the clip path from sqlite, runs `_sync_embed` in a thread-pool executor (`run_in_executor`) so Marengo's 5-30s latency never blocks the event loop.
- Real path: `_call_marengo` (`embed.py:47`) calls `client.assets.create()` then `client.embed.v_2.create()` with `model_name="marengo3.0"`, `embedding_scope=["clip","asset"]`, and `VideoSegmentation_Fixed(duration_sec=3)` — Marengo's native segmentation produces one parent (`asset`) vector + N child (`clip`) vectors at 3s granularity. Tenacity retries 3x with exponential backoff.
- Mock path: `USE_MOCK_EMBEDDINGS=true` → `_mock_embedding` (`embed.py:32`) returns a deterministic 512-d unit vector keyed by `clip_id`. Three fake children at 0-3s, 3-6s, 6-9s.
- Persistence: parent embedding stored under the parent `clip_id`; each child gets a row in `clips` (via `db.insert_child_clip`) with `parent_id`, `start_offset_sec`, `end_offset_sec`, and its own embedding row. Children — not the parent — are what flows into clustering.
- Pre-warm: `_pre_warm_marengo` (`app.py:23`) fires once at lifespan startup against `seed/prewarm.mp4` so the first real clip doesn't pay cold-start latency.

### 2. Cluster — `backend/pipeline/cluster.py`

- `cluster_worker(clip_id, vec)` (`cluster.py:125`) runs once per child (or once for the parent if the clip was too short to segment). Returns the joined or newly-created `cluster_id`.
- Math is locked: `composite = 0.55*cos + 0.30*gps_proximity + 0.15*time_proximity` (`cluster.py:41-45`). GPS proximity = `max(0, 1 - dist_m/200)`; time proximity = `max(0, 1 - dt_s/600)`. When GPS is unavailable on either side, `gps` collapses to `0.0` (un-renormalized — visual still has to win on its own).
- Two gates per join (`cluster.py:143-148`):
  1. **Visual floor** (`config.VISUAL_FLOOR`, default `0.80`) — a clip is ineligible to join a cluster unless its cosine to that cluster's centroid clears the floor. Without this, GPS+time alone contribute 0.45 to composite and any visual cosine > 0.18 would clear the 0.55 threshold, fusing adversarial clips. The floor makes "AI sees the same scene" the dominant gate (CLU-08).
  2. **Composite threshold** (`config.CLUSTER_THRESHOLD`, default `0.55`) — the eligible best cluster must clear this to join; otherwise create a new cluster.
- All scoring + mutation runs inside `_LOCK: asyncio.Lock` (`cluster.py:69, 136`) — serializes the score-and-mutate critical section. SSE broadcast happens **outside** the lock (`cluster.py:197`).
- Centroid update: Welford running mean in float64, re-normalized to unit length, stored as float32 (`cluster.py:86`).
- In-memory cache `CLUSTERS: dict[str, ClusterCache]` (`cluster.py:68`) holds active clusters; `rebuild_cache()` (`cluster.py:227`) repopulates it from sqlite at lifespan startup before the server accepts work (CLU-10).
- The `cluster_assigned` SSE event includes the full `score_breakdown` (visual / gps / time / composite / threshold) — this powers the debug overlay and is the **pitch demo**.

### 3. Compile — `backend/pipeline/compile.py`

Triggered when a cluster crosses `member_count >= 2` (`run.py:20 _should_compile`). `db.set_compile_in_flight` is a CAS with 30s TTL — only one compile per cluster per upload batch (CMP-09).

`compile_segment(cluster_id)` (`compile.py:339`) runs three tracks in parallel under a single `asyncio.wait_for(timeout=60.0)` cap (`compile.py:384`):

- **Track A — `_run_agents`** (`compile.py:297`)
  - First, `_run_caption_writer_with_vision` (`compile.py:209`): direct top-level `query()` with image content blocks. Why not a subagent? Per the docstring: claude-agent-sdk 0.1.68 does not propagate image content from MCP tool returns into a subagent's vision context, so keyframes are pre-extracted in Python (`extract_cluster_keyframes` → midpoint frame per clip via `imageio-ffmpeg`, scaled to 512px long edge) and inlined into the user message as base64 image blocks. Returns `{caption, location}`.
  - Then `_run_orchestrator_chain` (`compile.py:256`) runs three subagents in series: **angle-selector** (Sonnet) → **editor** (Sonnet) → **publisher** (Haiku). Defined in `AGENTS` (`compile.py:83`). MCP tools (`backend/pipeline/compile_tools.py`): `get_cluster_clips`, `get_clip_metadata`, `save_segment`. The `save_segment` tool is the ONLY write path — only Publisher is allowed to call it (CMP-03).
- **Track B — `stitch_clips`** (`backend/pipeline/stitch.py:57`): ffmpeg concat demuxer over the selected child slices (`inpoint`/`outpoint` per ref) → `${DATA_DIR}/clips/{cluster_id}_compiled.webm` (libvpx-vp9 + libopus). Falls back to first clip's path on any failure — never raises.
- **Track C — `generate_caption`** (`backend/pipeline/caption_pipeline.py`): frame-based visual caption — picks 2-3 children closest to centroid by cosine, extracts 3 JPEGs each, sends to Haiku for per-clip descriptions, aggregates to Sonnet for an AP-wire headline. Returns `{caption, location}`. Never raises.

After the gather, `compile_segment` calls `db.insert_segment` again (idempotent ON CONFLICT) to update `video_url` (Track B) and overwrite the caption with Track C's vision caption when present.

Failure paths: `asyncio.TimeoutError` (60s cap), agent track exception, or Publisher never calling `save_segment` → `_save_fallback_segment` (`compile.py:317`) writes a generic AP-wire-style caption with chronological clip ordering. Idempotent — won't overwrite an existing segment row.

## Data flow

A typical clip's journey, end to end:

1. iPhone Safari posts to `POST /clips` (`app.py:105`) with multipart `file`, `lat`, `lng`, `ts`, `X-Session-Id` header.
2. `db.insert_clip` writes the file to `${DATA_DIR}/clips/{id}.{ext}` and inserts a `clips` row. Server returns `202` with `{clip_id, status: "processing"}`.
3. SSE broadcast: `clip_added`. `asyncio.create_task(run_pipeline(clip_id))` fires.
4. `embed_worker` runs in thread pool; persists parent + child embeddings as float32 BLOBs in `clip_embeddings`. SSE: `pipeline_progress { stage: "embedded" }`.
5. For each child, `cluster_worker` joins or creates a cluster (in-memory + sqlite). SSE: `cluster_assigned` with full score breakdown. Then `pipeline_progress { stage: "clustered" }`.
6. If any cluster crossed `member_count >= 2` and the CAS succeeds, `compile_segment` fires. SSE: `compile_started`.
7. After ≤60s, segment row written. SSE: `segment_published`.
8. Frontend `useEventSource` (`frontend/src/hooks/useEventSource.ts:15`) catches `segment_published` or `cluster_assigned` and re-fetches `GET /feed` (`frontend/src/views/Feed.tsx:58`).
9. `GET /feed` (`app.py:138`) sorts by haversine proximity to viewer + recency (FED-01) when `lat`/`lng` are passed; falls back to recency only.

## Storage

SQLite at `${DATA_DIR}/newz.db`, opened with `PRAGMA journal_mode=WAL, synchronous=NORMAL` (`db.py:70-71`). On Railway, `DATA_DIR=/data` is a mounted persistent volume — without it, redeploys wipe uploaded clips.

Tables (`db.py:18`):

| Table             | Purpose                                                                       |
| ----------------- | ----------------------------------------------------------------------------- |
| `clips`           | Parent clips + child sub-clips (parent_id self-reference for 3s segmentation).|
| `clip_embeddings` | 512-d float32 vector BLOB per clip/child + Marengo latency_ms.                |
| `clusters`        | Active cluster centroids, GPS centroid, median_ts, member_count, compile CAS columns. |
| `segments`        | Compiled segments — `ordered_clip_ids` (JSON), `caption`, `location`, `video_url`. |

Schema migrations are PRAGMA-checked in `db.init()` (`db.py:73-100`) — SQLite has no `ADD COLUMN IF NOT EXISTS`. Phase 4 added `compile_in_flight`/`last_compile_at` to `clusters`; Phase 4.5 added `parent_id`/`start_offset_sec`/`end_offset_sec` to `clips`.

Clips are served via `app.mount("/media", StaticFiles(...))` (`app.py:93`).

## Real-time (SSE)

`backend/events.py` is a 35-line in-process pub/sub: `_subscribers: list[asyncio.Queue]` with `maxsize=64`. Slow consumers drop events on `QueueFull` rather than blocking the publisher.

- `GET /events` (`app.py:155`) returns an `EventSourceResponse` with 15s ping interval. Polls subscriber queue with 1s timeout to honor disconnects.
- `useEventSource` hook (`frontend/src/hooks/useEventSource.ts`) opens **one** EventSource on Feed mount. HTTP/1.1 caps the browser at 6 connections per origin — only Feed.tsx mounts it.

Event types (discriminated union in `frontend/src/types.ts:77`): `clip_added`, `pipeline_progress`, `cluster_assigned`, `compile_started`, `segment_published`, `pipeline_error`. Errors are scrubbed of `TWELVELABS_API_KEY` before broadcast (`run.py:12 _scrub`).

## Deployment topology

Two services, one origin pair, talking via CORS.

```
Vercel (HTTPS)                Railway (HTTPS)
┌─────────────────┐           ┌────────────────────────────┐
│ frontend/       │ ────────► │ backend/Dockerfile         │
│ Vite SPA build  │  CORS     │ python:3.11-slim + ffmpeg  │
│ /index.html SPA │           │ uvicorn backend.app:app    │
│ rewrites        │           │ healthcheck: GET /health   │
└─────────────────┘           │ Volume: /data (persistent) │
                              └────────────────────────────┘
```

- **Frontend**: `frontend/vercel.json` defines `pnpm install --frozen-lockfile && pnpm build`, output `dist/`, SPA rewrite `/(.*) → /index.html`. Build-time `VITE_API_BASE` baked into bundle (`frontend/src/api.ts:7`).
- **Backend**: `backend/Dockerfile` installs ffmpeg + requirements.txt, binds `0.0.0.0:${PORT}`. `backend/railway.toml` declares Dockerfile builder + `/health` healthcheck (30s timeout, restart on failure max 5). `DATA_DIR=/data` mount path is mandatory; without it clips disappear on redeploy.
- **CORS**: `app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_URL, "http://localhost:5173"])` (`app.py:83`). Both origins allowed simultaneously so dev and prod work without a redeploy.
- **Pre-warm**: lifespan fires `_pre_warm_marengo` and `_pre_warm_sdk` in parallel as fire-and-forget tasks (`app.py:76-77`) — startup never blocks on them. SDK pre-warm is skipped when `OFFLINE_DEMO=true` or `ANTHROPIC_API_KEY` unset.
- **Demo seed**: `seed_demo_segment()` (`backend/seed/demo_segment.py`) inserts a staged segment if `segments` is empty — `OFFLINE_DEMO=true` serves cached embeddings + cached compile output without external API calls (Tier-5 fallback for hackathon WiFi failure).

Setup and CORS sanity check: see [README.md](../README.md). iPhone hardware gate: see [docs/IPHONE-GATE.md](./IPHONE-GATE.md).

## Out of scope

Live streaming, accounts/login, likes/comments, user-authored captions, content moderation, native iOS app, in-app editing, map view, national feed, Pinecone/Qdrant, Redis/Celery, server-side transcoding. Full reasoning + requirement IDs in [`.planning/PROJECT.md`](../.planning/PROJECT.md) and [`.planning/REQUIREMENTS.md`](../.planning/REQUIREMENTS.md) "Out of Scope" tables.
