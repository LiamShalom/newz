---
phase: 01-foundation-capture-ingest
plan: 01
subsystem: foundation
tags: [scaffold, fastapi, vite, react, tailwind4, monorepo]
requires: []
provides:
  - bootable-monorepo
  - fastapi-app-with-health
  - vite-react-spa-with-router
  - dark-theme-tokens
affects:
  - all-future-phase-1-plans
tech-stack:
  added:
    - fastapi==0.115.6
    - uvicorn[standard]==0.32.1
    - python-multipart==0.0.18
    - pydantic==2.10.3
    - python-dotenv==1.0.1
    - aiosqlite==0.20.0
    - react@18.3.1
    - react-dom@18.3.1
    - react-router-dom@6.30.3
    - "@tailwindcss/vite@4.2.4"
    - tailwindcss@4.2.4
    - typescript@5.5.4
    - vite@5.4.21
  patterns:
    - fire-and-forget pipeline shape (lifespan placeholder for Plan 02 db.init)
    - dotenv-loaded backend config with Phase 5 OFFLINE_DEMO hook
    - Vite dev proxy /api -> :8000
    - dark-first Tailwind 4 theme tokens via inline hex (#0A0A0A / #1A1A1A / #EF4444 / #FAFAFA / #A3A3A3 / #262626)
key-files:
  created:
    - backend/__init__.py
    - backend/app.py
    - backend/config.py
    - backend/requirements.txt
    - backend/.env.example
    - frontend/package.json
    - frontend/pnpm-lock.yaml
    - frontend/vite.config.ts
    - frontend/tsconfig.json
    - frontend/tsconfig.node.json
    - frontend/tailwind.config.ts
    - frontend/postcss.config.js
    - frontend/index.html
    - frontend/.env.example
    - frontend/src/main.tsx
    - frontend/src/App.tsx
    - frontend/src/index.css
    - frontend/src/views/Feed.tsx
    - frontend/src/views/Recorder.tsx
    - Makefile
    - README.md
    - .gitignore
  modified: []
decisions:
  - "Installed Python 3.11.15 via Homebrew (was missing on host machine; STACK.md-mandated 3.11 sweet spot)"
  - "Added tsc -b incremental artifacts (frontend/*.tsbuildinfo, frontend/vite.config.{d.ts,js}) to .gitignore — these regenerate on every pnpm build"
  - "frontend/postcss.config.js created as empty stub per plan (Tailwind 4 via @tailwindcss/vite needs no PostCSS config but stub heads off legacy tooling errors)"
metrics:
  duration_minutes: 7
  tasks_completed: 2
  files_changed: 23
  completed_date: "2026-04-25"
---

# Phase 01 Plan 01: Repo Bootstrap Summary

Bootable monorepo with FastAPI backend (`/health` returns 200) and Vite + React 18 + TS + Tailwind 4 frontend (two routes `/` and `/record` rendering dark-themed stubs).

## What Was Built

### Backend (Task 1, commit `5123d53`)

| File                       | Purpose                                                                            | LOC |
| -------------------------- | ---------------------------------------------------------------------------------- | --- |
| `backend/app.py`           | FastAPI app with `/health`, lifespan placeholder (Plan 02 will add db.init), CORS  | 32  |
| `backend/config.py`        | dotenv-loaded `FRONTEND_URL` / `DATA_DIR` / `OFFLINE_DEMO` (Phase 5 hook)           | 9   |
| `backend/requirements.txt` | Pinned deps per STACK.md                                                            | 6   |
| `backend/.env.example`     | Local dev defaults; commented Phase 2+ keys                                         | 7   |
| `backend/__init__.py`      | Package marker (empty)                                                              | 0   |
| `Makefile`                 | `install` / `backend` / `frontend` / `dev` targets                                  | 14  |
| `.gitignore`               | Excludes .env, .venv, node_modules, data/, *.db*, dist, tsc artifacts               | 28  |
| `README.md`                | One-paragraph description, local dev instructions, deploy stub, tech stack table    | 41  |

### Frontend (Task 2, commit `b15dee3`)

| File                              | Purpose                                                                       | LOC |
| --------------------------------- | ----------------------------------------------------------------------------- | --- |
| `frontend/package.json`           | React 18 + Vite + TS + Tailwind 4 + react-router-dom@6 deps                   | 24  |
| `frontend/vite.config.ts`         | react + tailwindcss plugins; dev proxy `/api -> :8000`                         | 11  |
| `frontend/tsconfig.json`          | Strict, ES2022, react-jsx, isolatedModules                                     | 19  |
| `frontend/tsconfig.node.json`     | Composite config for `vite.config.ts`                                          | 10  |
| `frontend/tailwind.config.ts`     | Content glob (TW4 still benefits from explicit content paths)                  | 5   |
| `frontend/postcss.config.js`      | Empty stub                                                                     | 1   |
| `frontend/index.html`             | viewport-fit=cover, theme-color #0A0A0A, system font stack                     | 13  |
| `frontend/.env.example`           | `VITE_API_BASE=http://localhost:8000`                                          | 1   |
| `frontend/src/main.tsx`           | BrowserRouter + StrictMode mount                                               | 14  |
| `frontend/src/App.tsx`            | Two routes -> Feed (/) and Recorder (/record)                                  | 12  |
| `frontend/src/index.css`          | `@import "tailwindcss"` + 100dvh base (UI-SPEC iOS contract)                   | 9   |
| `frontend/src/views/Feed.tsx`     | Dark-themed stub with link to /record                                          | 16  |
| `frontend/src/views/Recorder.tsx` | Dark-themed stub with link back to /                                           | 12  |

## Versions Installed

### Backend (`backend/.venv/bin/pip freeze | head -20`)

```
aiosqlite==0.20.0
annotated-types==0.7.0
anyio==4.13.0
click==8.3.3
fastapi==0.115.6
h11==0.16.0
httptools==0.7.1
idna==3.13
pydantic==2.10.3
pydantic_core==2.27.1
python-dotenv==1.0.1
python-multipart==0.0.18
PyYAML==6.0.3
starlette==0.41.3
typing_extensions==4.15.0
uvicorn==0.32.1
uvloop==0.22.1
watchfiles==1.1.1
websockets==16.0
```

Python: 3.11.15 (installed via `brew install python@3.11` — see Deviations).

### Frontend (`pnpm list --depth=0`)

```
dependencies:
  react@18.3.1
  react-dom@18.3.1
  react-router-dom@6.30.3
devDependencies:
  @tailwindcss/vite@4.2.4
  @types/react@18.3.28
  @types/react-dom@18.3.7
  @vitejs/plugin-react@4.7.0
  tailwindcss@4.2.4
  typescript@5.5.4
  vite@5.4.21
```

## One-Line Proofs

### Backend: `/health` returns 200 with `{"ok":true}`

```
$ backend/.venv/bin/uvicorn backend.app:app --port 8000 --app-dir . &
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
$ curl -fsS http://localhost:8000/health
{"ok":true}
$ curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8000/health
HTTP 200
```

### Backend: CORS allow-origin emitted for Vite dev origin

```
$ curl -s -i -H "Origin: http://localhost:5173" http://localhost:8000/health | grep -i access-control-allow-origin
access-control-allow-origin: http://localhost:5173
```

### Frontend: `pnpm build` exits clean

```
$ cd frontend && pnpm build
> tsc -b && vite build
vite v5.4.21 building for production...
transforming...
✓ 36 modules transformed.
dist/index.html                   0.60 kB │ gzip:  0.38 kB
dist/assets/index-CyqwBYFM.css    5.31 kB │ gzip:  1.85 kB
dist/assets/index-LK3S8oq-.js   164.47 kB │ gzip: 53.62 kB
✓ built in 311ms
```

### Frontend: Vite dev server returns root HTML

```
$ pnpm dev --port 5173 &
  VITE v5.4.21  ready in 128 ms
  ➜  Local:   http://localhost:5173/
$ curl -fsS http://localhost:5173/ | grep -E "(viewport-fit=cover|<title>Newz</title>|root)"
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title>Newz</title>
    <div id="root"></div>
```

Built JS bundle confirmed to contain `Plan 03`, `Plan 04`, and `/record` strings (greps against `frontend/dist/assets/index-*.js` all matched).

## Acceptance Criteria

### Task 1 (11/11 pass)

- `grep -q "fastapi==0.115.6" backend/requirements.txt` → OK
- `grep -q "aiosqlite==0.20.0" backend/requirements.txt` → OK
- `grep -q 'FastAPI(title="Newz API", lifespan=lifespan)' backend/app.py` → OK
- `grep -q "CORSMiddleware" backend/app.py` → OK
- `grep -q "config.FRONTEND_URL" backend/app.py` → OK
- `grep -q "OFFLINE_DEMO" backend/config.py` → OK (Phase 5 hook present)
- `grep -q '"ok": True' backend/app.py` → OK
- `grep -q "data/" .gitignore` → OK
- `grep -q "*.db" .gitignore` → OK
- `grep -q "backend/.env" .gitignore` → OK
- `grep -E "^(dev|backend|frontend|install):" Makefile` returns 4 → OK
- `curl http://localhost:8000/health` returns 200 with `"ok":true` → OK (runtime-verified)

### Task 2 (10/10 pass)

- `grep -q '"react": "\^18'` → OK
- `grep -q '"tailwindcss": "\^4'` → OK
- `grep -q '"react-router-dom"'` → OK
- `grep -q "@tailwindcss/vite" frontend/vite.config.ts` → OK
- `grep -q "proxy.*8000" frontend/vite.config.ts` → OK
- `grep -q "viewport-fit=cover" frontend/index.html` → OK
- `grep -q "100dvh" frontend/src/index.css` → OK
- `grep -q "BrowserRouter" frontend/src/main.tsx` → OK
- `grep -q 'path="/record"' frontend/src/App.tsx` → OK
- `grep -q '#0A0A0A' frontend/src/views/Feed.tsx` → OK
- `pnpm build` exits 0 → OK (runtime-verified)
- Dev server response at `/` includes the root div → OK (runtime-verified)

### Plan-level success criteria

- FND-01: `curl http://localhost:8000/health` returns 200 → OK (proven above)
- FND-02: `pnpm dev` brings up Vite, `/` and `/record` exist as routes (rendered client-side via React Router; static curl returns the SPA shell) → OK
- Repo bootable end-to-end with `make install` + two `make` commands → OK (Makefile targets installed Python deps + node_modules cleanly)
- Tailwind 4 config builds without warnings → OK (build output had zero warnings; only the cosmetic gzip-size lines)
- Phase 5 hook present: `OFFLINE_DEMO` env var read in `backend/config.py` → OK

## Threat Model Compliance

| Threat ID | Mitigation status                                                                                                  |
| --------- | ------------------------------------------------------------------------------------------------------------------ |
| T-01-01   | `git ls-files \| grep '\\.env'` returns ONLY `backend/.env.example` and `frontend/.env.example` (no secrets staged)  |
| T-01-02   | `git ls-files \| grep -E '(\\.venv\|node_modules\|/data/\|\\.db$)'` returns nothing — all excluded                  |
| T-01-03   | `app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_URL, "http://localhost:5173"], ...)` — explicit allowlist, never `["*"]` with credentials |
| T-01-04   | accepted (no rate limit on `/health`; trivially cheap, no DB or external IO)                                        |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Python 3.11 not present on host**
- **Found during:** Task 1 verification setup
- **Issue:** Plan and STACK.md require Python 3.11 (sweet spot per CLAUDE.md). Host had 3.13 and 3.14 only; `python3.11 -m venv` in the verification step would fail.
- **Fix:** `brew install python@3.11` → installed 3.11.15 to `/opt/homebrew/bin/python3.11`. Plan-spec Makefile and verify command unchanged.
- **Files modified:** none (host system change only)
- **Commit:** N/A (system install, not code)

**2. [Rule 2 - Critical hygiene] `.gitignore` did not cover tsc -b incremental artifacts**
- **Found during:** Task 2 post-`pnpm build` `git status` review
- **Issue:** `tsc -b` generates `frontend/vite.config.d.ts`, `frontend/vite.config.js`, and `frontend/tsconfig.node.tsbuildinfo` on every build. Plan's .gitignore didn't list these; they would re-appear as untracked after every CI/local build.
- **Fix:** Added three lines to `.gitignore` under the Node section.
- **Files modified:** `.gitignore`
- **Commit:** `b15dee3` (folded into task 2 commit since the artifacts only exist after frontend build runs)

### Authentication Gates

None. No external services were touched in this plan.

## Known Stubs

The following stubs are **intentional** per the plan — Phase 1 is greenfield scaffolding:

| Stub                                             | File                              | Resolved by |
| ------------------------------------------------ | --------------------------------- | ----------- |
| `Feed.tsx` shows "Plan 03 will build the feed"   | `frontend/src/views/Feed.tsx`     | Plan 01-03  |
| `Recorder.tsx` shows "Plan 04 will build camera" | `frontend/src/views/Recorder.tsx` | Plan 01-04  |
| `lifespan` is a no-op (no `db.init()`)           | `backend/app.py`                  | Plan 01-02  |
| No `POST /clips` / `GET /feed` routes yet        | `backend/app.py`                  | Plan 01-02  |
| README "Deploy" section is a stub                | `README.md`                       | Plan 01-05  |

These are tracked explicitly in the plan output and do not block plan completion.

## Self-Check: PASSED

Verified files exist on disk and commits are reachable:

```
$ for f in backend/app.py backend/config.py backend/requirements.txt backend/.env.example backend/__init__.py \
           frontend/package.json frontend/vite.config.ts frontend/tsconfig.json frontend/tailwind.config.ts \
           frontend/index.html frontend/src/main.tsx frontend/src/App.tsx frontend/src/index.css \
           frontend/src/views/Feed.tsx frontend/src/views/Recorder.tsx Makefile .gitignore README.md; do
    [ -f "$f" ] && echo "FOUND: $f" || echo "MISSING: $f"
  done
```

All 18 files: FOUND.

```
$ git log --oneline | grep -E "5123d53|b15dee3"
b15dee3 feat(01-01): scaffold Vite + React 18 + TS + Tailwind 4 frontend with router
5123d53 feat(01-01): scaffold FastAPI backend, Makefile, gitignore, README
```

Both commits: FOUND.
