<!-- generated-by: gsd-doc-writer -->
# API

HTTP + SSE contract for the Newz FastAPI backend (`backend/app.py`). For runtime config see [`./CONFIGURATION.md`](./CONFIGURATION.md). For pipeline behavior see [`./ARCHITECTURE.md`](./ARCHITECTURE.md).

**Base URL (local):** `http://localhost:8000`
**Auth:** None. The backend is anonymous by design (see CLAUDE.md "Hard Constraints"). The optional `X-Session-Id` header on `POST /clips` is a client-generated UUID stored in localStorage — it is recorded for debugging only, never validated.
**CORS:** `FRONTEND_URL` env var + `http://localhost:5173`, all methods, credentials allowed.

---

## Public API

### `GET /health`

Liveness probe. No side effects.

| Status | Body |
| --- | --- |
| `200` | `{"ok": true}` |

```bash
curl http://localhost:8000/health
```

---

### `POST /clips`

Ingest one captured video clip. Returns immediately (`202`) and runs embed → cluster → compile in the background via `asyncio.create_task(run_pipeline)`.

**Request:** `multipart/form-data`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `file` | file | yes | `video/mp4` or `video/webm` only. Max **100 MiB**. |
| `lat` | float (form) | yes | `-90.0 <= lat <= 90.0`. |
| `lng` | float (form) | yes | `-180.0 <= lng <= 180.0`. |
| `ts` | float (form) | yes | Client capture timestamp (epoch seconds). |
| `X-Session-Id` | header | no | Anonymous session UUID; opaque. |

**Response 202** (`IngestResponse`, see `backend/models.py`):

```json
{ "clip_id": "9e1b…hex", "status": "processing" }
```

**Errors:**

| Status | When |
| --- | --- |
| `413` | Upload > 100 MiB |
| `415` | `Content-Type` not in `video/mp4*`, `video/webm*` |
| `422` | `lat`/`lng` out of range, or missing form fields |

**Side effects (in order):**
1. Bytes written to `DATA_DIR/clips/{clip_id}.{ext}`.
2. Row inserted into `clips` (sqlite).
3. SSE `clip_added` broadcast.
4. `run_pipeline(clip_id)` scheduled — emits `pipeline_progress`, `cluster_assigned`, possibly `compile_started` + `segment_published`, or `pipeline_error`.

```bash
curl -X POST http://localhost:8000/clips \
  -H "X-Session-Id: $(uuidgen)" \
  -F "file=@clip.mp4;type=video/mp4" \
  -F "lat=34.1377" \
  -F "lng=-118.1253" \
  -F "ts=$(date +%s)"
```

---

### `GET /feed`

Top-N most recent compiled segments. Up to 50 rows.

**Query params:**

| Param | Type | Required | Notes |
| --- | --- | --- | --- |
| `lat` | float | no | If both `lat` and `lng` are present, results are re-sorted by `-(distance_km) - 0.5*(age_hours)`. Missing centroid → distance=`1e9`. |
| `lng` | float | no | See `lat`. |

**Response 200:**

```json
{
  "segments": [
    {
      "id": "seg_hex",
      "cluster_id": "clu_hex",
      "ordered_clip_ids": ["clip_a", "clip_b"],
      "caption": "Brush fire on Wilson Ave...",
      "location": "Pasadena, CA",
      "source_count": 3,
      "created_at": 1714000000.0,
      "centroid_lat": 34.137,
      "centroid_lng": -118.125,
      "video_url": "/media/clu_hex_compiled.webm",
      "video_urls": ["/media/clip_a.mp4", "/media/clip_b.mp4"]
    }
  ]
}
```

`video_url` is the stitched compile when present; otherwise falls back to the first source clip URL. `video_urls` is the per-clip ordered playlist (used by frontend for sequential multi-angle playback).

```bash
curl "http://localhost:8000/feed?lat=34.1377&lng=-118.1253"
```

---

### `GET /events` (SSE)

Server-Sent Events stream. One `EventSource` per browser tab (HTTP/1.1 6-connection cap). 15s keepalive ping. The connection lives until client disconnect.

Each frame is `event: <type>` + `data: <json>`. The JSON `data` payload always includes a `type` field matching the SSE event name.

```bash
curl -N http://localhost:8000/events
```

#### SSE event types

All events are emitted via `events.broadcast(...)` from `backend/events.py`. Slow subscribers (queue >64) silently drop events.

##### `clip_added` — `backend/app.py:124`
Emitted immediately after `POST /clips` writes the row.
```json
{ "type": "clip_added", "clip_id": "9e1b…" }
```

##### `pipeline_progress` — `backend/pipeline/run.py:43,58`
Emitted twice per upload: after embed completes, after clustering completes.
```json
{ "type": "pipeline_progress", "clip_id": "9e1b…", "stage": "embedded" }
```
`stage` is one of: `"embedded"`, `"clustered"`.

##### `cluster_assigned` — `backend/pipeline/cluster.py:216`
Emitted once per child segment (a single uploaded clip can produce multiple children if longer than the 3s Marengo segmentation window). `score_breakdown` is `null` only when the clip created a brand-new cluster (no existing centroid to score against).
```json
{
  "type": "cluster_assigned",
  "clip_id": "9e1b…",
  "cluster_id": "clu_hex",
  "is_new_cluster": false,
  "member_count": 3,
  "score_breakdown": {
    "visual": 0.8421,
    "gps": 0.9100,
    "time": 0.7500,
    "composite": 0.8407,
    "gps_available": true,
    "threshold": 0.55
  }
}
```

##### `compile_started` — `backend/pipeline/compile.py:353`
Emitted when a cluster crosses `member_count >= 2` and acquires the in-flight CAS lock.
```json
{ "type": "compile_started", "cluster_id": "clu_hex", "started_at": 1714000000.0 }
```

##### `segment_published` — `backend/pipeline/compile.py:437`
Always emitted after compile (success, timeout, or fallback). On timeout/error, `segment_id` is the fallback row's id.
```json
{ "type": "segment_published", "cluster_id": "clu_hex", "segment_id": "seg_hex" }
```

##### `pipeline_error` — `backend/pipeline/run.py:73`
Emitted only when the embed/cluster pipeline raises. `error` strings are scrubbed of `TWELVELABS_API_KEY` before broadcast (see `_scrub` in `run.py`).
```json
{ "type": "pipeline_error", "clip_id": "9e1b…", "error": "marengo timeout" }
```

---

### `GET /media/{filename}`

Static file mount serving `DATA_DIR/clips/`. Filenames returned by `/feed` (`/media/...`) resolve here. Read-only. No directory listing.

---

## Debug endpoints

> **Unstable, dev-only.** No auth, no rate limit, no schema stability. Do not call from the frontend in production. The cluster/compile-trigger endpoints mutate state.

### `GET /debug/clusters`
Per-cluster member breakdown with composite-score components vs the centroid. Powers the calibration overlay (see ROADMAP Phase 3 / CLU-09). `gps_distance_m` is `null` when `gps_available=false`.

### `GET /debug/dbstate`
Raw counts and sample IDs straight from sqlite. Used to diagnose in-memory ↔ DB drift.

### `GET /debug/clip/{clip_id}`
Returns `{"found": bool, "clip": <row>}` — the raw `clips` row.

### `POST /debug/compile/{cluster_id}`
Force-triggers `compile_segment(cluster_id)`. Resets the in-flight CAS lock first, then re-acquires.

| Status | When |
| --- | --- |
| `200` | `{"status": "triggered", "cluster_id": "..."}` |
| `409` | Compile already in flight (CAS lost the race) |

### `POST /debug/caption_writer/{cluster_id}`
Runs the vision caption-writer subagent in isolation. Does **not** write to the DB. Returns staged diagnostics (`ffmpeg_path`, per-clip keyframe extraction byte counts, the raw `caption`/`location` on success) so failures can be localized to: keyframe DB lookup, ffmpeg extraction, or the agent call itself. The response shape varies by failure stage — see `backend/app.py:282`.

---

## Status code summary

| Code | Where | Meaning |
| --- | --- | --- |
| `200` | All `GET` endpoints, `POST /debug/compile` (success) | OK |
| `202` | `POST /clips` | Accepted, processing in background |
| `409` | `POST /debug/compile` | Compile already in flight |
| `413` | `POST /clips` | Upload > 100 MiB |
| `415` | `POST /clips` | Content-Type not mp4/webm |
| `422` | `POST /clips` | Validation (lat/lng range, missing form fields) |
| `500` | Any | Unhandled exception (FastAPI default) |
