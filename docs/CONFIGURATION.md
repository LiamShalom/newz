<!-- generated-by: gsd-doc-writer -->
# Configuration

Environment variables and tunables for the Newz monorepo. The backend (FastAPI on Railway) and frontend (Vite/React on Vercel) read configuration independently — backend values are loaded in `backend/config.py`; frontend values must be prefixed `VITE_` and are baked at build time.

For deploy ordering and CORS wiring see the [README](../README.md). For the hardware-gate checklist see [docs/IPHONE-GATE.md](IPHONE-GATE.md).

## Backend env vars

All backend configuration is centralized in `backend/config.py`. Defaults make local dev work with no `.env` file; production overrides are set in the Railway dashboard.

Local dev: copy `backend/.env.example` -> `backend/.env`. `python-dotenv` loads `.env` at process start (`backend/config.py:5`).

| Variable | Type | Default | Purpose | Consumed at |
| --- | --- | --- | --- | --- |
| `FRONTEND_URL` | string (URL) | `http://localhost:5173` | CORS allow-origin for the Vercel frontend. Required in production or browser fetches fail. | `backend/config.py:7`, `backend/app.py:85` |
| `DATA_DIR` | path | `./data` (resolved) | Root directory for SQLite db (`newz.db`) and clip filesystem (`clips/`). On Railway must point at the mounted volume (`/data`) or redeploys wipe uploads. | `backend/config.py:8`, `backend/db.py:15-16`, `backend/app.py:91-93` |
| `TWELVELABS_API_KEY` | string (secret) | `""` (empty) | API key for Twelve Labs Marengo 3.0 embeddings. Required for production. | `backend/config.py:11`, `backend/pipeline/run.py:14`, `backend/pipeline/embed.py:55` |
| `PRE_WARM_CLIP_PATH` | path | `backend/seed/prewarm.mp4` | Path to a throwaway clip Marengo embeds at startup to pay cold-start latency before the first real clip. Skipped silently if file is missing. | `backend/config.py:12-14`, `backend/app.py:23-31` |
| `CLUSTER_THRESHOLD` | float | `0.55` | Composite-score cutoff above which a clip joins an existing cluster. See **Tunables**. | `backend/config.py:19`, `backend/pipeline/cluster.py:148`, `backend/app.py:222` |
| `VISUAL_FLOOR` | float | `0.80` | Marengo cosine floor a clip must clear vs. cluster centroid before composite is even considered. Prevents GPS+time-only fusion (CLU-08). See **Tunables**. | `backend/config.py:23`, `backend/pipeline/cluster.py:143`, `backend/app.py:223` |
| `ANTHROPIC_API_KEY` | string (secret) | unset | Anthropic key for Claude Agent SDK compile pipeline. If unset, compile is disabled (logged as warning); ingest + clustering still work. Not declared in `config.py` — read directly via `os.environ`. | `backend/app.py:49`, `backend/pipeline/caption_pipeline.py:107` |
| `PORT` | int | `8000` | Bind port for uvicorn. Railway injects this at runtime; the Dockerfile honors it via `${PORT:-8000}`. | `backend/Dockerfile:20`, `backend/Procfile:1` |

### Required vs optional (production)

The container will start with no env vars set, but the demo will be broken in specific ways:

- **Required for any production deploy:** `FRONTEND_URL` (CORS), `DATA_DIR=/data` (volume persistence), `TWELVELABS_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.
- **Optional everywhere else:** `PRE_WARM_CLIP_PATH`, `CLUSTER_THRESHOLD`, `VISUAL_FLOOR`, `RUN_THRESHOLD`, `MAX_RUN_MEMBERS` — all have sensible defaults.

## Frontend env vars

Vite only exposes vars prefixed `VITE_` to client code (`import.meta.env.*`). They are inlined at `pnpm build` time — changing one requires a redeploy.

Local dev: copy `frontend/.env.example` -> `frontend/.env`. Production: set in Vercel Project Settings -> Environment Variables (see `frontend/.env.production.example`).

| Variable | Type | Default | Purpose | Consumed at |
| --- | --- | --- | --- | --- |
| `VITE_API_BASE` | string (URL) | `http://localhost:8000` (fallback in source) | Base URL of the FastAPI backend. In production: the Railway public URL. | `frontend/src/api.ts:7` |

That is the only frontend env var. All other configuration is hardcoded in source.

## Config files (non-env)

These are not env vars but they govern runtime behavior alongside `config.py`:

- `backend/Dockerfile` — Python 3.11-slim, installs `ffmpeg`, runs `uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir .`.
- `backend/railway.toml` and `backend/railway.json` — `DOCKERFILE` builder, healthcheck `GET /health` with 30s timeout, `ON_FAILURE` restart policy (max 5 retries).
- `backend/Procfile` — alternate uvicorn invocation; <!-- VERIFY: which Procfile vs. Dockerfile actually runs on Railway given the project uses DOCKERFILE builder -->.
- `frontend/vercel.json` — `pnpm install --frozen-lockfile && pnpm build`, output `dist`, SPA rewrite `/(.*) -> /index.html`.

## Tunables (calibrated demo values)

Three variables are calibrated against the staged demo dataset. Hackathon judges may want to inspect or override them live; surface them on the Phase 3 debug overlay rather than hiding behind a redeploy.

### `CLUSTER_THRESHOLD` (default `0.55`)

Composite-score threshold. Composite is `0.55 x Marengo cosine + 0.30 x GPS proximity + 0.15 x time proximity` — see `backend/pipeline/cluster.py:18`. A clip whose best-match cluster scores `>= 0.55` joins that cluster; otherwise it seeds a new one.

- Lower it (e.g., `0.45`) -> looser clusters, more clips merged, higher false-positive rate.
- Raise it (e.g., `0.65`) -> tighter clusters, more singletons, risk of demo-killing under-clustering.
- Calibration notebook lives under `backend/notebooks/` <!-- VERIFY: notebook filename and current calibration value at demo time -->.

### `VISUAL_FLOOR` (default `0.80`)

Hard floor on Marengo visual cosine. Even if GPS + time push composite over `CLUSTER_THRESHOLD`, the clip must agree visually with the cluster centroid (>= 0.80) to fuse. Prevents the adversarial case where two unrelated clips at the same intersection get merged because GPS+time alone clear the threshold (CLU-08).

Don't lower this below `0.70` without re-running the calibration notebook against the staged dataset.

## Per-environment overrides

| Environment | Backend | Frontend |
| --- | --- | --- |
| Local dev | `backend/.env` (gitignored) | `frontend/.env.local` or `frontend/.env` |
| Production | Railway dashboard env vars | Vercel Project Settings -> Environment Variables (Production scope) |

There is no `.env.staging`, `.env.production` file checked into the repo for the backend — production values live only in the Railway dashboard. Frontend ships `.env.example` and `.env.production.example` as templates only; neither is loaded at runtime.

Changing a frontend env var requires `pnpm dlx vercel --prod` (or a dashboard redeploy) — Vite inlines `import.meta.env.*` at build time. Backend env changes take effect on the next Railway redeploy <!-- VERIFY: whether Railway hot-restarts on env-var change vs. requires manual redeploy -->.
