# External Integrations

**Analysis Date:** 2026-04-24

## APIs & External Services

**Video AI:**
- Twelve Labs Marengo 3.0 — Generates 512-dimensional multimodal embeddings (visual + audio + speech in one vector) per submitted clip. The load-bearing AI primitive for event clustering.
  - SDK/Client: `twelvelabs==1.2.3` (Python)
  - Auth: `TWELVELABS_API_KEY` env var
  - Model name string: `"marengo3.0"` (lowercase, no hyphen — the old `"Marengo-retrieval-2.7"` style is dead since 2026-03-30)
  - Integration point: `backend/pipeline/embed.py`
  - Call pattern: synchronous embed path for clips under 10 minutes — `client.embed.create(model_name="marengo3.0", video_file=..., video_embedding_scope=["asset"], embedding_option=["visual", "audio", "transcription"])`
  - Output: `result.video_embedding.segments[0].embeddings_float` — list of 512 floats
  - Latency: 5–30 seconds per clip on the sync path. Never block the HTTP response on this call — fire-and-forget via `asyncio.create_task`.
  - Pre-warm: hit Marengo with a throwaway clip on FastAPI startup (`lifespan` event) to eliminate cold-start latency before the demo.
  - Offline fallback: `OFFLINE_DEMO=true` env flag bypasses the API and loads cached embeddings from `backend/seed/embeddings.json`.
  - Constraints: 4-second minimum clip length (enforce in the recorder UI). Must verify exact method names against `pip show twelvelabs` + `dir(client.embed)` on day 1 — do not rely on documentation code samples verbatim.

**Multi-Agent AI:**
- Anthropic Claude Agent SDK — Powers the 4-subagent editorial compile pipeline (Angle Selector → Editor → Caption Writer → Publisher). Produces a headline, caption, and ordered clip list per cluster.
  - SDK/Client: `claude-agent-sdk==0.1.68` (Python); includes direct `anthropic==0.39.0` as fallback for one-shot calls
  - Auth: `ANTHROPIC_API_KEY` env var (same key for both packages)
  - Integration point: `backend/pipeline/compile.py`
  - Call pattern: `async for msg in query(prompt=..., options=ClaudeAgentOptions(allowed_tools=["Agent"], agents={...}, mcp_servers={...})):`
  - Subagent models: `"sonnet"` for Angle Selector, Editor, Caption Writer; `"haiku"` for Publisher (deterministic tool call only)
  - **`"Agent"` must be in `allowed_tools`** — without it the orchestrator cannot invoke subagents (silent failure)
  - Subagents receive fresh context windows; state passes only through the orchestrator's prompt construction
  - Hard cap: 30-second wall-clock timeout on the full compile pipeline; fallback to default clip ordering + generic caption
  - Run inside `asyncio.create_task` (never inside a synchronous request-response cycle — will exceed Railway/Vercel timeouts)
  - Offline fallback: `OFFLINE_DEMO=true` loads cached compile output from `backend/seed/segment.json`
  - Bundled CLI binary: the wheel ships the Claude Code CLI — no separate Node.js install needed on Railway

## Data Storage

**Databases:**
- SQLite (single file, WAL mode)
  - Connection: file path configured via `DATA_DIR` env var (local: `./newz.db`; Railway: `/data/newz.db`)
  - Client: `aiosqlite` for async access from FastAPI coroutines
  - Schema tables: `clips`, `clip_embeddings` (512-d vectors stored as BLOB), `clusters`, `segments`
  - Vector storage: `numpy.float32` byte arrays stored as SQLite BLOBs (512 dims = 2048 bytes per vector)
  - In-memory cache: `active_clusters` list rebuilt from SQLite at startup (FastAPI `lifespan` event); SQLite is source of truth, in-memory is the speed cache for the assignment loop
  - No Postgres, no Redis, no pgvector — zero-config is load-bearing at hackathon scale

**File Storage:**
- Local filesystem on the Railway persistent volume
  - Clip files stored at `{DATA_DIR}/clips/{clip_id}.{ext}` (extension from actual MIME type: `.webm` for Chrome, `.mp4` for Safari)
  - Served to the browser via FastAPI `StaticFiles` mount: `app.mount("/clips", StaticFiles(directory=clips_dir))`
  - Frontend `<video>` elements reference clips by URL directly (no transcoding, no pre-signed URLs)
  - Pre-recorded staged demo clips stored at `backend/seed/demo_clips/` (committed to repo; load-bearing for offline demo)
  - No S3 — adds creds, CORS config, and a network failure mode in the upload hot path

**Caching:**
- No Redis or external cache
- In-process: `active_clusters: list[ClusterCache]` held in FastAPI process memory (rebuilt from SQLite on startup)
- On-disk: `backend/seed/embeddings.json` and `backend/seed/segment.json` cache pre-computed outputs for the staged demo dataset (enables `OFFLINE_DEMO=true`)

## Authentication & Identity

**Auth Provider:**
- None — anonymity is a load-bearing product constraint, not a deferred feature
  - Implementation: anonymous session UUID stored in `localStorage` (browser-side only); never sent to the backend as an identity token
  - No accounts, no login, no profiles
  - Clips are identified by a server-generated UUID; no user identity is ever attached

## Monitoring & Observability

**Error Tracking:**
- None — hackathon scope; standard Python logging to stdout (Railway captures stdout logs)

**Logs:**
- `log.exception(...)` in pipeline error handlers (each stage catches and broadcasts a `pipeline_error` SSE event)
- SSE event bus surfaces pipeline errors to the frontend: `{"type": "pipeline_error", "clip_id": ..., "error": ...}`

## CI/CD & Deployment

**Hosting:**
- Frontend: Vercel — static React/Vite build; auto-deploy on GitHub push; HTTPS + CDN automatic
  - Deploy command: `vercel --prod` from `frontend/` after `pnpm build`
  - Environment variable: `VITE_API_BASE=https://newz-api.up.railway.app`
- Backend: Railway — single-container Python service; auto-detects FastAPI/Dockerfile from GitHub
  - Deploy command: `railway up` from `backend/` or push to connected GitHub repo
  - Persistent volume mounted at `/data` for SQLite file + clip storage
  - Free tier sufficient for demo traffic

**CI Pipeline:**
- None configured — direct push-to-deploy via Vercel + Railway GitHub integrations

**Demo Failsafes:**
- Personal hotspot as WiFi backup (Tier 1)
- `OFFLINE_DEMO=true` serves everything from local SQLite + disk, bypassing all external APIs (Tier 2)
- ngrok or Cloudflare Tunnel as Railway failsafe — point laptop localhost at a tunnel (Tier 3)
- Pre-recorded 90-second screencast in pitch deck as last resort (Tier 4)

## Browser APIs (Client-Side)

**Camera Capture:**
- `navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: true })`
- `MediaRecorder` with MIME type detection ladder: `"video/mp4;codecs=avc1,mp4a"` → `"video/webm;codecs=vp9,opus"` → `"video/webm"` → no mimeType (iOS Safari fallback)
- **Never hardcode `mimeType: "video/webm"`** — Safari silently produces empty output
- Cap recording at 30 seconds (iOS Safari bug causes page reload on clips ≥60s)
- Upload as `multipart/form-data` POST to `/clips`

**Geolocation:**
- `navigator.geolocation.getCurrentPosition(success, error, { enableHighAccuracy: true, timeout: 10_000, maximumAge: 0 })`
- Requires HTTPS (Vercel + Railway both provide it automatically; `localhost` is exempt)
- GPS is optional — submit with `gps=null` on timeout/denial; cluster scoring weights Marengo similarity higher when GPS is missing
- `?demo_location=lat,lon` query param override for indoor venue GPS inaccuracy at Caltech

**Real-Time Updates:**
- `EventSource` (SSE) connecting to `GET /events` on the backend
- Events: `clip_added`, `cluster_updated`, `segment_published`, `pipeline_error`
- Auto-reconnect handled natively by the browser

## Webhooks & Callbacks

**Incoming:**
- None — Twelve Labs webhooks exist but are not worth the ngrok overhead for the hackathon; polling via `task.wait_for_done()` is used instead

**Outgoing:**
- None

## Environment Configuration

**Required env vars:**
- `ANTHROPIC_API_KEY` — Anthropic API credentials (backend only)
- `TWELVELABS_API_KEY` — Twelve Labs API credentials (backend only)
- `FRONTEND_URL` — set in Railway after first Vercel deploy; used in CORS `allow_origins`
- `DATA_DIR` — filesystem root for clips + SQLite (default `./data` or `/data` on Railway)
- `VITE_API_BASE` — backend URL, set in Vercel project settings (frontend only)

**Optional env vars:**
- `OFFLINE_DEMO=true` — bypasses all external APIs; serves cached embeddings + segments from `backend/seed/`
- `USE_MOCK_EMBEDDINGS=true` — skips Marengo during development; returns deterministic fake 512-d vectors

**Secrets location:**
- Backend: `.env` file (gitignored); mirrored as Railway environment variables in production
- Frontend: `.env.local` file (gitignored); mirrored as Vercel environment variables in production
- API keys must never appear in frontend bundles or git history

---

*Integration audit: 2026-04-24*
