# Technology Stack

**Analysis Date:** 2026-04-24

## Languages

**Primary:**
- Python 3.11 - Backend (FastAPI monolith, embedding pipeline, multi-agent compile)
- TypeScript 5.5+ - Frontend (React SPA, all UI components)

**Secondary:**
- SQL - SQLite schema (clips, embeddings, clusters, segments tables)

## Runtime

**Environment:**
- Python 3.11 — 3.10+ required by `claude-agent-sdk`; avoid 3.13 (patchy wheel availability as of April 2026)
- Node 18+ — Frontend tooling only (Vite dev server, pnpm); NOT required on the backend

**Package Manager:**
- pnpm — Frontend (Vite ecosystem)
- pip — Backend Python dependencies
- Lockfile: `requirements.txt` (backend); `pnpm-lock.yaml` (frontend, generated on first install)

## Frameworks

**Core:**
- FastAPI 0.115.6 — Python web framework; native async, auto OpenAPI, Pydantic v2, CORS middleware
- Uvicorn 0.32.1 — ASGI server; `--reload` in dev, single-worker production on Railway
- React 18.3.x — UI framework; SPA with two routes (`/` feed, `/record` camera)
- Vite 5.x — Frontend bundler/dev server; sub-second HMR, zero-config TypeScript

**Styling:**
- Tailwind CSS 4.x — utility-first styling; zero design-system overhead

**Routing:**
- React Router 6.x — client-side routing; exactly two routes

**State:**
- Zustand 4.x — lightweight client state (GPS, recording state, feed list); use only if `useState` becomes painful

**Testing:**
- Not configured — hackathon scope; no test runner required

**Build/Dev:**
- `@tailwindcss/vite` — Tailwind v4 Vite plugin
- Vercel CLI — frontend deploy (`vercel --prod` from `frontend/`)
- Railway CLI — backend deploy (`railway up` from `backend/`)

## Key Dependencies

**Critical — Backend:**
- `twelvelabs==1.2.3` — Official Twelve Labs Python SDK; the only supported path to Marengo 3.0 embeddings. **Use model name `"marengo3.0"` (lowercase, no hyphen).** Marengo 2.7 sunset 2026-03-30.
- `claude-agent-sdk==0.1.68` — Anthropic multi-agent runtime; **bundles Claude Code CLI binary inside the wheel — no Node.js needed on Railway**. Supports Sonnet/Haiku subagents. To use Opus 4.7 pin `>=0.2.111` (incompatible API surface with 0.1.x).
- `python-multipart==0.0.18` — **Required** by FastAPI to receive multipart video uploads; omitting it causes cryptic 400 errors.
- `aiosqlite` — Async SQLite access from FastAPI coroutines; WAL mode for concurrent reads.
- `numpy==2.1.3` — In-memory cosine similarity over 512-d Marengo vectors; single matmul over ≤1000 normalized vectors is <1ms. No vector DB needed at hackathon scale.
- `pydantic==2.10.3` — Data validation; bundled with FastAPI; use for Clip, Cluster, Segment, ScoreBreakdown models.
- `sse-starlette` — Server-Sent Events via `EventSourceResponse`; powers the real-time feed event bus.

**Supporting — Backend:**
- `anthropic==0.39.0` — Direct Claude API client (optional; Agent SDK covers most cases but useful for one-shot calls outside the pipeline)
- `httpx==0.27.2` — Async HTTP client for any supplemental external calls
- `python-dotenv==1.0.1` — Local `.env` loading
- `haversine` — GPS proximity scoring (`haversine(gps_a, gps_b, unit=Unit.METERS)`)

**Frontend:**
- `react-router-dom` 6.x — client routing
- `zustand` 4.x — lightweight state
- `date-fns` 3.x — "2 minutes ago" display in feed (tree-shakable)

**Pinned `requirements.txt`:**
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.18
pydantic==2.10.3
python-dotenv==1.0.1
twelvelabs==1.2.3
claude-agent-sdk==0.1.68
anthropic==0.39.0
numpy==2.1.3
httpx==0.27.2
aiosqlite
sse-starlette
haversine
```

## Configuration

**Environment:**
- Backend reads config from environment variables (via `python-dotenv` in development).
- Required backend vars:
  - `ANTHROPIC_API_KEY` — used by `claude-agent-sdk` and `anthropic` packages
  - `TWELVELABS_API_KEY` — used by `twelvelabs` SDK
  - `FRONTEND_URL` — used in CORS middleware (set after first Vercel deploy)
  - `DATA_DIR` — filesystem root for clip storage (Railway: `/data`; local: `./clips`)
  - `OFFLINE_DEMO` — set to `true` to serve cached embeddings + compile output without any external API calls
  - `USE_MOCK_EMBEDDINGS` — set to `true` to skip Marengo during development
- Frontend reads a single env var:
  - `VITE_API_BASE` — backend URL (e.g., `https://newz-api.up.railway.app`)

**Never embed API keys in the frontend bundle** — both `ANTHROPIC_API_KEY` and `TWELVELABS_API_KEY` are paid credentials and must live backend-only.

**Build:**
- Backend: `uvicorn main:app --reload --port 8000` (dev); `uvicorn main:app --host 0.0.0.0 --port $PORT` (prod)
- Frontend: `pnpm dev` (dev); `pnpm build` → `vercel --prod` (prod)
- Single entry point target: `make demo` — starts FastAPI + Vite, seeds DB, opens browser

## Platform Requirements

**Development:**
- Python 3.11 virtualenv
- Node 18+ with pnpm
- Two terminal processes: FastAPI on `:8000`, Vite on `:5173`
- HTTPS required for `getUserMedia` (camera) — `localhost` is exempt; use ngrok/Cloudflare Tunnel for real-device testing without prod deploy
- Real iPhone required for iOS Safari MediaRecorder verification — emulators lie

**Production:**
- Frontend: Vercel (static build of React/Vite SPA; CDN + HTTPS automatic)
- Backend: Railway (single-container Python service; persistent volume mounted at `/data` for clip storage)
- SQLite file lives in the Railway persistent volume — no Postgres, no external DB
- Clip files served via FastAPI `StaticFiles` from the same persistent volume

## Version Compatibility Notes

| Package | Constraint | Reason |
|---------|-----------|--------|
| `claude-agent-sdk` 0.1.68 | Sonnet/Haiku only | Opus 4.7 requires `>=0.2.111`; the two SDK lines have incompatible API surfaces |
| `twelvelabs` 1.2.3 | Python 3.8–3.12 | `marengo3.0` only; 2.7 dead |
| `numpy` 2.x | Python 3.10+ | If `faiss-cpu` ever added, it requires NumPy <2 — pin separately |
| Vite 5 | Node 18+ | Vite 6 also acceptable but less stable as of April 2026 |
| Python | 3.11 | 3.13 has patchy wheel support for some deps as of April 2026 |

---

*Stack analysis: 2026-04-24*
