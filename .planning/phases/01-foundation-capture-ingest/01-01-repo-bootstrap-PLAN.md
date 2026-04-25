---
phase: 01-foundation-capture-ingest
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .gitignore
  - README.md
  - Makefile
  - backend/requirements.txt
  - backend/.env.example
  - backend/pyproject.toml
  - backend/app.py
  - backend/config.py
  - backend/__init__.py
  - frontend/package.json
  - frontend/pnpm-lock.yaml
  - frontend/index.html
  - frontend/vite.config.ts
  - frontend/tsconfig.json
  - frontend/tsconfig.node.json
  - frontend/tailwind.config.ts
  - frontend/postcss.config.js
  - frontend/.env.example
  - frontend/src/main.tsx
  - frontend/src/App.tsx
  - frontend/src/index.css
  - frontend/src/views/Feed.tsx
  - frontend/src/views/Recorder.tsx
autonomous: true
requirements:
  - FND-01
  - FND-02
user_setup: []

must_haves:
  truths:
    - "Backend boots locally on port 8000 with /health returning 200"
    - "Frontend boots locally on port 5173 with two routes (/, /record) navigable"
    - "make dev (or equivalent) brings both processes up with one command"
    - "Tailwind 4 dark-first theme tokens render correctly on the feed shell"
  artifacts:
    - path: "backend/app.py"
      provides: "FastAPI app with /health route + lifespan + CORS"
      contains: "FastAPI(lifespan=lifespan)"
    - path: "backend/requirements.txt"
      provides: "Pinned Python deps"
      contains: "fastapi==0.115.6"
    - path: "frontend/package.json"
      provides: "React+Vite+TS+Tailwind 4 deps"
      contains: "tailwindcss"
    - path: "frontend/vite.config.ts"
      provides: "Vite config with React + Tailwind 4 plugin + dev proxy"
      contains: "@tailwindcss/vite"
    - path: "frontend/src/App.tsx"
      provides: "React Router with / and /record routes"
      contains: "/record"
    - path: "Makefile"
      provides: "Single dev command boots both services"
      contains: "dev:"
    - path: ".gitignore"
      provides: "Excludes node_modules, .venv, /data, .env, dist"
      contains: ".env"
  key_links:
    - from: "frontend/src/App.tsx"
      to: "react-router-dom"
      via: "BrowserRouter + Route components"
      pattern: "BrowserRouter|createBrowserRouter|<Route"
    - from: "frontend/vite.config.ts"
      to: "backend FastAPI :8000"
      via: "dev proxy"
      pattern: "proxy.*8000"
    - from: "backend/app.py"
      to: "CORSMiddleware"
      via: "FE origin allowlist"
      pattern: "CORSMiddleware"
---

<objective>
Stand up the empty repo: backend (FastAPI + Uvicorn + Python 3.11, pinned per STACK.md), frontend (React 18 + Vite + TS + Tailwind 4), root Makefile and .gitignore. End state: `make dev` brings up both services, /health returns 200, the FE shell renders a dark-themed feed route and a stub /record route, and React Router navigation works between them.

Purpose: Every other Phase 1 plan depends on this scaffold. Without a bootable repo there is nothing to build into.

Output: Bootable monorepo with FE and BE skeletons. No camera, no upload, no DB yet — those come in plans 02 and 04.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-foundation-capture-ingest/01-CONTEXT.md
@.planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md
@.planning/phases/01-foundation-capture-ingest/01-PATTERNS.md
@.planning/research/STACK.md
@.planning/research/ARCHITECTURE.md
@CLAUDE.md

<interfaces>
<!-- Greenfield repo. No existing interfaces. PATTERNS.md provides authoritative templates. -->

Pinned versions (STACK.md §"Installation", PATTERNS.md `backend/requirements.txt`):

Backend (`backend/requirements.txt` — Phase 1 minimum, defer twelvelabs/numpy/anthropic to plans in Phases 2+4):
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.18
pydantic==2.10.3
python-dotenv==1.0.1
aiosqlite==0.20.0
```

Frontend (`frontend/package.json` — runtime + dev):
- react@^18.3.1
- react-dom@^18.3.1
- react-router-dom@^6.26.0
- typescript@~5.5.0
- vite@^5.4.0
- @vitejs/plugin-react@^4.3.0
- tailwindcss@^4.0.0
- @tailwindcss/vite@^4.0.0

UI-SPEC color tokens (must be available as Tailwind utilities or CSS vars):
- bg base: #0A0A0A
- surface: #1A1A1A
- accent (red-500): #EF4444
- fg primary: #FAFAFA
- fg muted: #A3A3A3
- border: #262626

Two routes (PATTERNS.md frontend/src/App.tsx):
- `/` -> Feed (stub; Plan 03 fills it in)
- `/record` -> Recorder (stub; Plan 04 fills it in)
</interfaces>
</context>

<tasks>

<task type="auto" tdd="false">
  <name>Task 1: Backend scaffold (FastAPI + /health + CORS + Makefile + .gitignore)</name>
  <files>
    backend/requirements.txt
    backend/.env.example
    backend/__init__.py
    backend/app.py
    backend/config.py
    Makefile
    .gitignore
    README.md
  </files>
  <read_first>
    .planning/research/STACK.md (lines 336-381 — Installation, env vars, CORS)
    .planning/research/ARCHITECTURE.md (lines 78-108 — Recommended Project Structure)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 67-100 — backend/app.py skeleton, lines 242-260 — requirements.txt)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (entire file — to honor D-01..D-08 and S6 CORS allowlist)
    CLAUDE.md (stack hard-constraints, Python 3.11 sweet spot)
  </read_first>
  <action>
Create the backend Python package with the exact scaffolding below.

1. **`backend/requirements.txt`** — verbatim, pinned (no twelvelabs/numpy/anthropic in Phase 1):
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.18
pydantic==2.10.3
python-dotenv==1.0.1
aiosqlite==0.20.0
```

2. **`backend/.env.example`** — verbatim:
```
# Local dev defaults. Copy to backend/.env before running. Never commit .env.
FRONTEND_URL=http://localhost:5173
DATA_DIR=./data
OFFLINE_DEMO=false
# Phase 2+ (do not need values yet):
# TWELVELABS_API_KEY=
# ANTHROPIC_API_KEY=
```

3. **`backend/__init__.py`** — empty file (makes `backend` an importable package).

4. **`backend/config.py`** — load env via `python-dotenv`:
```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
OFFLINE_DEMO = os.environ.get("OFFLINE_DEMO", "false").lower() == "true"
```
The `OFFLINE_DEMO` flag is read here so Phase 5 (DEM-04) can wire the actual offline behavior without retrofitting config. Phase 1 reads it; no code branches on it yet.

5. **`backend/app.py`** — FastAPI app with /health, CORS, lifespan placeholder. DB init and routes for `/clips` / `/feed` land in Plan 02 — leave a TODO comment:
```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Plan 02 will call db.init() here.
    # Plan 02 will mount StaticFiles to serve clip files here.
    yield

app = FastAPI(title="Newz API", lifespan=lifespan)

# CORS allowlist per STACK.md §"CORS" + PATTERNS.md S6.
# FRONTEND_URL is the Vercel deploy origin in prod (Plan 05); localhost:5173 is dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"ok": True}
```

6. **`Makefile`** at repo root — one-command dev. Use tabs (Make requires real tabs):
```
.PHONY: dev backend frontend install

install:
	cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && pnpm install

backend:
	cd backend && .venv/bin/uvicorn backend.app:app --reload --port 8000 --app-dir ..

frontend:
	cd frontend && pnpm dev

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."
	@echo "Or use: (cd backend && .venv/bin/uvicorn backend.app:app --reload --port 8000 --app-dir ..) & (cd frontend && pnpm dev)"
```

(Note: a single `make dev` that backgrounds both is fragile; the two-terminal pattern is the documented hackathon norm. The README will spell this out.)

7. **`.gitignore`** at repo root — verbatim:
```
# Python
__pycache__/
*.pyc
.venv/
backend/.env
backend/data/

# Node
node_modules/
frontend/dist/
frontend/.env
frontend/.env.local

# OS
.DS_Store

# Hackathon clip storage (FND-04 persistent volume in prod; ./data locally)
data/
*.db
*.db-wal
*.db-shm

# Editors
.vscode/
.idea/
```

8. **`README.md`** at repo root — short hackathon-style README. Include:
   - One-paragraph description (pulled from CLAUDE.md project guide first paragraph).
   - "Local dev" section: `make install`, then `make backend` + `make frontend` in two terminals.
   - "Deploy" section: stub heading "see Plan 05" — Plan 05 fills in Vercel + Railway instructions and the iPhone QR-code gate.
   - Tech stack table mirroring CLAUDE.md `## Stack`.

**Verification:**
- `cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt` succeeds.
- `cd backend && .venv/bin/uvicorn backend.app:app --port 8000 --app-dir ..` boots without import errors.
- `curl http://localhost:8000/health` returns `{"ok":true}` with HTTP 200.
- `curl http://localhost:8000/health -H "Origin: http://localhost:5173" -i | grep -i "access-control-allow-origin"` returns the localhost origin (CORS preflight is implicit on simple GET; this check confirms the middleware is mounted).

Per CLAUDE.md "Verify Before Claiming": run the curl after starting uvicorn; do not claim success on import alone.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech && python3.11 -m venv backend/.venv && backend/.venv/bin/pip install -q -r backend/requirements.txt && backend/.venv/bin/python -c "from backend.app import app; print('OK', app.title)"</automated>
    <runtime>backend/.venv/bin/uvicorn backend.app:app --port 8000 --app-dir . &amp; sleep 2 &amp;&amp; curl -fsS http://localhost:8000/health | grep '"ok":true' &amp;&amp; kill %1</runtime>
  </verify>
  <acceptance_criteria>
    - `grep -q "fastapi==0.115.6" backend/requirements.txt` succeeds
    - `grep -q "aiosqlite==0.20.0" backend/requirements.txt` succeeds
    - `grep -q "FastAPI(title=\"Newz API\", lifespan=lifespan)" backend/app.py` succeeds
    - `grep -q "CORSMiddleware" backend/app.py` succeeds
    - `grep -q "config.FRONTEND_URL" backend/app.py` succeeds
    - `grep -q "OFFLINE_DEMO" backend/config.py` succeeds (Phase 5 hook present)
    - `grep -q '"ok": True' backend/app.py` succeeds
    - `grep -q "data/" .gitignore` succeeds
    - `grep -q "*.db" .gitignore` succeeds
    - `grep -q "backend/.env" .gitignore` succeeds
    - Makefile contains lines starting with `dev:`, `backend:`, `frontend:`, `install:` (`grep -E "^(dev|backend|frontend|install):" Makefile` returns 4 matches)
    - `curl http://localhost:8000/health` returns HTTP 200 with body containing `"ok":true` (proven by runtime verify command above)
  </acceptance_criteria>
  <done>FastAPI boots, /health returns 200 JSON, CORS middleware loaded, requirements pinned per STACK.md, Makefile + .gitignore + README in place. No DB or upload routes yet (Plan 02).</done>
</task>

<task type="auto" tdd="false">
  <name>Task 2: Frontend scaffold (Vite + React 18 + TS + Tailwind 4 + Router with /, /record)</name>
  <files>
    frontend/package.json
    frontend/index.html
    frontend/vite.config.ts
    frontend/tsconfig.json
    frontend/tsconfig.node.json
    frontend/tailwind.config.ts
    frontend/postcss.config.js
    frontend/.env.example
    frontend/src/main.tsx
    frontend/src/App.tsx
    frontend/src/index.css
    frontend/src/views/Feed.tsx
    frontend/src/views/Recorder.tsx
  </files>
  <read_first>
    .planning/research/STACK.md (lines 360-381 — Frontend install, env vars)
    .planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md (entire file — color tokens, typography, spacing scale, font stack)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 627-638 — vite.config.ts; line 31 — App.tsx routing)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (D-01, D-08 — FAB and feed shape)
  </read_first>
  <action>
Bootstrap the Vite SPA with React 18, TypeScript, Tailwind 4, and React Router 6. Use **plain pnpm** (`pnpm@9` or whatever the user has — do not pin pnpm version in the package.json itself).

1. **`frontend/package.json`** — verbatim:
```json
{
  "name": "newz-frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "@tailwindcss/vite": "^4.0.0",
    "tailwindcss": "^4.0.0",
    "typescript": "~5.5.0",
    "vite": "^5.4.0"
  }
}
```
Note `vite --host`: required so a real iPhone on the same Wi-Fi can hit the dev server (FND-03 hardware gate prep — Plan 05 leverages this).

2. **`frontend/vite.config.ts`** — proxy /api to FastAPI (per PATTERNS.md):
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
```

3. **`frontend/tsconfig.json`** — strict, modern target:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowImportingTsExtensions": false,
    "noEmit": true,
    "isolatedModules": true,
    "useDefineForClassFields": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

4. **`frontend/tsconfig.node.json`**:
```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "skipLibCheck": true,
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

5. **`frontend/tailwind.config.ts`** — Tailwind 4 uses CSS-first config but a small TS file is fine for `content` discovery glob:
```typescript
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
} satisfies Config;
```

6. **`frontend/postcss.config.js`** — empty/skip; Tailwind 4 via `@tailwindcss/vite` does not need PostCSS config. Create an empty stub to head off "missing config" errors from older tooling:
```javascript
export default { plugins: {} };
```

7. **`frontend/index.html`** — viewport-locked, dark, system font:
```html
<!doctype html>
<html lang="en" class="bg-[#0A0A0A]">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#0A0A0A" />
    <title>Newz</title>
  </head>
  <body class="bg-[#0A0A0A] text-[#FAFAFA]" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```
`viewport-fit=cover` is required for `env(safe-area-inset-*)` to return non-zero on iOS Safari (UI-SPEC §"iOS Safari constraints baked into the contract"). `theme-color` paints the address bar `#0A0A0A` — eliminates the dark-on-light flash on iOS.

8. **`frontend/.env.example`**:
```
VITE_API_BASE=http://localhost:8000
```

9. **`frontend/src/index.css`** — Tailwind 4 single-line import + dvh-friendly base:
```css
@import "tailwindcss";

html, body, #root {
  background: #0A0A0A;
  color: #FAFAFA;
  margin: 0;
  min-height: 100dvh;
}
```
`100dvh` is mandatory (UI-SPEC interaction contract). Do not use `100vh`.

10. **`frontend/src/main.tsx`**:
```typescript
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```

11. **`frontend/src/App.tsx`** — two routes:
```typescript
import { Routes, Route } from "react-router-dom";
import { Feed } from "./views/Feed";
import { Recorder } from "./views/Recorder";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Feed />} />
      <Route path="/record" element={<Recorder />} />
    </Routes>
  );
}
```

12. **`frontend/src/views/Feed.tsx`** — stub. Plan 03 replaces this with the real feed shell + RecordFAB + EmptyState. Phase-1 scope means no AI, no SSE.
```typescript
import { Link } from "react-router-dom";

export function Feed() {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] text-[#FAFAFA] flex flex-col items-center justify-center p-6">
      <p className="text-[#A3A3A3] text-base">Plan 03 will build the feed here.</p>
      <Link
        to="/record"
        className="mt-6 px-6 py-3 rounded-full bg-[#EF4444] text-white font-semibold"
      >
        Go to /record
      </Link>
    </div>
  );
}
```

13. **`frontend/src/views/Recorder.tsx`** — stub. Plan 04 replaces this with MediaRecorder + MIME ladder + GPS + retake screen.
```typescript
import { Link } from "react-router-dom";

export function Recorder() {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] text-[#FAFAFA] flex flex-col items-center justify-center p-6">
      <p className="text-[#A3A3A3] text-base">Plan 04 will build the camera here.</p>
      <Link to="/" className="mt-6 underline text-[#FAFAFA]">Back to feed</Link>
    </div>
  );
}
```

**Install + verify:**
- `cd frontend && pnpm install` (creates pnpm-lock.yaml; that file should be committed but is not in files_modified — it is generated, allow it).
- `cd frontend && pnpm build` succeeds (catches Tailwind 4 config errors at build time).
- `cd frontend && pnpm dev` starts Vite on :5173.
- Open http://localhost:5173 — see "Plan 03 will build the feed here." on a `#0A0A0A` background.
- Click "Go to /record" — URL changes to /record, see Recorder stub.

Per CLAUDE.md: do not skip the `pnpm build` step. A type error or Tailwind misconfig will only surface at build time.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm install --silent &amp;&amp; pnpm build 2&gt;&amp;1 | tail -20</automated>
    <runtime>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; (pnpm dev --port 5173 &amp; sleep 4 &amp;&amp; curl -fsS http://localhost:5173/ | grep -E "(Plan 03|root|Newz)" &amp;&amp; kill %1)</runtime>
  </verify>
  <acceptance_criteria>
    - `grep -q '"react": "\^18' frontend/package.json` succeeds
    - `grep -q '"tailwindcss": "\^4' frontend/package.json` succeeds
    - `grep -q '"react-router-dom"' frontend/package.json` succeeds
    - `grep -q "@tailwindcss/vite" frontend/vite.config.ts` succeeds
    - `grep -q "proxy.*8000" frontend/vite.config.ts` succeeds
    - `grep -q "viewport-fit=cover" frontend/index.html` succeeds
    - `grep -q "100dvh" frontend/src/index.css` succeeds
    - `grep -q "BrowserRouter" frontend/src/main.tsx` succeeds
    - `grep -q 'path="/record"' frontend/src/App.tsx` succeeds
    - `grep -q '#0A0A0A' frontend/src/views/Feed.tsx` succeeds (theme tokens applied)
    - `cd frontend && pnpm build` exits 0 (proven by automated verify)
    - Dev server response at `/` includes the root div (proven by runtime verify)
  </acceptance_criteria>
  <done>Vite + React 18 + TS + Tailwind 4 boots cleanly. Two routes resolve. Dark-first theme tokens applied to stubs. Build succeeds without TS or Tailwind errors.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| dev environment | All code runs on developer laptop; no remote untrusted input in this plan |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-01 | I (Information disclosure) | `backend/.env`, `frontend/.env` | mitigate | `.gitignore` excludes `backend/.env`, `frontend/.env`, `frontend/.env.local`. `.env.example` is the only committed env file and contains no secrets. |
| T-01-02 | T (Tampering) | `backend/data/`, `*.db` | mitigate | `.gitignore` excludes `data/` and `*.db*` so SQLite + clip files never enter git history. |
| T-01-03 | I (Information disclosure) | CORS allow-origins | mitigate | `allow_origins=[FRONTEND_URL, "http://localhost:5173"]` — explicit allowlist, never `["*"]` with `allow_credentials=True`. Plan 05 will set `FRONTEND_URL` to the prod Vercel origin. |
| T-01-04 | D (Denial of service) | `/health` endpoint | accept | Health endpoint has no DB or external IO — trivially cheap. Rate limiting added in Plan 02 if needed. |
</threat_model>

<verification>
- `make install` from a fresh clone produces a working `.venv` and `node_modules`.
- `make backend` then `curl http://localhost:8000/health` returns 200 with `{"ok": true}`.
- `make frontend` then opening `http://localhost:5173/` shows the Feed stub on `#0A0A0A`.
- Navigating to `/record` shows the Recorder stub.
- `git status` after the plan shows no committed `.env`, `.venv/`, `node_modules/`, `data/`, or `*.db` files.
</verification>

<success_criteria>
- FND-01: `curl http://localhost:8000/health` returns 200.
- FND-02: `pnpm dev` brings up Vite, both `/` and `/record` render the dark-themed stubs.
- Repo bootable end-to-end with `make install` + two `make` commands.
- Tailwind 4 config builds without warnings.
- Phase 5 hook present: `OFFLINE_DEMO` env var read in `backend/config.py`.
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-capture-ingest/01-01-SUMMARY.md` with:
- What was built (file list, line counts)
- Versions installed (`.venv/bin/pip freeze | head -20`, `pnpm list --depth=0`)
- One-line proof: the curl + pnpm dev outputs
- Anything that diverged from the plan and why
</output>
