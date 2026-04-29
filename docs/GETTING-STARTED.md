<!-- generated-by: gsd-doc-writer -->
# Getting Started

First-run guide for a teammate cloning Newz. Goal: backend running on `:8000`, frontend on `:5173`, and you can record a clip on your phone and see it land in the feed.

For a higher-level overview see [README.md](../README.md). For env-var details see [docs/CONFIGURATION.md](./CONFIGURATION.md). For what's actually running under the hood see [docs/ARCHITECTURE.md](./ARCHITECTURE.md).

## Prerequisites

- **Python 3.11** (the `Makefile` calls `python3.11` explicitly; the backend `Dockerfile` pins `python:3.11-slim`)
- **Node 18+** and **pnpm** (the `frontend/vite.config.ts` + `frontend/package.json` are pnpm-locked via `pnpm-lock.yaml`)
- **ffmpeg is NOT required system-wide** — `imageio-ffmpeg` ships a bundled binary used by the compile pipeline
- `TWELVELABS_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` for the live pipeline. Without `TWELVELABS_API_KEY` the embed stage will fail; without `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` compile will fall back to a generic caption.

## Clone & install

```bash
git clone <this repo>
cd Hacktech
make install
```

`make install` does both halves:

- `cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- `cd frontend && pnpm install`

## Backend setup

1. Create `backend/.env` from `backend/.env.example`. Populate using [docs/CONFIGURATION.md](./CONFIGURATION.md):

   ```bash
   # backend/.env
   FRONTEND_URL=http://localhost:5173
   DATA_DIR=./data
   TWELVELABS_API_KEY=...
   ANTHROPIC_API_KEY=...
   GEMINI_API_KEY=...
   ```

2. Run the backend:

   ```bash
   make backend
   ```

   This runs `uvicorn backend.app:app --reload --port 8000`.

3. Smoke test:

   ```bash
   curl http://localhost:8000/health
   # {"ok":true}
   ```

   Startup logs `Marengo pre-warm complete latency_ms=...`.

## Frontend setup

1. Create `frontend/.env` (or `.env.local`). For local dev pointed at the local backend the only var is `VITE_API_BASE`:

   ```bash
   # frontend/.env
   VITE_API_BASE=http://localhost:8000
   ```

   You can omit the file entirely — `frontend/src/api.ts:7` falls back to `http://localhost:8000`.

2. Run the dev server:

   ```bash
   make frontend
   ```

   This is `cd frontend && pnpm dev`, which runs `vite --host` so a real iPhone on the same Wi-Fi can reach `http://<your-laptop-LAN-ip>:5173` (required for the iPhone gate — see below).

3. Open `http://localhost:5173`. The feed will be empty until clips are ingested.

## End-to-end smoke test

With both servers running:

1. Open `http://localhost:5173` in a browser. The feed starts empty.
2. Tap the red FAB → record a 3-5s clip → "Post clip". The browser POSTs `multipart/form-data` to `http://localhost:8000/clips`.
3. Backend logs show: `clip_added` → embed (`stage: embedded`) → cluster (`cluster_assigned` with score breakdown) → if `member_count >= 2`, compile.
4. Verify directly:

   ```bash
   curl http://localhost:8000/feed | jq '.segments | length'
   curl http://localhost:8000/debug/dbstate
   ```

5. The Feed view's `useEventSource` hook (`frontend/src/hooks/useEventSource.ts`) catches `cluster_assigned` / `segment_published` and re-fetches `/feed` automatically — no refresh needed.

## Common gotchas

- **No `.env.example` files.** README mentions them but they don't exist. Populate `backend/.env` and `frontend/.env` by hand from [docs/CONFIGURATION.md](./CONFIGURATION.md).
- **iOS Safari is the demo target.** Localhost desktop testing is fine for plumbing; the actual record path needs a real iPhone on Safari, on a different network than your laptop, against the **deployed** Vercel + Railway URLs. See [docs/IPHONE-GATE.md](./IPHONE-GATE.md). MIME-type fallback ladder (`mp4;avc1 → webm;vp9 → webm → no mimeType`) is required and lives in the recorder code.
- **Indoor GPS at Caltech is unreliable.** GPS weight collapses to `0.0` when unavailable; clustering still works on visual+time. The `?demo_location=` override (DEM-05) is the documented escape hatch.
- **Marengo cold-start kills demos.** Pre-warm fires once at startup against `backend/seed/prewarm.mp4`; if that file is missing pre-warm is skipped silently and your first real clip pays the 5-30s cold-start tax. Don't delete the seed file.
- **Compile is gated on `ANTHROPIC_API_KEY`.** Without it, ingest + clustering still work but compile logs a warning and falls back to a generic AP-wire caption. This is the documented degraded path, not a bug.
- **CORS trailing-slash trap.** `FRONTEND_URL` is exact-match (`backend/app.py:85`). A trailing slash breaks preflight. This was the root cause of two iPhone-gate failures (see [docs/IPHONE-GATE.md](./IPHONE-GATE.md) resolution log).
- **Vite env vars are baked at build time.** Changing `VITE_API_BASE` requires a redeploy (`pnpm dlx vercel --prod`) — not a hot reload.

## Next steps

- Run the backend tests: `cd backend && .venv/bin/pytest` (suite covers cluster, compile, SSE, feed, segments).
- Run the frontend tests: `cd frontend && pnpm test`.
- Read [docs/ARCHITECTURE.md](./ARCHITECTURE.md) for the embed → cluster → compile pipeline and SSE fan-out.
- Read [docs/CONFIGURATION.md](./CONFIGURATION.md) for every tunable and what flipping it does.
- Before any deploy, run [docs/IPHONE-GATE.md](./IPHONE-GATE.md) on a real iPhone against the deployed URLs.
