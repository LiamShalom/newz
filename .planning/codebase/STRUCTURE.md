# Codebase Structure

**Analysis Date:** 2026-04-24

**Note:** No source code exists yet — the project is at Phase 0 (pre-Phase 1). This document describes the **prescribed structure** from `.planning/research/ARCHITECTURE.md`, which is the authoritative blueprint. All paths below are targets for implementation.

## Directory Layout

```
newz/                             # Project root
├── backend/                      # FastAPI monolith (Python 3.11)
│   ├── app.py                    # FastAPI app, routes, lifespan
│   ├── config.py                 # Env vars (TL_API_KEY, ANTHROPIC_API_KEY, paths, flags)
│   ├── db.py                     # SQLite init, schema, aiosqlite async helpers
│   ├── models.py                 # Pydantic v2: Clip, Cluster, Segment, ScoreBreakdown
│   ├── events.py                 # SSE event bus (asyncio.Queue per client)
│   ├── feed.py                   # Proximity + recency feed ranking
│   ├── pipeline/
│   │   ├── embed.py              # Twelve Labs Marengo 3.0 wrapper + mock mode
│   │   ├── cluster.py            # Online single-pass clustering + composite score
│   │   ├── compile.py            # Claude Agent SDK 4-subagent pipeline
│   │   └── tools.py              # @tool functions exposed to agents
│   └── seed/
│       ├── demo_clips/           # 3-4 pre-recorded clips (.webm / .mp4)
│       └── seed.py               # Replay script — posts demo clips on startup
├── frontend/                     # React 18 + Vite + TypeScript + Tailwind 4
│   ├── src/
│   │   ├── App.tsx               # React Router: / (Feed) + /record (Recorder)
│   │   ├── views/
│   │   │   ├── Recorder.tsx      # MediaRecorder + GPS + MIME ladder + POST /clips
│   │   │   ├── Feed.tsx          # SSE listener + vertical TikTok-style segment grid
│   │   │   └── Debug.tsx         # Score breakdown overlay (judges)
│   │   ├── api.ts                # fetch() wrappers for all backend endpoints
│   │   └── sse.ts                # EventSource hook — subscribes to GET /events
│   ├── index.html
│   ├── vite.config.ts            # Proxy /api → FastAPI :8000
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   └── package.json
├── notebooks/                    # Calibration work (Phase 3)
│   └── cluster_calibration.ipynb # Empirical threshold tuning against staged dataset
├── clips/                        # Runtime clip storage — gitignored (local dev)
├── newz.db                       # SQLite database file — gitignored
├── requirements.txt              # Python dependencies (pinned)
├── Makefile                      # `make demo` — single-command demo boot
├── CLAUDE.md                     # Project guide for Claude
└── .planning/                    # GSD planning artifacts
    ├── PROJECT.md
    ├── REQUIREMENTS.md
    ├── ROADMAP.md
    ├── STATE.md
    ├── codebase/                 # Codebase map (this document lives here)
    └── research/                 # Pre-build research artifacts
```

## Directory Purposes

**`backend/`:**
- Purpose: Entire Python backend — routes, pipeline, storage, event bus
- Contains: FastAPI app, Pydantic models, SQLite helpers, all AI pipeline stages
- Key files: `backend/app.py` (entry point), `backend/pipeline/cluster.py` (core demo magic)

**`backend/pipeline/`:**
- Purpose: The three-stage AI pipeline — each file is one independent stage
- Contains: `embed.py`, `cluster.py`, `compile.py`, `tools.py`
- Key constraint: Each file must be independently testable with a mock clip path; if `compile.py` fails, `cluster.py` still works as the fallback demo

**`backend/seed/`:**
- Purpose: Load-bearing demo infrastructure — pre-recorded clips and replay script
- Contains: `demo_clips/` (3-4 angle files of one staged event), `seed.py`
- Key constraint: `OFFLINE_DEMO=true` must serve cached embeddings + cached compile output from here with zero external API calls

**`frontend/src/views/`:**
- Purpose: Three top-level views — each owns its own state
- Contains: `Recorder.tsx`, `Feed.tsx`, `Debug.tsx`
- Key constraint: No premature componentization; at 24-hour scope, each view file is self-contained

**`notebooks/`:**
- Purpose: Phase 3 calibration — empirically validate clustering thresholds before the demo
- Contains: `cluster_calibration.ipynb` — must pass by hour 12 of the build window
- Key constraint: This notebook is a Phase 3 deliverable, not optional polish

**`clips/`:**
- Purpose: Runtime clip storage on local filesystem, served via FastAPI `StaticFiles`
- Generated: Yes (created at runtime)
- Committed: No (gitignored)
- Production path: `/data/clips/` on Railway persistent volume

## Key File Locations

**Entry Points:**
- `backend/app.py`: FastAPI app factory, all route definitions, lifespan hooks (DB init, Marengo pre-warm, seed replay)
- `frontend/src/App.tsx`: React Router root, two routes (`/` → Feed, `/record` → Recorder)
- `backend/seed/seed.py`: Demo seed replay, also callable via "Replay Staged Event" endpoint

**Configuration:**
- `backend/config.py`: All env vars — `TL_API_KEY`, `ANTHROPIC_API_KEY`, `CLUSTER_THRESHOLD`, `USE_MOCK_EMBEDDINGS`, `OFFLINE_DEMO`, `DATA_DIR`
- `frontend/vite.config.ts`: Dev proxy (`/api → http://localhost:8000`), build output config
- `requirements.txt`: Pinned Python deps including `twelvelabs==1.2.3`, `claude-agent-sdk==0.1.68`

**Core Logic:**
- `backend/pipeline/embed.py`: Twelve Labs `marengo3.0` wrapper; `USE_MOCK_EMBEDDINGS` flag; startup pre-warm call
- `backend/pipeline/cluster.py`: Composite score formula, in-memory `active_clusters` list, `assign_or_create()`, `should_compile()`
- `backend/pipeline/compile.py`: Claude Agent SDK orchestrator + 4 `AgentDefinition` objects; 30s `asyncio.wait_for` hard cap
- `backend/pipeline/tools.py`: `@tool` functions (`get_cluster_clips`, `get_clip_metadata`, `save_segment`) exposed to agents via MCP server
- `backend/events.py`: `broadcast()` function, `_subscribers: list[asyncio.Queue]`, SSE generator
- `backend/db.py`: Schema (clips, embeddings, clusters, segments tables), WAL mode pragma, async CRUD helpers

**Frontend Views:**
- `frontend/src/views/Recorder.tsx`: MediaRecorder + MIME ladder + Geolocation + multipart POST + localStorage retry queue
- `frontend/src/views/Feed.tsx`: SSE subscription + segment grid + proximity/age overlay + FAB + empty state
- `frontend/src/views/Debug.tsx`: Cluster score bar chart — load-bearing for judge demo

**Testing/Calibration:**
- `notebooks/cluster_calibration.ipynb`: Threshold validation against staged dataset; adversarial test (unrelated clips must not cluster)

## Naming Conventions

**Files:**
- Backend Python: `snake_case.py` (e.g., `embed.py`, `cluster.py`, `compile.py`)
- Frontend TypeScript views: `PascalCase.tsx` (e.g., `Recorder.tsx`, `Feed.tsx`)
- Frontend utilities: `camelCase.ts` (e.g., `api.ts`, `sse.ts`)

**Directories:**
- Backend: lowercase `snake_case` (e.g., `pipeline/`, `seed/`)
- Frontend: lowercase (e.g., `views/`, `src/`)

**Pydantic Models:**
- `PascalCase` in `backend/models.py` (e.g., `Clip`, `Cluster`, `Segment`, `ScoreBreakdown`)

**Database Tables:**
- `snake_case` plural (e.g., `clips`, `embeddings`, `clusters`, `segments`)

**Environment Variables:**
- `SCREAMING_SNAKE_CASE` (e.g., `TL_API_KEY`, `CLUSTER_THRESHOLD`, `USE_MOCK_EMBEDDINGS`, `OFFLINE_DEMO`)

**SSE Event Types:**
- `snake_case` string (e.g., `clip_added`, `cluster_updated`, `segment_published`, `pipeline_error`)

## Where to Add New Code

**New backend route:**
- Add handler to `backend/app.py`
- Add Pydantic request/response models to `backend/models.py`
- Add DB helper to `backend/db.py` if needed

**New pipeline stage:**
- Add new file in `backend/pipeline/`
- Wire into `run_pipeline()` in `backend/app.py`
- Add SSE broadcast event at stage completion

**New agent tool:**
- Add `@tool` function to `backend/pipeline/tools.py`
- Register in `newz_tools = create_sdk_mcp_server(tools=[...])`
- Add to relevant `AgentDefinition.tools` list in `backend/pipeline/compile.py`

**New frontend view:**
- Add `PascalCase.tsx` to `frontend/src/views/`
- Add route in `frontend/src/App.tsx`
- Fetch helpers go in `frontend/src/api.ts`

**New frontend component (shared):**
- Add to `frontend/src/components/` (create this directory when first needed)

**Utilities / shared helpers:**
- Backend: `backend/` root level module (e.g., `backend/utils.py`)
- Frontend: `frontend/src/` root level `.ts` file

**Demo artifacts:**
- Pre-recorded clips: `backend/seed/demo_clips/`
- Cached embeddings/compile output: `backend/seed/` (alongside `seed.py`)

## Special Directories

**`backend/seed/demo_clips/`:**
- Purpose: 3-4 `.webm` or `.mp4` files of the same staged event from different angles
- Generated: No (manually recorded and committed)
- Committed: Yes — this is load-bearing for the demo

**`clips/` (local dev) / `/data/clips/` (production):**
- Purpose: Runtime clip file storage, served via FastAPI `StaticFiles`
- Generated: Yes (written by `POST /clips` handler)
- Committed: No (gitignored)

**`notebooks/`:**
- Purpose: Calibration work; `cluster_calibration.ipynb` is a required Phase 3 deliverable
- Generated: No (hand-authored)
- Committed: Yes

**`.planning/`:**
- Purpose: GSD planning artifacts — project vision, requirements, roadmap, state, research
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-04-24*
