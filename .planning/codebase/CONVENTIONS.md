# Coding Conventions

**Analysis Date:** 2026-04-24
**Status:** Pre-implementation — conventions derived from CLAUDE.md, research docs, and planned stack. These are prescriptive standards to follow when writing code.

---

## Naming Patterns

**Files (Python backend):**
- Modules use `snake_case.py`: `embed.py`, `cluster.py`, `compile.py`, `events.py`
- Pipeline files live in `backend/pipeline/`: `embed.py`, `cluster.py`, `compile.py`, `tools.py`
- Top-level modules: `app.py`, `config.py`, `db.py`, `models.py`, `feed.py`, `events.py`

**Files (TypeScript frontend):**
- React view components use `PascalCase.tsx`: `Recorder.tsx`, `Feed.tsx`, `Debug.tsx`
- Utility modules use `camelCase.ts`: `api.ts`, `sse.ts`
- Tailwind config: `vite.config.ts` (Vite integration via `@tailwindcss/vite`)

**Python functions:**
- `snake_case` for all functions and methods
- Async coroutines prefixed by their role: `async def run_pipeline(clip_id)`, `async def assign_or_create(...)`, `async def should_compile(...)`
- Worker entry points named `generate`, `run`, or `assign_or_create` per module: `embed.generate()`, `compile.run()`, `cluster.assign_or_create()`

**Python variables:**
- `snake_case` throughout
- Constants and weights in `UPPER_SNAKE_CASE`: `W_VISUAL = 0.55`, `W_GPS = 0.30`, `W_TIME = 0.15`, `THRESHOLD = 0.55`
- Env-var names in `UPPER_SNAKE_CASE`: `TWELVELABS_API_KEY`, `ANTHROPIC_API_KEY`, `OFFLINE_DEMO`, `USE_MOCK_EMBEDDINGS`

**TypeScript variables and functions:**
- `camelCase` for variables and functions: `startRecording`, `refetchFeed`, `lastClipId`
- `PascalCase` for React components and TypeScript interfaces/types: `ClipCard`, `SegmentTile`, `ScoreBreakdown`
- Constants in `UPPER_SNAKE_CASE`: `MIME_CANDIDATES`, `API_BASE`

**SQLite schema:**
- Table names in `snake_case` plural: `clips`, `clip_embeddings`, `clusters`, `segments`
- Column names in `snake_case`: `clip_id`, `centroid_lat`, `embedding_status`, `ordered_clip_ids`

---

## Code Style

**Python formatting:**
- No formatter specified in research; use `black` with default settings (88-char line length)
- `ruff` for linting — catches common async/await misuse and import issues
- Type hints required on all function signatures: `async def generate(clip_id: str) -> np.ndarray`

**TypeScript formatting:**
- No formatter config yet; use `prettier` with Vite defaults
- ESLint via Vite's `react-ts` template — do not disable rules
- Strict TypeScript: `"strict": true` in `tsconfig.json`

**Python linting rules to enforce:**
- No blocking I/O in route handlers — all HTTP calls use `httpx.AsyncClient` with `await`
- No `requests` library anywhere in backend — it is synchronous
- `asyncio.create_task` for fire-and-forget, never `BackgroundTasks` for long-running work

**TypeScript linting rules to enforce:**
- No hardcoded MIME types: always use `MediaRecorder.isTypeSupported()` ladder
- `VITE_API_BASE` env var must be read via `import.meta.env.VITE_API_BASE`; never hardcode localhost URLs

---

## Import Organization

**Python order:**
1. Standard library (`os`, `json`, `asyncio`, `time`, `logging`)
2. Third-party (`fastapi`, `pydantic`, `numpy`, `twelvelabs`, `claude_agent_sdk`, `aiosqlite`)
3. Local modules (`from . import db`, `from .models import Clip`, `from .events import broadcast`)

**TypeScript order:**
1. React imports (`import React, { useEffect, useState } from 'react'`)
2. Third-party libraries (`import { useNavigate } from 'react-router-dom'`)
3. Local modules (`import { fetchFeed } from '../api'`, `import { useSSE } from '../sse'`)

**Path aliases:**
- Not configured yet; use relative imports in both Python and TypeScript at hackathon scale

---

## Error Handling

**Backend — pipeline errors:**
- Wrap each pipeline stage in `try/except Exception as e`
- Always broadcast a `pipeline_error` event on failure — never silently swallow
- Log with `log.exception("pipeline failed for %s", clip_id)` (includes stack trace)
- Pattern from `ARCHITECTURE.md`:

```python
async def run_pipeline(clip_id: str):
    try:
        embedding = await embed.generate(clip_id)
        cluster_id = await cluster.assign_or_create(clip_id, embedding)
        await events.broadcast({"type": "cluster_updated", "cluster_id": cluster_id})
        if await cluster.should_compile(cluster_id):
            segment = await compile.run(cluster_id)
            await events.broadcast({"type": "segment_published", "segment_id": segment.id})
    except Exception as e:
        log.exception("pipeline failed for %s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": str(e)})
```

**Backend — Marengo calls:**
- Wrap every Twelve Labs API call with `tenacity` retry: 3 attempts, exponential backoff
- Return 202 immediately even if retry is pending — never expose retry state to the HTTP caller
- Set `embedding_status = "failed"` in SQLite on final retry failure

**Backend — compile pipeline timeout:**
- Hard 30-second wall-clock cap via `asyncio.wait_for(..., timeout=30.0)`
- On `asyncio.TimeoutError`, fall back to default clip ordering + generic caption — never raise to the caller

**Backend — HTTP routes:**
- Routes return 202 for ingest (`POST /clips`) — never 200; processing is not synchronous
- Return `{"clip_id": clip_id, "status": "processing"}` shape — consistent across all 202 responses
- Use `HTTPException` for client errors (400/422), not bare `raise ValueError`

**Frontend — uploads:**
- Failed uploads queue in localStorage and retry on reconnect (REQ: CAP-09)
- Show per-state progress: `uploading → embedding → clustering → compiled`
- Never block the submit button on GPS — use 5s timeout, submit with `gps=null` if unavailable

**Frontend — SSE:**
- `EventSource` auto-reconnects natively; do not implement manual reconnect logic
- Handle `pipeline_error` events with a non-blocking toast, not a modal

---

## Logging

**Framework:** Python `logging` module (standard library)

**Setup:**
```python
import logging
log = logging.getLogger(__name__)
```

**Patterns:**
- Use `log.exception(...)` (not `log.error(...)`) inside `except` blocks — captures stack trace
- Log latency for every Marengo call: `log.info("embed complete clip=%s latency=%.2fs", clip_id, elapsed)`
- Log composite score on every cluster assignment: `log.debug("clip=%s cluster=%s score=%.3f", ...)`
- Never log: API keys, GPS coordinates (privacy), session UUIDs (anonymity), IP addresses (anonymity)

---

## Comments

**When to comment:**
- Explain non-obvious math (clustering weights, score normalization)
- Mark every `# DEMO FALLBACK:` code path explicitly
- Mark every tunable constant with its calibration context: `# tune empirically — see calibration notebook`

**Module docstrings:**
- One-line description at top of each `pipeline/` module explaining its role in the hot path

**TypeScript JSDoc:**
- Not required for hackathon scope; use inline comments for iOS-specific workarounds

**Example:**
```python
# W_VISUAL dominates — Marengo multimodal already encodes audio+speech+motion.
# W_GPS prevents cross-location false merges (e.g., two protests at different campuses).
# W_TIME prevents same-corner morning/evening merge.
# Tune THRESHOLD empirically against staged demo dataset before the pitch — do NOT ship unvalidated.
W_VISUAL = 0.55
W_GPS    = 0.30
W_TIME   = 0.15
THRESHOLD = 0.55  # env var: CLUSTER_THRESHOLD for hot-swap without redeploy
```

---

## Function Design

**Size:** Each pipeline stage function fits in one screen (~40 lines). If longer, extract a helper.

**Parameters:**
- Prefer explicit positional args over `**kwargs` for pipeline functions
- Pydantic models for HTTP request/response bodies: `Clip`, `Cluster`, `Segment`, `ScoreBreakdown`
- Raw primitives (`str`, `float`, `np.ndarray`) for internal pipeline stage handoffs

**Return values:**
- Pipeline stages return domain objects, not raw dicts: `return ScoreBreakdown(visual=v, gps=g, time=t, composite=score)`
- Async coroutines always `return` a typed value or `None` — never leave implicit `return None` on a success path
- Compile pipeline's `run()` returns a `Segment` dataclass or raises — caller handles fallback

**Async rules:**
- All database access via `aiosqlite` — no synchronous SQLite calls in route handlers or pipeline coroutines
- All external HTTP via `httpx.AsyncClient` — no `requests` anywhere
- `asyncio.create_task(run_pipeline(clip_id))` is the ONLY correct way to kick off the pipeline from an HTTP route

---

## Module Design

**Exports (Python):**
- Each `pipeline/` module exports one primary function: `embed.generate`, `cluster.assign_or_create`, `compile.run`
- `events.py` exports `broadcast` as the single shared bus entry point
- `db.py` exports async helpers: `insert_clip`, `fetch_cluster`, `insert_segment`, etc.

**Barrel files (TypeScript):**
- Not used at this scale — import directly from `../api`, `../sse`, `../views/Feed`

**Configuration:**
- All env vars read in `backend/config.py` — never read `os.environ` directly inside pipeline modules
- Frontend reads `import.meta.env.VITE_API_BASE` only in `api.ts` — never scattered across components

**Idempotency:**
- Every pipeline stage checks "already done" before running: `if clip.embedding_status == "done": return existing_vector`
- Compile stage: `if cluster.segment_id is not None: return existing_segment`
- Safe to re-run `run_pipeline(clip_id)` on server restart — no duplicate work

---

## iOS-Specific Patterns

**MediaRecorder MIME type ladder (always use this pattern exactly):**
```typescript
const candidates = [
  "video/mp4;codecs=avc1,mp4a",  // Safari prefers this
  "video/webm;codecs=vp9,opus",  // Chrome/Firefox
  "video/webm;codecs=vp8,opus",
  "video/webm",
];
const mimeType = candidates.find(t => MediaRecorder.isTypeSupported(t));
const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
// CRITICAL: omit mimeType entirely if nothing is supported — Safari is happier with no mimeType than wrong one
```

**Video element attributes (required for iOS inline playback):**
```tsx
<video autoPlay muted playsInline />
// All three attributes required — missing any one produces black screen on iOS
```

**Camera permission (must be on user gesture, not page load):**
- Call `getUserMedia` directly inside click handler — no `setTimeout`, no async chains before the call
- Retry with `{video: true, audio: false}` if `NotAllowedError` on audio

---

*Convention analysis: 2026-04-24*
