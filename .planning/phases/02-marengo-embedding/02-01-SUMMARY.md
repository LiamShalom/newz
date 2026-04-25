---
phase: 02-marengo-embedding
plan: 01
subsystem: api
tags: [twelvelabs, marengo, embeddings, sqlite, numpy, tenacity]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: "db.py scaffold with clips table, config.py with TWELVELABS_API_KEY and USE_MOCK_EMBEDDINGS, backend/pipeline/__init__.py"
provides:
  - "embed_worker(clip_id, conn) -> np.ndarray — async Phase 2 pipeline stage"
  - "clip_embeddings SQLite table with 512-d float32 BLOB storage"
  - "store_embedding() and get_embedding() db helpers"
  - "_mock_embedding() deterministic unit vector for offline/CI/OFFLINE_DEMO"
affects: [03-clustering, 05-demo-hardening]

# Tech tracking
tech-stack:
  added: [tenacity]
  patterns:
    - "run_in_executor pattern: sync SDK wrapped in loop.run_in_executor(None, fn, *args) to keep FastAPI event loop unblocked"
    - "Deterministic mock vectors via int.from_bytes seed (PYTHONHASHSEED-stable)"
    - "BLOB storage: np.float32.tobytes() / np.frombuffer() for 512*4=2048-byte vectors"

key-files:
  created:
    - backend/pipeline/embed.py
  modified:
    - backend/db.py

key-decisions:
  - "SDK v1.2.3 imports VideoInputRequest and MediaSource from twelvelabs.types, NOT twelvelabs.models.embed — that module does not exist"
  - "config.USE_MOCK_EMBEDDINGS is already a bool (not string) — no .lower() comparison needed"
  - "clip_embeddings DDL and WAL/busy_timeout pragmas were already present in Phase 1 scaffold — Task 1 added only store_embedding and get_embedding helpers"

patterns-established:
  - "All embed stage imports deferred to function body (_call_marengo) to avoid import-time SDK cost in mock mode"
  - "T-02-01: API key never logged; T-02-02: clip_path validated via Path.exists() before open; T-02-03: only clip_id and latency logged"

requirements-completed: [EMB-01, EMB-02, EMB-03, EMB-04]

# Metrics
duration: 15min
completed: 2026-04-25
---

# Phase 2 Plan 01: Marengo Embedding Worker Summary

**Marengo 3.0 embed worker with run_in_executor threading, deterministic mock mode, tenacity retry, and SQLite 512-d BLOB persistence**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-25T05:17:00Z
- **Completed:** 2026-04-25T05:32:51Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `embed_worker(clip_id, conn)` async entry point that never blocks the FastAPI event loop (run_in_executor wrapping synchronous SDK)
- `_mock_embedding()` with deterministic int.from_bytes seed — stable across Python restarts, critical for OFFLINE_DEMO cluster stability
- SDK v2 two-step pattern confirmed and implemented: `assets.create(method="direct") -> embed.v_2.create(marengo3.0, fused_embedding, asset scope)`
- Full DB persistence layer: `store_embedding()` (BLOB + status=done + latency_ms) and `get_embedding()` (BLOB -> float32 array) with in-memory round-trip test passing

## Task Commits

1. **Task 1: clip_embeddings DDL + db.py helpers** - `8d7dd80` (feat)
2. **Task 2: pipeline/embed.py** - `03e6da3` (feat)

## SDK Verification Outcome

`dir(c.embed.v_2)` confirmed `create` and `tasks` attributes exist on the `v_2` resource. SDK version 1.2.3 installed from `/opt/miniconda3/lib/python3.13/site-packages`.

`c.embed.v_2.create` signature confirmed: `(*, input_type, model_name, video=...)` returns `EmbeddingSuccessResponse` with `data[0].embedding` as `List[float]` (512 floats).

## Files Created/Modified

- `backend/pipeline/embed.py` — complete embed stage: `_mock_embedding`, `_call_marengo` (SDK v2 two-step), `_sync_embed` (dispatcher), `embed_worker` (async entry point), tenacity retry
- `backend/db.py` — added `store_embedding()`, `get_embedding()` helpers; updated module docstring

## Decisions Made

- **SDK import path:** `VideoInputRequest` and `MediaSource` are in `twelvelabs.types`, not `twelvelabs.models.embed`. The plan specified `from twelvelabs.models.embed import ...` but that module does not exist in v1.2.3. Fixed to use `from twelvelabs.types import MediaSource, VideoInputRequest`.
- **USE_MOCK_EMBEDDINGS type:** `config.py` already returns a `bool` (via `.lower() == "true"`). The plan noted a potential string type — confirmed bool, no conversion needed in `_sync_embed`.
- **Schema already present:** The Phase 1 scaffold already included the `clip_embeddings` DDL and WAL/busy_timeout pragmas. Task 1 scope was limited to adding `store_embedding` and `get_embedding` helpers only.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected SDK import path for VideoInputRequest and MediaSource**
- **Found during:** Task 1 (SDK surface verification step)
- **Issue:** Plan specified `from twelvelabs.models.embed import VideoInputRequest, MediaSource` but `twelvelabs.models` does not exist as a module in SDK v1.2.3
- **Fix:** Changed import to `from twelvelabs.types import MediaSource, VideoInputRequest` — confirmed working via `python3 -c "from twelvelabs.types import VideoInputRequest, MediaSource; print('imports ok')"`
- **Files modified:** backend/pipeline/embed.py
- **Verification:** Import succeeds; all mock tests pass
- **Committed in:** 03e6da3 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 SDK import bug)
**Impact on plan:** Import correction was essential for any real Marengo call to succeed. No scope creep. Mock tests and DB round-trip tests fully pass.

## Issues Encountered

- SDK verification confirmed `c.embed.v_2` attribute exists but `from twelvelabs.models.embed import ...` fails — `models` subpackage does not exist. Corrected to `twelvelabs.types`.

## User Setup Required

None — mock mode (`USE_MOCK_EMBEDDINGS=true`) works without any API key. For real Marengo calls, `TWELVELABS_API_KEY` must be set in `.env`.

## Next Phase Readiness

- `embed_worker(clip_id, conn)` is ready to be called from `run_pipeline()` in `app.py`
- `get_embedding(clip_id, conn)` is ready for Phase 3 clustering to load stored vectors
- Mock mode produces stable deterministic vectors — Phase 3 calibration notebook can use mock data
- Phase 3 blocker: clustering threshold (`0.55`) is empirically unvalidated — calibration notebook is a Phase 3 deliverable

---
*Phase: 02-marengo-embedding*
*Completed: 2026-04-25*
