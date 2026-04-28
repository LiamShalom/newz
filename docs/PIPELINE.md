# Ingestion Pipeline — User Video → Multi-Angle News Segment

How a 30-second iPhone Safari recording becomes a published, multi-angle news segment in the feed. This doc maps the full hot path against the live code, stage by stage. For high-level architecture see [ARCHITECTURE.md](./ARCHITECTURE.md); for project scope see [`.planning/PROJECT.md`](../.planning/PROJECT.md).

## End-to-end flow

```
iPhone Safari                 FastAPI single process                   Browser feed
─────────────                 ──────────────────────                  ─────────────
recorder.tsx                  POST /clips  ──► insert_clip            (subscribed via
  capture (MIME ladder)         │             + write file              EventSource to
  + GPS (blocking)              │             + SSE: clip_added         /events)
  + 5–30s blob          ──►   202 Accepted     │
                                │             asyncio.create_task(run_pipeline)
                                │                  │
                                │   ┌──────────────┴──────────────────────┐
                                │   │ embed_worker (Marengo 3.0)          │
                                │   │   parent (asset-scope, 512-d)       │
                                │   │   + N child rows (clip-scope, 3s)   │  SSE: pipeline_progress
                                │   │   store_embedding for each         │  (stage="embedded")
                                │   ├─────────────────────────────────────┤
                                │   │ cluster_worker (parent vec only)    │
                                │   │   composite = 0.55·cos              │  SSE: cluster_assigned
                                │   │             + 0.30·gps              │  (+ score breakdown)
                                │   │             + 0.15·time             │
                                │   │   join (≥0.70) or new cluster       │
                                │   ├─────────────────────────────────────┤
                                │   │ _should_compile gate                │
                                │   │   skip unless ≥2 distinct parents   │
                                │   │   CAS-acquire compile_in_flight     │
                                │   ├─────────────────────────────────────┤
                                │   │ compile_segment (300s LLM cap)      │  SSE: compile_started
                                │   │   ‖ orchestrator: angle-selector    │
                                │   │     → publisher (save_segment)      │
                                │   │   ‖ caption: Gemini 2.5 Flash       │
                                │   │     on stitched 3-child composite   │
                                │   │   then: per-run ffmpeg trim (30s)   │
                                │   │   then: re-insert with title +      │
                                │   │           caption + video_url       │  SSE: segment_published
                                │   └─────────────────────────────────────┘
                                ▼                                          ▼
                          GET /feed (proximity+recency sort)         Feed.tsx refetches
                                                                     (cluster_assigned or
                                                                      segment_published)
```

The whole pipeline is async tasks chained via `asyncio.create_task` inside the FastAPI process. No queues, no Celery, no broker.

## Stages

### 1. Capture (frontend)

**Code:** `frontend/src/views/Recorder.tsx`

State machine: `priming → acquiring → ready → recording → retake → gps-pending → submitting`. 8 phases tracked as a discriminated union (`Recorder.tsx:39`).

- **MIME selection** — `pickMimeType()` from `frontend/src/lib/mimeLadder.ts` walks `mp4;avc1 → webm;vp9 → webm → undefined`. When everything fails, the `MediaRecorder` constructor option is omitted entirely (Safari is happier with no mimeType). `Recorder.tsx:108-113`.
- **Recording cap** — 30s hard cap, 5s minimum (Marengo requires ≥4s). Clock ticks every 100ms via `setInterval` and stops the recorder when elapsed ≥ `RECORD_CAP_SEC`. `Recorder.tsx:131-140`.
- **GPS is blocking** — `getPositionWithTimeout(5000)` runs after retake confirmation. A clip with no GPS fix is rejected at the UI (`error: location-unavailable`) — the backend never sees it. `Recorder.tsx:159-171`.
- **Submit** — `postClip({ blob, filename, lat, lng, ts })` POSTs `multipart/form-data` to `/clips` with header `X-Session-Id: <uuid>` (anonymous session in `localStorage`). On any non-2xx, the blob is enqueued in `uploadQueue` and retried on the next `/feed` visit. `Recorder.tsx:181-201`, `frontend/src/api.ts:36-55`.

### 2. Ingest (`POST /clips`)

**Code:** `backend/app.py:105-126`

Endpoint returns **202 Accepted** synchronously with `IngestResponse(clip_id, status="processing")`. Validation:

| Check | Limit | Error |
|---|---|---|
| Content-Type | starts with `video/mp4` or `video/webm` | 415 |
| `lat` / `lng` range | ±90 / ±180 | 422 |
| Body size | ≤ 100 MiB | 413 |

After validation:
1. `db.insert_clip()` writes the blob to `${DATA_DIR}/clips/{uuid}.{ext}` and inserts a row with `embedding_status='pending'`, `cluster_id=NULL`, `session_id` from the `X-Session-Id` header. `backend/db.py:133-154`.
2. `events.broadcast({"type": "clip_added", "clip_id": ...})` — fans out to every SSE subscriber via bounded `asyncio.Queue(maxsize=64)`; `QueueFull` drops events for slow clients. `backend/events.py`.
3. `asyncio.create_task(run_pipeline(clip_id))` — fire-and-forget. The HTTP response returns immediately; the pipeline runs on the same event loop in the background.

### 3. Pipeline orchestrator

**Code:** `backend/pipeline/run.py:34-72`

Three sequential awaits inside one task:

```python
parent_clip_id, parent_vec = await embed_worker(clip_id)
# SSE: pipeline_progress stage="embedded"
cluster_id = await cluster_worker(parent_clip_id, parent_vec)
# SSE: pipeline_progress stage="clustered"
if await _should_compile(cluster_id):
    asyncio.create_task(compile_segment(cluster_id))
```

Errors are caught at the top level, scrubbed (`TWELVELABS_API_KEY` redacted), and broadcast as `pipeline_error` so the frontend can surface failure without leaking secrets. `run.py:12-17, 69-71`.

### 4. Embed — Twelve Labs Marengo 3.0

**Code:** `backend/pipeline/embed.py`

Wrapped in `loop.run_in_executor(None, _sync_embed, clip_path, clip_id)` so Marengo's blocking SDK call never freezes the event loop. Retries 3× with exponential backoff (`tenacity`).

The Marengo call requests **two embedding scopes in one shot**:
- `embedding_scope=["clip", "asset"]` with `segmentation=Fixed(duration_sec=3)` — produces one **asset-scope** parent vector covering the whole clip and a list of **clip-scope** child vectors, each spanning 3s.
- `embedding_option=["visual", "audio", "transcription"]`, `embedding_type=["fused_embedding"]` — single 512-d fused vector per scope.

After the call (`embed.py:91-114`):
- Each returned vector is L2-normalized to unit length and stored as `float32`.
- The parent embedding goes on the original `clips` row (`store_embedding(clip_id, parent_vec, latency_ms)`).
- Each child becomes its **own row** in the `clips` table via `insert_child_clip(parent_id=clip_id, start_offset_sec, end_offset_sec, ...)` and gets its own embedding stored. Children inherit `lat/lng/ts/session_id` from the parent.

**The Phase 4.6 pivot** (`embed.py:137-180`): only the parent vector enters clustering. Children exist for **compile-time slicing** — angle-selector and the caption pipeline read child rows + their embeddings, but the cluster centroid is built from parent-scope vectors only. `embed_worker` returns exactly one `(clip_id, parent_vec)` pair.

**Pre-warm** (`backend/app.py:23-39`): on lifespan startup, a throwaway `_sync_embed` runs against `PRE_WARM_CLIP_PATH` to pay Marengo's cold-start latency before the first real upload. Skipped when `USE_MOCK_EMBEDDINGS=true`. Failure is non-fatal.

**Mock path** (`embed.py:120-134`): `USE_MOCK_EMBEDDINGS=true` returns deterministic 512-d unit vectors keyed by `clip_id` + 3 fake children at 0–3s/3–6s/6–9s. Stable across restarts so demos replay identically.

### 5. Cluster — composite-score join

**Code:** `backend/pipeline/cluster.py`

In-memory `CLUSTERS: dict[str, ClusterCache]` is the active set (`cluster.py:68`). Rebuilt from sqlite on lifespan startup before the server accepts work (`app.py:70-71`, `cluster.py:227-242`).

The whole score-and-mutate critical section runs under a single `asyncio.Lock` to prevent two concurrent uploads from racing into separate clusters when they should join the same one (`cluster.py:136-195`).

**Scoring** (`cluster.py:103-118`):

```
visual = max(0, vec · centroid)               # both unit vectors → cosine
gps    = max(0, 1 − dist_m / 50.0)            # 0.0 when GPS unavailable on either side
time   = max(0, 1 − Δs / 600.0)
composite = 0.55·visual + 0.30·gps + 0.15·time
```

Weights and radii are locked at module level (`W_VISUAL=0.55, W_GPS=0.30, W_TIME=0.15, GPS_RADIUS_M=50.0, TIME_WINDOW_S=600.0`). Threshold and visual floor are env-tunable via `config.CLUSTER_THRESHOLD` (default `0.70`) and `config.VISUAL_FLOOR` (default `0.85`).

**Two-gate join** (`cluster.py:140-149`):
1. **Visual floor** — pre-filter: clusters with `visual < VISUAL_FLOOR` are ineligible regardless of composite. Without this, GPS+time alone contribute up to 0.45, so any clip within range would join *something*.
2. **Composite threshold** — best-eligible cluster joins only if `composite ≥ CLUSTER_THRESHOLD`.

**Centroid update** uses Welford running mean in float64 then re-normalized to unit length and stored as float32 (`update_centroid`, `cluster.py:86-96`). GPS centroid is averaged only when both old and new have a fix; otherwise the old value is preserved (`cluster.py:155-162`). Persist-then-mutate ordering: `db.upsert_cluster()` and `db.assign_clip_to_cluster()` complete before the in-memory `CLUSTERS` dict is updated (`cluster.py:176-178`).

The SSE `cluster_assigned` event includes the full score breakdown (`visual`, `gps`, `time`, `composite`, `gps_available`, `threshold`) so the frontend's debug overlay can show *why* a clip joined or didn't (`cluster.py:198-216`).

### 6. Compile gate

**Code:** `backend/pipeline/run.py:20-31`

Two checks before spending any LLM tokens:
1. `db.count_distinct_parents_in_cluster(cluster_id) >= 2` — solo-parent clusters never compile, even with N children. A "multi-angle segment" requires multiple distinct uploads.
2. `db.set_compile_in_flight(cluster_id, True, ttl_seconds=30.0)` — atomic CAS in sqlite that returns `False` if another compile is already in flight. Stale flags older than 30s are reclaimed.

Only when both pass does `compile_segment(cluster_id)` get scheduled.

### 7. Compile — multi-agent + vision caption

**Code:** `backend/pipeline/compile.py:362-475`

Three phases inside one 300s wall-clock budget plus a separate 30s ffmpeg budget:

**Phase 1 — LLM work in parallel (`asyncio.gather`, 300s timeout):**

| Branch A: orchestrator chain | Branch B: caption pipeline |
|---|---|
| `claude-agent-sdk` `query()` with two `AgentDefinition`s | `caption_pipeline.generate_caption()` |
| Model: `sonnet` for orchestrator + angle-selector, `haiku` for publisher | Model: `gemini-2.5-flash` (native video) |
| MCP tools: `get_cluster_runs`, `get_clip_metadata`, `save_segment` | Picks 3 children closest to centroid by cosine, ffmpeg-stitches them, uploads to Gemini Files API, polls until `ACTIVE`, calls `generate_content` with structured JSON schema |
| **Parent diversity** is enforced in the prompt and re-checked deterministically after the agent returns (`_enforce_parent_diversity`, `compile.py:249-309`) | Layer-2 sanitizer strips forbidden vocabulary (`camera`, `frame`, `footage`, …), enforces 8-word / 60-char title cap, detects title≈caption duplicates (`caption_pipeline.py:202-253`) |
| Output: a `segments` row with `ordered_clip_ids = [run_ids]`, `title=""`, `caption=""` | Output: `{title, caption, location, source: "vision"}` or `None` |

The orchestrator's flow (`compile.py:43-55`):
1. **angle-selector** picks 2–4 RUNS via `mcp__newz_tools__get_cluster_runs`. A *run* is a contiguous span of similar 3s child slices within a single parent — i.e. one continuous camera angle. Run detection lives in `backend/pipeline/runs.py:27-77`: per-parent walk over children with `cosine ≥ RUN_THRESHOLD` (default `0.70`) and `MAX_RUN_MEMBERS=2` cap (so a long parent doesn't collapse into one giant run). Run IDs are deterministic: `f"{parent_id}_run_{idx}"`.
2. **publisher** persists via `mcp__newz_tools__save_segment` with the ordered run IDs and empty title/caption strings (Branch B's output overwrites them later).

**Phase 1.5 — parent diversity guard** (`compile.py:249-309`): if angle-selector picked runs from fewer than 2 distinct parents while the cluster has ≥2 available parents, the segment row is patched in place with the earliest run from each missing parent. Belt-and-suspenders alongside the prompt constraint — LLMs don't always obey.

**Phase 2 — per-run ffmpeg trim (`asyncio.wait_for`, 30s timeout):** `_stitch_segment_runs` writes one `.mp4` per chosen run via `trim_window` — a stream-copy `-c copy` trim of one window from one parent file (no re-encode, ~50–100ms per run). Trims run in parallel via `asyncio.gather`. Output: `data/clips/{run_id}.mp4` per run, served at `/media/{run_id}.mp4`. `backend/pipeline/stitch.py:112-176`.

**Phase 3 — single re-insert** (`compile.py:438-454`): `db.insert_segment` re-runs with title from Branch B (or fallback), caption from Branch B (or fallback), `video_url = run_video_urls[0]` for headline playback, and `source_count = distinct parent count`. The `segments` table has a unique index on `cluster_id` so re-compiles upsert.

**Failure modes:**
- Orchestrator chain raises → `_save_fallback_segment(cluster_id)` writes a generic AP-wire caption with chronological clip ordering (`compile.py:220-241`).
- Branch B returns `None` or non-`vision` source → fallback caption.
- 300s LLM timeout → fallback segment, `compile_in_flight=False`, SSE `segment_published` still fires.
- 30s stitch timeout → segment row exists but `video_url=None`; frontend shows the segment without playable video.
- `OFFLINE_DEMO=true` or missing `GEMINI_API_KEY` → caption pipeline returns deterministic mock copy (`caption_pipeline.py:309-340`).

### 8. Real-time feed updates

**Code:** `backend/app.py:155-175`, `frontend/src/views/Feed.tsx:58-62`, `frontend/src/hooks/useEventSource.ts`

Backend `GET /events` returns an `EventSourceResponse` (sse-starlette). One bounded `asyncio.Queue` per subscriber; the request loop polls `q.get()` with a 1s timeout so it can detect client disconnect. Pings every 15s.

Frontend `useEventSource` opens one `EventSource` per tab (HTTP/1.1 6-connection limit). The Feed component re-fetches `/feed` on `cluster_assigned` or `segment_published` events. The feed list re-renders.

## Per-clip state machine

Every parent clip walks this state machine, persisted across `clips`, `clip_embeddings`, `clusters`, and `segments`:

```
INSERTED          (clips row, embedding_status='pending', cluster_id=NULL)
   │ embed_worker success
   ▼
EMBEDDED          (clip_embeddings row exists, N child clips inserted+embedded)
   │ cluster_worker success
   ▼
CLUSTERED         (clips.cluster_id set, clusters row updated, in-memory CLUSTERS updated)
   │ _should_compile returns True (≥2 distinct parents in cluster)
   ▼
COMPILE_PENDING   (clusters.compile_in_flight=1, TTL 30s)
   │ compile_segment success
   ▼
PUBLISHED         (segments row with title + caption + video_url + ordered_run_ids)
```

Failure paths:
- `embed_worker` raises → `clips.embedding_status='failed'`, pipeline aborts, `pipeline_error` SSE.
- `cluster_worker` raises → cluster cache untouched (persist-first ordering), pipeline aborts.
- `compile_segment` raises or times out → `_save_fallback_segment` writes a generic-caption row, `compile_in_flight=0`, `segment_published` SSE still fires.

## Key constraints

| Constraint | Where | Why |
|---|---|---|
| 30s recording cap (frontend) | `Recorder.tsx:49` (`RECORD_CAP_SEC`) | UX + Marengo asset upload size |
| 5s minimum recording | `Recorder.tsx:50` | Marengo requires ≥4s |
| 100 MiB upload cap | `backend/app.py:101` | Backend memory + Railway request limits |
| GPS blocking on submit | `Recorder.tsx:159-171` | D-07 conflict resolution; null-GPS clips rejected at UI |
| 50m GPS radius | `cluster.py:44` (`GPS_RADIUS_M`) | Tightened from 200m to fight one-location lump |
| 600s time window | `cluster.py:45` (`TIME_WINDOW_S`) | Same-event recordings are typically within 10 min |
| 0.70 cluster threshold | `config.CLUSTER_THRESHOLD` | Tuned against staged demo set |
| 0.85 visual floor | `config.VISUAL_FLOOR` | Prevents GPS+time fusing adversarial clips |
| ≥2 distinct parents to compile | `run.py:28-29` | Solo-parent compiles waste tokens |
| 300s LLM compile budget | `compile.py:393` | Absorbs retry/throttle bursts |
| 30s stitch budget | `compile.py:425` | Pulled out of LLM gather so ffmpeg isn't cancelled by orchestrator timeout |
| Pre-warm Marengo + Claude SDK | `app.py:64-77` | Cold-start latency = dead demo |
| OFFLINE_DEMO env flag | `caption_pipeline.py:335`, `embed.py:120` | Live-first demo with cached fallback |

## Where the data lives

| What | Where | When |
|---|---|---|
| Raw uploaded blob | `${DATA_DIR}/clips/{clip_id}.{ext}` | On `POST /clips` |
| Per-run trimmed `.mp4` | `${DATA_DIR}/clips/{run_id}.mp4` | At compile Phase 2 |
| Caption composite (transient) | `${DATA_DIR}/clips/{cluster_id}_caption_input.mp4` | Created and unlinked inside `generate_caption` |
| Parent + child rows | `clips` table (one row per parent, one per child, parent_id FK) | On embed |
| Embeddings | `clip_embeddings.vector` BLOB (512 × float32 = 2048 bytes) | On embed |
| Cluster centroids | `clusters` table (centroid BLOB, centroid_lat/lng, median_ts) | On cluster join/create |
| Active cluster cache | `cluster.CLUSTERS: dict[str, ClusterCache]` | In-memory; rebuilt from sqlite on lifespan |
| Published segment | `segments` table (one per cluster_id, unique index) | On compile success or fallback |
| Compile lock | `clusters.compile_in_flight` + `last_compile_at` (CAS) | During compile, TTL 30s |

All persistent state is in `${DATA_DIR}` (sqlite WAL + clip files). Wiping the data dir resets the system; `POST /admin/reset` does the same with token auth (`backend/app.py:356-417`).
