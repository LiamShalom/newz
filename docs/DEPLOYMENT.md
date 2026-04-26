<!-- generated-by: gsd-doc-writer -->
# Deployment

How Newz is deployed for the HackTech demo. Two services, two providers, one cross-domain SSE link. For env-var detail see [docs/CONFIGURATION.md](CONFIGURATION.md). For the iPhone hardware gate see [docs/IPHONE-GATE.md](IPHONE-GATE.md).

## Topology

```
                    ┌─────────────────────────────┐
                    │  iPhone Safari (HTTPS req)  │
                    └──────────────┬──────────────┘
                                   │
            ┌──────────────────────┴──────────────────────┐
            │                                             │
            ▼                                             ▼
   ┌────────────────────┐                    ┌────────────────────────┐
   │   Vercel (CDN)     │   fetch + SSE      │  Railway (container)   │
   │  React+Vite SPA    │ ─────────────────▶ │  FastAPI + Uvicorn     │
   │  frontend/dist     │   credentials:     │  backend.app:app       │
   │  VITE_API_BASE ──▶ │   include          │                        │
   └────────────────────┘                    │  Volume: /data         │
                                             │   ├─ newz.db (sqlite)  │
                                             │   └─ clips/*.mp4       │
                                             └────────────────────────┘
```

- **Frontend:** Vercel static deploy of `frontend/dist`. Build = `pnpm install --frozen-lockfile && pnpm build` (`frontend/vercel.json:3`). SPA rewrite `/(.*) -> /index.html` (`frontend/vercel.json:7`). The Railway origin is baked into the bundle at build time via `VITE_API_BASE` (`frontend/src/api.ts:7`).
- **Backend:** Railway container built from `backend/Dockerfile` (python:3.11-slim + ffmpeg, line 6). Healthcheck `GET /health` with 30s timeout, restart `ON_FAILURE` max 5 retries (`backend/railway.toml:6-9`). Public URL: `https://newz-production.up.railway.app` (referenced by `docs/IPHONE-GATE.md:10`). <!-- VERIFY: that this URL is the canonical production hostname and not a stale preview -->
- **CORS + SSE:** Backend trusts only `FRONTEND_URL` + `localhost:5173` (`backend/app.py:85`); `allow_credentials=True` so the browser keeps the SSE connection open across the origin boundary (`backend/app.py:86`).

## First-time deploy

The **order matters** — both sides need the other's URL before CORS works. Plan on two redeploys per side.

### 1. Backend (Railway)

1. https://railway.app/new → "Deploy from GitHub repo" → pick this repo. Service root directory: `backend/`. <!-- VERIFY: exact Railway dashboard path for setting service root directory -->
2. Railway auto-detects `backend/Dockerfile` because `backend/railway.toml` declares `builder = "DOCKERFILE"` (line 2). No buildpack involved.
3. Attach a Volume (see "Persistent volume setup" below) **before** the first deploy completes — the first uploaded clip will write to `${DATA_DIR}/clips/` and you want that on the volume.
4. Set env vars (Railway dashboard → Variables):
   - `DATA_DIR=/data` — must match the volume mount path or sqlite + clips land on the ephemeral container FS.
   - `FRONTEND_URL=<vercel url>` — fill after step 2 below; placeholder `http://localhost:5173` will work for the first boot.
   - `OFFLINE_DEMO=false`
   - `TWELVELABS_API_KEY=<secret>` and `ANTHROPIC_API_KEY=<secret>` — see `docs/CONFIGURATION.md`.
5. Wait for healthcheck `GET /health` to flip green (`backend/app.py:96`). Copy the public URL.

### 2. Frontend (Vercel)

1. From `frontend/`: `pnpm dlx vercel link` (or "New Project" on https://vercel.com/new). **Project Root must be `frontend/`** — `frontend/vercel.json` only resolves there. <!-- VERIFY: Vercel auto-detection picks `frontend/` correctly without manual override -->
2. First deploy: `pnpm dlx vercel --prod`. Copy the URL.

### 3. Wire env vars (the second redeploy)

1. **Vercel** → Project Settings → Environment Variables → add `VITE_API_BASE=<railway url from step 1>` for Production scope. Vite inlines this at build time (`frontend/src/api.ts:7`); changing it requires a rebuild.
2. **Railway** → Variables → set `FRONTEND_URL=<vercel url from step 2>`. Railway redeploys on env-var change. <!-- VERIFY: Railway hot-restarts on env-var update vs. requires manual redeploy -->
3. Redeploy the frontend so the new `VITE_API_BASE` is baked: `pnpm dlx vercel --prod`.

### 4. CORS sanity check

```bash
curl -I -H "Origin: $FRONTEND_URL" $BACKEND_URL/health | grep -i access-control
```

Response must include `access-control-allow-origin: $FRONTEND_URL`. If missing, the Railway env-var change in step 3.2 didn't roll into the running container — kick a manual redeploy from the Railway dashboard.

### 5. iPhone gate

Deploy is not "done" until `docs/IPHONE-GATE.md` records a PASS on a real iPhone, on a different network than the dev laptop.

## Updating a deploy

- **Push to `main`** = both providers auto-deploy. Vercel rebuilds via `vercel.json` (`pnpm install --frozen-lockfile && pnpm build`). Railway rebuilds via `Dockerfile`. <!-- VERIFY: both Vercel and Railway are wired to auto-deploy on push to main, and which branch each watches -->
- **Env-var only change:** Vercel redeploy required (Vite inlines at build time). Railway picks up env changes on its next restart.
- **Rollback:**
  - Vercel: dashboard → Deployments → "Promote to Production" on a known-good build.
  - Railway: dashboard → Deployments → "Redeploy" on a prior successful build. <!-- VERIFY: exact Railway rollback UI affordance and whether it preserves the volume -->

## Persistent volume setup

The backend writes two things to `DATA_DIR`:

- `${DATA_DIR}/newz.db` — SQLite (WAL mode) (`backend/db.py:15`)
- `${DATA_DIR}/clips/` — uploaded clip blobs, served via `/media` static mount (`backend/app.py:93`)

If `DATA_DIR` is the ephemeral container FS, both vanish on every restart/redeploy.

**Required Railway config:**

1. Railway dashboard → service → Volumes panel → "New Volume". <!-- VERIFY: exact panel name in current Railway UI -->
2. Mount path: `/data`.
3. Set env var `DATA_DIR=/data` so `backend/config.py:8` resolves to the mounted volume.
4. Redeploy. The container's `mkdir -p /data/clips` runs at app start (`backend/app.py:91-92`).

> **Known issue (2026-04-25):** the volume mount is currently NOT working in production — clips and the sqlite db wipe on every container restart. Suspected causes: (a) the Volume is attached but the mount path doesn't match `DATA_DIR`, (b) `DATA_DIR` env var was never set in the Railway dashboard, or (c) the vision compile step OOMs the container often enough that the user-visible symptom looks like data loss. Diagnose with the checklist below before assuming a Railway-platform bug.

## Operational runbook

All paths below assume `BACKEND_URL=https://newz-production.up.railway.app`.

| Action | Command / location |
| --- | --- |
| Check liveness | `curl $BACKEND_URL/health` → `{"ok": true}` (`backend/app.py:96`) |
| Inspect current segments | `curl "$BACKEND_URL/feed"` (`backend/app.py:138`) |
| Inspect cluster internals | `curl $BACKEND_URL/debug/clusters` — per-cluster member breakdown + composite scores (`backend/app.py:176`). Hidden from OpenAPI; do not expose to authenticated public traffic. |
| Watch live SSE stream | `curl -N $BACKEND_URL/events` — server-sent events; pings every 15s (`backend/app.py:173`). One EventSource per browser tab. |
| Tail container logs | Railway dashboard → service → Deployments → "View Logs". <!-- VERIFY: Railway log access path in current UI --> |
| Open container shell | Railway dashboard → service → "Shell" or `railway shell` via CLI. <!-- VERIFY: whether the Railway "Shell" feature is enabled on this project's plan --> |
| Force a restart | Railway dashboard → service → "Restart" (preserves the volume; only re-runs the entrypoint). <!-- VERIFY: Restart vs. Redeploy semantics for volume preservation --> |

## Restart-survives-volume? diagnostic checklist

Run this when uploaded clips disappear after a Railway redeploy or restart. Goal: prove whether `/data` is actually persistent.

1. **Before restart** — open Railway shell on the live container:
   ```bash
   ls -la /data            # expect: clips/  newz.db
   du -sh /data/clips      # record size
   sqlite3 /data/newz.db 'SELECT COUNT(*) FROM clips;'   # record count
   ```
2. **Capture** the `/feed` payload from outside:
   ```bash
   curl -s $BACKEND_URL/feed | jq '.segments | length'
   ```
3. **Force a restart** (Railway dashboard → service → "Restart" — NOT "Redeploy", which rebuilds the image).
4. **After restart** — re-run the same three commands from step 1 in a fresh shell, then re-curl `/feed`.
5. **Compare:**
   - File counts under `/data/clips/` identical → volume is mounted, data persists.
   - File counts went to 0 / `newz.db` is missing → volume is **not** mounted at `/data`. Check `DATA_DIR` env var matches the volume mount path exactly. <!-- VERIFY: Railway "Restart" preserves the volume; if it re-creates the container with a fresh volume, this test won't distinguish mount-bug from restart-policy-bug -->
   - Files persist but `/feed` is empty after restart → not a volume issue; check the in-memory `CLUSTERS` rebuild from sqlite (`backend/app.py:70-71`, `backend/pipeline/cluster.rebuild_cache`).
6. **Tail logs during the restart** for `OOMKilled` / SIGKILL — if the vision step is OOMing, restarts will be frequent and the user-visible symptom looks like data loss even when the volume is fine. <!-- VERIFY: current Railway plan memory limit and whether the vision caption step exceeds it -->

## Known issues

- **Volume not persisting across restarts (2026-04-25).** See "Persistent volume setup" + diagnostic checklist above. Until resolved, the demo cannot rely on overnight clip retention; re-seed via `backend/seed/demo_segment.py` after every restart (`backend/app.py:73`).
- **Cold-start latency on Marengo first call (5-30s).** Mitigated by `_pre_warm_marengo` at lifespan startup (`backend/app.py:23`, `app.py:76`) — but if `seed/prewarm.mp4` is missing the warmup is silently skipped. Verify the file shipped in the Docker image.
- **`OFFLINE_DEMO=true` is the documented WiFi-failure fallback.** If hackathon WiFi dies mid-demo, set on Railway and redeploy — Claude SDK pre-warm + downstream live calls are skipped (`backend/app.py:46`). See `CONFIGURATION.md` "Tunables".
- **`Procfile` is shipped alongside `Dockerfile`.** Railway uses the Dockerfile (per `railway.toml`); the `Procfile` is dev-only and won't be honored in production. <!-- VERIFY: Railway never falls back to Procfile when Dockerfile build fails -->
