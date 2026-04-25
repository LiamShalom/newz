# Newz

AI-native local news from anonymous crowdsourced footage. Hackathon MVP, HackTech (Caltech) April 24-26, 2026. Co-founders: Liam, Roan, Claude.

Anonymous, GPS-tagged short clips → Twelve Labs Marengo 3.0 multimodal embeddings → composite-score event clustering → Claude Agent SDK multi-agent compile → hyperlocal feed. Every user is journalist and audience; there is no creator/consumer split.

## Local dev

Requires Python 3.11, Node 18+, pnpm.

```bash
make install
```

Then in two terminals:

```bash
make backend   # FastAPI on :8000 (http://localhost:8000/health)
```

```bash
make frontend  # Vite on :5173 (http://localhost:5173)
```

The Vite dev server is started with `--host` so a real iPhone on the same Wi-Fi can hit it (required for the Phase 5 iPhone gate).

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env` before first run.

## Deploy

Frontend on Vercel (HTTPS, FND-05). Backend on Railway with a persistent volume mounted at `/data` (FND-04). The two services talk over CORS — set the env vars below on the **second** deploy of each side, in the order given. Hardware verification lives in [docs/IPHONE-GATE.md](docs/IPHONE-GATE.md).

### 1. Vercel (frontend)

1. From repo root: `pnpm dlx vercel link` (or "New Project" -> connect repo on https://vercel.com/new). Project root = repo root; the build command in `vercel.json` does the `cd frontend` for you.
2. First deploy: `pnpm dlx vercel --prod`. Copy the URL (e.g. `https://newz-xyz.vercel.app`). Skip env var for now — we don't have the Railway URL yet.

### 2. Railway (backend)

1. https://railway.app/new -> "Deploy from GitHub repo" -> pick this repo. Service root directory: `backend/`.
2. Attach a Volume: name `data`, mount path `/data`. (Without it, redeploys wipe `${DATA_DIR}/clips/` and uploaded clips disappear.)
3. Set environment variables:
   - `DATA_DIR=/data`
   - `FRONTEND_URL=<vercel url from step 1>`
   - `OFFLINE_DEMO=false`
4. Wait for the first deploy. Railway picks up `backend/Dockerfile` (python:3.11-slim) and `backend/railway.toml` (healthcheck `/health`). Copy the public URL (e.g. `https://newz-api.up.railway.app`).

### 3. Wire Vercel -> Railway

1. Vercel Project Settings -> Environment Variables -> add `VITE_API_BASE=<railway url from step 2>` for Production.
2. Redeploy: `pnpm dlx vercel --prod` (or via the dashboard). The new bundle hardcodes the Railway origin at build time.

### 4. CORS sanity check

CORS misconfiguration is the #1 cause of broken FE/BE-split demos. Verify after both URLs exist:

```bash
curl -I -H "Origin: $FRONTEND_URL" $BACKEND_URL/health | grep -i access-control
```

The response **must** include `access-control-allow-origin: $FRONTEND_URL`. If it does not, the Railway redeploy after step 2.3 didn't fire — kick the backend redeploy from the Railway dashboard so the new `FRONTEND_URL` is in the running container's env.

### 5. iPhone hardware gate

The deploy is not complete until [docs/IPHONE-GATE.md](docs/IPHONE-GATE.md) records a PASS. The gate must run on a real iPhone (not Chrome DevTools, not an emulator) on Safari, on a different network than the dev laptop. This closes Pitfall #3 (KILL-DEMO).

## Stack

| Layer            | Tool                                                                        |
| ---------------- | --------------------------------------------------------------------------- |
| Frontend         | React 18 + Vite + TypeScript + Tailwind 4 (Vercel)                          |
| Backend          | FastAPI + Uvicorn (Python 3.11) on Railway with persistent volume           |
| Video AI         | Twelve Labs `marengo3.0` via `twelvelabs==1.2.3` (512-d multimodal vectors) |
| Multi-agent AI   | Anthropic `claude-agent-sdk==0.1.68`                                        |
| Storage          | SQLite (aiosqlite, WAL) + local FS for clips                                |
| Vector search    | NumPy in-memory cosine over normalized 512-d vectors                        |

## Scope

Phase 1 (this milestone): bootable monorepo + iOS Safari camera + clip upload + raw feed playback. No AI yet — that lands in Phase 2.
