<!-- generated-by: gsd-doc-writer -->
# Development

For a contributor making changes mid-hackathon. Project context, scope rules, and the GSD phase workflow live in [CLAUDE.md](../CLAUDE.md) and [`.planning/`](../.planning/) — this doc is the practical "where do I add things and how do I see them work" reference. For env vars see [CONFIGURATION.md](./CONFIGURATION.md). For deploy + CORS wiring see the [README](../README.md). For iPhone hardware verification see [IPHONE-GATE.md](./IPHONE-GATE.md).

## Repo layout

```
backend/                  # FastAPI single-process monolith
  app.py                  # Routes (POST /clips, GET /feed, /events, /debug/*) + lifespan
  config.py               # Env loading (python-dotenv); single source of truth for tunables
  db.py                   # aiosqlite (WAL); clips, embeddings, clusters, segments
  events.py               # SSE pub/sub fan-out
  models.py               # Pydantic IngestResponse etc.
  pipeline/               # Hot-path stages chained via asyncio.create_task
    run.py                # Orchestrator: embed -> cluster -> maybe compile
    embed.py              # Marengo 3.0 (512-d)
    cluster.py            # Composite score; in-memory CLUSTERS dict; rebuild_cache()
    compile.py            # 4-subagent Claude SDK pipeline (60s cap)
    compile_tools.py      # MCP @tool defs (get_cluster_clips, get_clip_metadata, save_segment)
    keyframes.py          # ffmpeg keyframe extraction for caption-writer
    stitch.py             # ffmpeg multi-angle concat
    caption_pipeline.py   # Caption generation
    frames.py             # Native Marengo 3s segmentation helpers
  seed/                   # Marengo pre-warm asset + reusable demo clips (prewarm.mp4, demo/)
  notebooks/              # calibration.ipynb (Phase 3 cluster threshold tuning)
  tests/                  # pytest-asyncio
frontend/                 # React 18 + Vite + TS + Tailwind 4
  src/
    App.tsx               # 2 routes only: / -> Feed, /record -> Recorder
    api.ts                # API_BASE (VITE_API_BASE), fetchSegments, postClip
    views/Feed.tsx        # Feed + SSE refetch
    views/Recorder.tsx    # iOS-Safari camera, MIME ladder, GPS, postClip
    components/           # Tailwind 4 components (no CSS modules)
    hooks/useEventSource.ts  # Mount on Feed.tsx ONLY (HTTP/1.1 6-conn cap)
    lib/                  # mimeLadder, getPositionWithTimeout, etc.
docs/                     # ARCHITECTURE, CONFIGURATION, IPHONE-GATE, this file
.planning/                # PROJECT.md, REQUIREMENTS.md, ROADMAP.md, STATE.md, research/
Makefile                  # install / backend / frontend / dev / reset
```

## Dev loop

Two-terminal hot reload. Both servers reload on file save; no manual restart in the common case.

```bash
make install              # python3.11 venv + pnpm install
make backend              # uvicorn --reload :8000  (calls real Marengo — needs TWELVELABS_API_KEY)
make frontend             # vite --host :5173       (--host so a real iPhone on same Wi-Fi can hit it)
```

Backend uvicorn picks up edits to anything under `backend/` including pipeline modules. **Restart manually only when:** (a) you edit `backend/.env`, or (b) you change the lifespan / pre-warm code (lifespan only runs once per process).

Frontend Vite HMR reloads on save. The `--host` flag binds 0.0.0.0 — point your iPhone Safari at `http://<laptop-LAN-ip>:5173`.

## Where to add things

### A new pipeline stage

Hot path is `backend/pipeline/run.py` -> `embed_worker` -> `cluster_worker` -> `compile_segment`. Add stages by:

1. Create `backend/pipeline/<your_stage>.py` with an async entry point that takes whatever the prior stage returns and writes its result via `backend/db.py`.
2. Wire it into `run_pipeline()` in `backend/pipeline/run.py` after the prior stage. Keep it inside the `try:` so failures broadcast `pipeline_error` over SSE.
3. Broadcast progress so the frontend can react: `await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "<name>"})`.
4. If the stage calls an external API, follow the embed pattern: `loop.run_in_executor(None, _sync_call, ...)` so the event loop never blocks.
5. Add a `/debug/<stage>/{id}` endpoint in `backend/app.py` for manual triggering during development (see existing `/debug/compile/{cluster_id}`).

### A new frontend route

1. Add the view to `frontend/src/views/<Name>.tsx`.
2. Register the route in `frontend/src/App.tsx` (currently `/` and `/record` only — keep the surface tiny).
3. **Do not mount a second `useEventSource`.** The hook lives on `Feed.tsx` because HTTP/1.1 caps 6 connections per origin and SSE holds one persistently. If a new view needs server pushes, lift the EventSource into a context.
4. Hit the backend through `frontend/src/api.ts` so `API_BASE` (`VITE_API_BASE`) routing stays centralized.

### A new MCP tool (compile pipeline)

1. Add `@tool("name", "description", {"arg": type})` to `backend/pipeline/compile_tools.py`. Return `{"content": [{"type": "text", "text": json.dumps(payload)}]}`.
2. The tool is auto-registered on the `newz_tools` MCP server — it shows up to subagents as `mcp__newz_tools__<name>`.
3. Add it to the relevant subagent's `allowed_tools` in `backend/pipeline/compile.py`. **Only the Publisher subagent may use `save_segment`** (CMP-03) — preserve that invariant.
4. Test via `POST /debug/compile/{cluster_id}` against an existing cluster; see logs for tool-call traces.

### A new env var or tunable

Add it to `backend/config.py` (with a default) and `backend/.env.example`. Document it in [CONFIGURATION.md](./CONFIGURATION.md). Frontend env vars must be prefixed `VITE_` and are baked at build time — they do **not** hot-reload; restart `make frontend` after editing `frontend/.env`.

## Debugging

Backend exposes intentionally-permissive `/debug/*` endpoints (see `backend/app.py`):

| Endpoint | Use |
| --- | --- |
| `GET /debug/clusters` | Per-cluster member breakdown with composite score components (visual / gps / time). The Phase 3 calibration view. |
| `GET /debug/dbstate` | Counts and sample IDs straight from sqlite. First check when "where did my clip go?" |
| `GET /debug/clip/{clip_id}` | Raw clip row including `cluster_id`. |
| `POST /debug/compile/{cluster_id}` | Manually trigger the 4-subagent compile on an existing cluster. Resets in-flight flag. |
| `POST /debug/caption_writer/{cluster_id}` | Run vision caption-writer in isolation; reports keyframe extraction count + raw exception. Use to isolate compile failures. |

These are `include_in_schema=False` and not auth-gated — fine for hackathon, do not deploy to public traffic as-is.

**SSE tail:** watch the live event stream from a terminal:

```bash
curl -N http://localhost:8000/events
```

Events: `clip_added`, `pipeline_progress` (with `stage` in `embedded`/`clustered`), `pipeline_error`, plus segment broadcasts from `backend/events.py`. SSE secrets are scrubbed via `_scrub()` in `backend/pipeline/run.py` — `TWELVELABS_API_KEY` will not leak into error events.

**Logs:** uvicorn logs INFO by default (`backend/app.py:19`). Pipeline stages log `pipeline embed done clip_id=...`, `pipeline cluster done child_id=... cluster_id=...`, `compile triggered cluster_id=...`. Grep there first.

**Frontend:** Recorder.tsx covers the iOS Safari MIME ladder (`frontend/src/lib/mimeLadder.ts`). When camera silently fails on a real iPhone, check the iPhone gate runbook in [IPHONE-GATE.md](./IPHONE-GATE.md) before touching code.

## Testing

```bash
cd backend && .venv/bin/python -m pytest        # async pipeline tests
cd frontend && pnpm test                         # vitest run (single pass)
cd frontend && pnpm test:watch                   # vitest watch
```

Backend tests are in `backend/tests/` (pytest-asyncio): `test_cluster.py`, `test_compile.py`, `test_compile_timeout.py`, `test_pipeline_integration.py`, `test_events_sse.py`, `test_db_clusters.py`, `test_debug_clusters.py`, `test_segments_db.py`, `test_feed_segments.py`. They run against an in-memory sqlite — no fixtures to manage.

Phase 3 calibration is a Jupyter notebook, not a pytest target: `backend/notebooks/calibration.ipynb`. Run it when tuning `CLUSTER_THRESHOLD` or `VISUAL_FLOOR`.

## GSD phase workflow

Phase-by-phase execution is driven by the GSD commands. **Do not duplicate the phase table here** — it lives in [`.planning/ROADMAP.md`](../.planning/ROADMAP.md) and the current cursor lives in [`.planning/STATE.md`](../.planning/STATE.md). Commands and config: see [CLAUDE.md](../CLAUDE.md#gsd-workflow).

Quick reference:

- `/gsd-progress` — current state + next action
- `/gsd-discuss-phase <N>` -> `/gsd-plan-phase <N>` -> `/gsd-execute-phase <N>`
- `/gsd-next` — auto-advance

Before suggesting any change, read `.planning/PROJECT.md` for scope and `.planning/STATE.md` for the active phase. Out-of-scope items (live streaming, accounts, Pinecone, Redis, etc.) are in [CLAUDE.md](../CLAUDE.md#out-of-scope-do-not-propose-adding) — do not propose adding them.

## Code conventions

- **Python:** type hints on all public functions (`backend/pipeline/*.py` is the reference style). Module docstrings list the public API at the top — match that pattern when adding new modules. `async def` everywhere on the request path; sync work goes through `loop.run_in_executor`. Errors on the pipeline broadcast `pipeline_error` over SSE with `_scrub()`-redacted secrets.
- **TypeScript:** strict mode (see `frontend/tsconfig.json`). All backend calls go through `frontend/src/api.ts` — do not hardcode `localhost:8000` in components.
- **Styling:** Tailwind 4 utility classes only. No CSS modules, no styled-components, no inline `style={{...}}` for anything reusable. Tokens live in `frontend/src/theme.ts` and `tailwind.config.ts`.
- **No emojis** in code, commits, or generated output (project-wide rule from [CLAUDE.md](../CLAUDE.md)).
- **Anonymity is load-bearing.** No accounts, no auth headers carrying identity. The only client-side identifier is the anonymous session UUID in `localStorage` (see `frontend/src/session.ts`), sent as `X-Session-Id` for rate-limit/dedup only.
- **Locked clustering math:** `0.55*cos + 0.30*gps + 0.15*time`, threshold `0.55`, visual floor `0.80`. Do not change these constants without updating CLAUDE.md and the calibration notebook (see `backend/pipeline/cluster.py` module docstring).
