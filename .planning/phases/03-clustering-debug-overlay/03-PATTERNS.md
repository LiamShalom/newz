# Phase 3: Clustering + Debug Overlay — Pattern Map

**Mapped:** 2026-04-25
**Files analyzed:** 7 (4 backend Python + 1 seed script + 1 notebook + 1 asset directory)
**Analogs found:** 6 / 7 (notebook has no in-repo analog; uses RESEARCH.md template)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/pipeline/cluster.py` (NEW) | pipeline-worker / service | event-driven (chained from embed_worker) + CRUD over SQLite | `backend/pipeline/embed.py` | exact (same pipeline-stage role + same DB write pattern) |
| `backend/db.py` (MODIFY) | data-access layer | CRUD | `backend/db.py` (`store_embedding`, `get_embedding`, `insert_clip`) | exact (extending the same module) |
| `backend/pipeline/run.py` (MODIFY) | orchestrator | event-driven chain | `backend/pipeline/run.py` (existing embed step) | exact (extending same file) |
| `backend/app.py` lifespan (MODIFY) | startup hook | batch read + in-memory hydration | `backend/app.py` `lifespan()` + `_pre_warm_marengo()` | exact (same lifespan ctx mgr) |
| `backend/app.py` `GET /debug/clusters` (NEW route) | controller / route handler | request-response (read-only JSON) | `backend/app.py` `GET /feed` route | role-match (read-only GET handler) |
| `backend/seed/seed_demo.py` (NEW) | utility / CLI script | request-response (HTTP client over POST /clips) | NO IN-REPO ANALOG (use RESEARCH.md §"Seed script" template) | none |
| `backend/notebooks/calibration.ipynb` (NEW) | test / dev tool | batch + HTTP probe | NO IN-REPO ANALOG (use RESEARCH.md §"Calibration notebook layout") | none |
| `backend/seed/demo/*.mp4` (NEW assets) | static asset | n/a (binary blob) | `backend/seed/prewarm.mp4` | role-match (same seed/ directory pattern) |

## Pattern Assignments

### `backend/pipeline/cluster.py` (pipeline-worker, event-driven + CRUD)

**Analog:** `backend/pipeline/embed.py`

**Why this analog:** `embed.py` is the immediately-preceding stage in the same fire-and-forget pipeline. Same role (async public worker called by `run_pipeline`), same data-flow shape (read clip from DB → CPU work → persist back to DB → return value to caller), and same project conventions (relative imports, module-level logger, error handling with status flag). `cluster.py` should mirror this file's shape line-for-line.

**Module docstring + import block pattern** (`backend/pipeline/embed.py:1-25`):

```python
"""
backend/pipeline/embed.py — Marengo 3.0 embed stage.

Public API:
    embed_worker(clip_id) -> np.ndarray
        Async entry point. Called by run_pipeline(). Never blocks the event loop.

Private helpers:
    _sync_embed(clip_path, clip_id) -> tuple[np.ndarray, int]
        Synchronous dispatcher — runs in thread pool.
    _mock_embedding(clip_id) -> np.ndarray
        Deterministic unit vector, stable across restarts (OFFLINE_DEMO safe).
"""

import asyncio
import logging
import time
from pathlib import Path

import numpy as np
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import config, db

log = logging.getLogger(__name__)
```

**Copy for `cluster.py`:**
- Same docstring layout (module summary + Public API + Private helpers)
- Same relative-import pattern: `from .. import config, db, events` (add `events` since `cluster_worker` broadcasts)
- Same module-level `log = logging.getLogger(__name__)`
- Add `import math, uuid` and `from dataclasses import dataclass, field` for new module's needs

**Async public-entry pattern** (`backend/pipeline/embed.py:83-109`):

```python
async def embed_worker(clip_id: str) -> np.ndarray:
    """Async embed stage. Called by run_pipeline(clip_id).

    Reads clip path from DB, runs _sync_embed in thread pool, persists BLOB.
    Returns 512-d vector for cluster_worker (Phase 3).
    """
    clip = await db.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"embed_worker: clip {clip_id!r} not found")

    clip_path = clip["path"]
    if not Path(clip_path).exists():
        raise FileNotFoundError(f"embed_worker: file missing at {clip_path!r}")

    try:
        loop = asyncio.get_event_loop()
        vec, latency_ms = await loop.run_in_executor(None, _sync_embed, clip_path, clip_id)
        await db.store_embedding(clip_id, vec, latency_ms)
        return vec
    except Exception:
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE clips SET embedding_status = 'failed' WHERE id = ?", (clip_id,)
            )
            await conn.commit()
        raise
```

**Copy for `cluster_worker(clip_id, vec)`:**
- Same opening: `clip = await db.get_clip(clip_id)` + `if clip is None: raise ValueError(...)`
- Same `try` body wrapping all DB writes; on exception, log via `log.exception(...)` and `raise` (don't silently swallow — let `run_pipeline` catch)
- No `run_in_executor` needed: cosine over <100 unit vectors is sub-millisecond; keep inline
- Replace executor block with the async-with-_LOCK score-and-mutate block from RESEARCH §"cluster_worker async entry point"

**Logging pattern** (`backend/pipeline/embed.py:72`):

```python
log.info("embed clip_id=%s latency_ms=%d dims=%d", clip_id, latency_ms, len(vec))
```

**Copy for `cluster.py`** (key=value style, single-line, no f-strings):

```python
log.info("cluster_worker clip_id=%s cluster_id=%s new=%s composite=%s",
         clip_id, cluster_id, breakdown is None,
         "n/a" if breakdown is None else f"{breakdown.composite:.3f}")
```

**Mock pattern** (`backend/pipeline/embed.py:28-34`):

```python
def _mock_embedding(clip_id: str) -> np.ndarray:
    """Deterministic 512-d unit vector keyed by clip_id (PYTHONHASHSEED-stable)."""
    seed = int.from_bytes(clip_id.encode("utf-8")[:8], "big") % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.random(512).astype(np.float32)
    vec /= np.linalg.norm(vec) + 1e-12
    return vec
```

Not directly applicable to `cluster.py` (no API to mock), but the pattern of "deterministic from clip_id" is reusable if the calibration notebook needs synthetic vectors.

**L2 normalization idiom** (`backend/pipeline/embed.py:71`):

```python
vec /= np.linalg.norm(vec) + 1e-12
```

**Copy for centroid update in `cluster.py`** — running-mean centroid must be re-normalized identically:

```python
updated /= np.linalg.norm(updated) + 1e-12
```

---

### `backend/db.py` — new helpers `get_all_clusters()`, `upsert_cluster()`, `assign_clip_to_cluster()` (data-access, CRUD)

**Analog:** existing helpers in same file — `store_embedding` (lines 141-154), `get_embedding` (lines 157-165), `get_clip` (lines 110-115)

**Why this analog:** Same module, same per-operation aiosqlite connection convention, same `aiosqlite.Row` row-factory pattern for SELECTs, same BLOB-as-bytes convention for vectors.

**Per-operation connection + INSERT OR REPLACE pattern** (`backend/db.py:141-154` — `store_embedding`):

```python
async def store_embedding(clip_id: str, vec: np.ndarray, latency_ms: int) -> None:
    blob = vec.astype(np.float32).tobytes()
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO clip_embeddings (clip_id, vector, latency_ms, created_at) "
            "VALUES (?, ?, ?, ?)",
            (clip_id, blob, latency_ms, now),
        )
        await conn.execute(
            "UPDATE clips SET embedding_status = 'done', embed_latency_ms = ? WHERE id = ?",
            (latency_ms, clip_id),
        )
        await conn.commit()
```

**Copy for `upsert_cluster(cluster)`** — same shape: open connection, BLOB the vector via `astype(np.float32).tobytes()`, parameterize with `?`, `await conn.commit()` at end. Use `INSERT ... ON CONFLICT(id) DO UPDATE SET ...` (aiosqlite supports SQLite UPSERT) since clusters are mutated repeatedly. Concrete SQL is in RESEARCH.md §"DB helpers".

**Copy for `assign_clip_to_cluster(clip_id, cluster_id)`** — even simpler: single `UPDATE clips SET cluster_id = ? WHERE id = ?`, then commit. Mirrors the second `await conn.execute()` inside `store_embedding`.

**Row-factory SELECT pattern** (`backend/db.py:118-138` — `fetch_recent_clips`):

```python
async def fetch_recent_clips(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT id, path, lat, lng, ts, created_at "
            "FROM clips ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
    out = []
    for r in rows:
        ...
        out.append({...})
    return out
```

**Copy for `get_all_clusters() -> list[dict]`:**
- Set `conn.row_factory = aiosqlite.Row` then SELECT all columns from `clusters`
- Open a SECOND cursor in the same `async with conn` to fetch `clips` rows where `cluster_id IS NOT NULL` (so we group `member_ids` per cluster in one transaction; avoids N+1)
- Convert rows to `dict(r)` for return
- Group `member_ids` in Python via `dict.setdefault(cluster_id, []).append(clip_id)` after the queries close
- Concrete SQL + grouping logic is in RESEARCH.md §"DB helpers" — `get_all_clusters()`

**BLOB read pattern** (`backend/db.py:157-165` — `get_embedding`):

```python
async def get_embedding(clip_id: str) -> np.ndarray | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT vector FROM clip_embeddings WHERE clip_id = ?", (clip_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return np.frombuffer(row[0], dtype=np.float32).copy()
```

**Copy for centroid reconstitution in lifespan:** `np.frombuffer(row["centroid"], dtype=np.float32).copy()`. The `.copy()` is required so the buffer is writable (running-mean update needs to mutate). This idiom is already established by `get_embedding`.

**Module-level constants** (`backend/db.py:14-15`):

```python
DB_PATH = config.DATA_DIR / "newz.db"
CLIPS_DIR = config.DATA_DIR / "clips"
```

**Copy for new helpers:** keep using `DB_PATH` (already exported from db module). No new module-level constants needed.

---

### `backend/pipeline/run.py` (orchestrator, event-driven chain)

**Analog:** existing `run_pipeline()` in same file (lines 9-23)

**Existing scaffold** (`backend/pipeline/run.py:1-23`):

```python
import logging

from .. import events
from .embed import embed_worker

log = logging.getLogger(__name__)


async def run_pipeline(clip_id: str) -> None:
    """Background pipeline. Fire-and-forget from POST /clips.

    Phase 2: embed_worker — Marengo 512-d vector, stored in SQLite.
    Phase 3: cluster_worker — composite-score assignment (coming).
    Phase 4: compile_pipeline — Claude Agent SDK segment (coming).
    """
    try:
        vec = await embed_worker(clip_id)
        log.info("pipeline embed done clip_id=%s dims=%d", clip_id, len(vec))
        await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "embedded"})
        # Phase 3 wires in: cluster_id = await cluster_worker(clip_id, vec)
    except Exception as exc:
        log.exception("pipeline failed clip_id=%s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": str(exc)})
```

**Copy / extend pattern:**
- Add `from .cluster import cluster_worker` to the import block (mirrors `from .embed import embed_worker`)
- Replace the comment `# Phase 3 wires in: cluster_id = await cluster_worker(clip_id, vec)` with the actual call:
  ```python
  cluster_id = await cluster_worker(clip_id, vec)
  log.info("pipeline cluster done clip_id=%s cluster_id=%s", clip_id, cluster_id)
  await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "clustered"})
  ```
- Keep the call inside the same `try` block — the existing `except` already handles broadcast of `pipeline_error`. cluster_worker exceptions must NOT corrupt `CLUSTERS` cache (see Pitfall 6 in RESEARCH); they propagate up and the cache stays consistent because cluster.py mutates cache LAST.
- Bump the docstring: change "Phase 3: cluster_worker — composite-score assignment (coming)." → "Phase 3: cluster_worker — composite-score assignment."

---

### `backend/app.py` lifespan (MODIFY) — rebuild `CLUSTERS` from SQLite (CLU-10)

**Analog:** existing `lifespan` (lines 37-41) + `_pre_warm_marengo` (lines 18-34)

**Existing lifespan** (`backend/app.py:37-41`):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    asyncio.create_task(_pre_warm_marengo())  # fire-and-forget; never blocks startup
    yield
```

**Copy / extend pattern:**
- Insert cluster-cache rebuild AFTER `await db.init()` and BEFORE the `asyncio.create_task(_pre_warm_marengo())` line (rebuild must complete before any new clip ingest accepts work; pre-warm is independent)
- Use a local import to avoid circular dependency: `from .pipeline import cluster as cluster_mod` (mirrors the `from .pipeline.embed import _sync_embed` local import already at `backend/app.py:29`)
- The cluster module exposes its module-level `CLUSTERS` dict and a public `rebuild_from_db()` async helper, OR the lifespan does the dataclass construction inline. Recommendation: put the rebuild logic as `cluster.rebuild_cache()` so app.py stays thin
- Concrete code in RESEARCH.md §"Pattern 4: Lifespan Rebuild from SQLite"

**Local-import pattern inside `_pre_warm_marengo`** (`backend/app.py:29-31`) — proves project convention for breaking circular deps with deferred imports:

```python
try:
    from .pipeline.embed import _sync_embed
    loop = asyncio.get_event_loop()
    _, latency_ms = await loop.run_in_executor(None, _sync_embed, pre_warm_path, "__prewarm__")
```

**Copy:** Use the same local-import pattern in lifespan for `cluster_mod` and in `GET /debug/clusters` route.

---

### `backend/app.py` `GET /debug/clusters` (NEW route, controller, request-response)

**Analog:** `GET /feed` route at `backend/app.py:92-95`

**Existing route** (`backend/app.py:92-95`):

```python
@app.get("/feed")
async def feed():
    rows = await db.fetch_recent_clips(limit=50)
    return {"clips": rows}
```

**Why this analog:** Same shape — read-only async GET handler returning a JSON dict, no auth (matches anonymity constraint), no body, queries DB / in-memory state, returns wrapped under a top-level key (`{"clips": ...}` ↔ `{"clusters": ...}`).

**Copy for `/debug/clusters`:**
- `@app.get("/debug/clusters")` decorator at the bottom of `app.py` (after `/feed`)
- `async def debug_clusters():` — no path/query params for v1
- Local import `from .pipeline import cluster as cluster_mod` at top of function body
- Iterate `cluster_mod.CLUSTERS.values()`, for each cluster fetch member clips via `db.get_clip` + embeddings via `db.get_embedding` (existing helpers), compute `score_against` for diagnostic display
- Return JSON dict with `threshold`, `weights`, `gps_radius_m`, `time_window_s`, `clusters` keys
- Concrete JSON shape locked in RESEARCH.md §"GET /debug/clusters JSON shape"

**Health endpoint pattern** (`backend/app.py:59-61`):

```python
@app.get("/health")
async def health():
    return {"ok": True}
```

**Copy for minimal route stylistic conventions:** decorator on previous line, async def, single return statement (when possible). No HTTPException needed for `/debug/clusters` — empty `CLUSTERS` dict returns valid JSON `{"clusters": []}`.

**Validation / error pattern** (`backend/app.py:76-83` — `ingest_clip`):

```python
if file.content_type and not any(file.content_type.startswith(p) for p in ALLOWED_MIME_PREFIXES):
    raise HTTPException(status_code=415, detail=f"unsupported content type: {file.content_type}")
if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
    raise HTTPException(status_code=422, detail="lat/lng out of range")
```

**Apply to /debug/clusters:** None of these inputs apply. The route is read-only. Optional defensive: add `@app.get("/debug/clusters", include_in_schema=False)` to hide from public OpenAPI docs (debug endpoint, not for end users). Apply only if planner deems it valuable; not required by CLU-09.

---

### `backend/seed/seed_demo.py` (NEW, utility / CLI script, request-response)

**Analog:** NO IN-REPO ANALOG — no existing CLI scripts in this codebase. Use RESEARCH.md §"Seed script" as template.

**Closest stylistic anchor:** the way `_pre_warm_marengo` shells out to `_sync_embed` with a hardcoded path (`backend/app.py:24-31`) shows the project's "small piece of code that exercises the live pipeline" idiom. Apply that mindset — `seed_demo.py` is the same pattern but from the OUTSIDE via HTTP.

**Pattern to follow** (RESEARCH.md §"Seed script"):
- Module docstring with `Usage:` block
- Hardcoded `CALTECH_LAT = 34.1377` / `CALTECH_LNG = -118.1253` (matches CLAUDE.md "demo target" — Beckman Mall area)
- `argparse` with `--base-url` defaulting to `http://localhost:8000`
- `httpx.AsyncClient` for POST /clips uploads
- Sequential uploads with `await asyncio.sleep(0.5)` between them — pipeline race avoidance per Pitfall 4
- Glob `seed/demo/clip-*.mp4`, assert 3-4 files
- Print `clip_id` and lat/lng per upload for operator visibility
- Run as `python -m backend.seed.seed_demo`

**Dependency note:** `httpx` is NOT in `backend/requirements.txt`. Per RESEARCH §"Environment Availability", planner has two options:
1. Add `httpx` to a `requirements-dev.txt` (preferred — clean separation)
2. Use stdlib `urllib.request` (zero new deps; uglier code)

**Recommendation:** create `backend/requirements-dev.txt` with `httpx` and `matplotlib`, keep production `requirements.txt` clean.

---

### `backend/notebooks/calibration.ipynb` (NEW, test/dev tool)

**Analog:** NO IN-REPO ANALOG. Use RESEARCH.md §"Calibration notebook layout" as the literal cell-by-cell template.

**Pattern to follow:**
- Cell 1: imports + `BASE = os.environ.get("BACKEND_URL", "http://localhost:8000")` + `DEMO = Path("../seed/demo")`
- Cell 2: `httpx.get(f"{BASE}/health")` smoke test
- Cell 3: `subprocess.run(["python", "-m", "backend.seed.seed_demo", "--base-url", BASE])` + `time.sleep(45)` for embed pipeline to finish
- Cell 4: assert biggest cluster member_count >= 3 → CLU-07
- Cell 5: matplotlib pairwise composite matrix → CLU-09 visual diagnostic
- Cell 6: adversarial pair → CLU-08
- Cell 7 (optional): threshold sweep over `[0.40 .. 0.70]`

**Project-convention notes:**
- Notebook must NOT import pipeline modules directly (avoids fork/asyncio pitfalls per RESEARCH §"Architectural Responsibility Map" row "Calibration notebook")
- Notebook talks to backend via HTTP only — same way judges' browser would
- Header markdown cell should document `USE_MOCK_EMBEDDINGS=false` precondition (mock vectors are random and won't fuse → CLU-07 will fail with mock embeddings)

---

### `backend/seed/demo/*.mp4` (NEW asset directory)

**Analog:** `backend/seed/prewarm.mp4`

**Why this analog:** Same `seed/` directory, same .mp4 binary asset role, same purpose (small file checked into repo to exercise pipeline). The existing prewarm.mp4 is `backend/seed/prewarm.mp4` and is committed (referenced from `config.PRE_WARM_CLIP_PATH` default).

**Pattern to follow:**
- File naming convention: `clip-1.mp4`, `clip-2.mp4`, `clip-3.mp4`, `clip-4.mp4` (sortable lexicographically — matches RESEARCH §"Seed script" `sorted(CLIP_DIR.glob("clip-*.mp4"))`)
- Keep clips short (10-15s) — same constraint as `prewarm.mp4`
- Commit binaries to git (project already commits prewarm.mp4 — no .gitignore exclusion for `seed/`)

---

## Shared Patterns

### Project Import Convention (relative imports inside `backend/`)

**Source:** `backend/pipeline/embed.py:23` and `backend/pipeline/run.py:3-4`

```python
from .. import config, db          # from pipeline/ to backend/
from .embed import embed_worker    # from pipeline/run.py to pipeline/embed.py
```

**Apply to:**
- `backend/pipeline/cluster.py`: `from .. import config, db, events`
- `backend/pipeline/run.py`: add `from .cluster import cluster_worker`
- `backend/app.py`: keep existing `from . import config, db, events` style; deferred `from .pipeline import cluster as cluster_mod` inside lifespan and `/debug/clusters`

### Logging Convention

**Source:** every backend module

```python
log = logging.getLogger(__name__)
log.info("event_name key1=%s key2=%d", val1, val2)   # %-format, key=value
```

**Apply to:** all new code in `cluster.py`, new db helpers, new route. Never use f-strings inside `log.*` calls (deferred formatting is project convention).

### Per-operation aiosqlite connection

**Source:** `backend/db.py` — every helper opens a fresh `async with aiosqlite.connect(DB_PATH) as conn:` block, runs queries, calls `await conn.commit()` for writes, lets the context manager close.

```python
async with aiosqlite.connect(DB_PATH) as conn:
    await conn.execute("...", (...,))
    await conn.commit()
```

**Apply to:** `get_all_clusters`, `upsert_cluster`, `assign_clip_to_cluster`. NEVER share a connection between coroutines or persist a connection at module level.

### Parameterized SQL (anti-injection)

**Source:** `backend/db.py:100-104` (`insert_clip`), `backend/db.py:113` (`get_clip`)

```python
await conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,))
```

**Apply to:** every new SQL query in db.py. Never f-string SQL.

### Numpy BLOB serialization

**Source:** `backend/db.py:142` (`store_embedding`):

```python
blob = vec.astype(np.float32).tobytes()
```

**Source:** `backend/db.py:165` (`get_embedding`):

```python
return np.frombuffer(row[0], dtype=np.float32).copy()
```

**Apply to:** centroid persistence in `upsert_cluster` (write side) and lifespan rebuild (read side). The `.copy()` on read makes the array writable for running-mean updates.

### Fire-and-forget broadcast (Phase 4 forward-compatible)

**Source:** `backend/events.py:7-19` + call sites at `backend/app.py:87` (`clip_added`) and `backend/pipeline/run.py:19,23` (`pipeline_progress` / `pipeline_error`)

```python
await events.broadcast({"type": "clip_added", "clip_id": clip_id})
```

**Apply to:** `cluster_worker` emits `cluster_assigned` event (RESEARCH §"cluster_worker async entry point" lines 597-615). The current `events.broadcast()` is a no-op until Phase 4 wires `GET /events`; calling it now is forward-compatible and zero-cost.

### Anonymity-preserving identifiers

**Source:** `backend/db.py:93` (`insert_clip`):

```python
clip_id = uuid.uuid4().hex
```

**Apply to:** new cluster IDs in `cluster_worker` — `cluster_id = uuid.uuid4().hex`. Never derive from session_id, lat/lng, or any user-identifying field (CLAUDE.md "Hard Constraints").

### Error handling: log + raise (don't swallow)

**Source:** `backend/pipeline/embed.py:102-109`

```python
except Exception:
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "UPDATE clips SET embedding_status = 'failed' WHERE id = ?", (clip_id,)
        )
        await conn.commit()
    raise
```

**Apply to:** `cluster_worker` — if exception occurs DURING the score-and-mutate block, do NOT update CLUSTERS dict (see Pitfall 6). The exception bubbles up to `run_pipeline`'s outer `try` (`backend/pipeline/run.py:21-23`), which broadcasts `pipeline_error` and logs. cluster.py itself only logs and re-raises — does not need to set a `cluster_status = 'failed'` column (no such column exists; cluster_id stays NULL on the clip, which is the implicit failure signal).

### Lifespan extension (additive, not destructive)

**Source:** `backend/app.py:37-41`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    asyncio.create_task(_pre_warm_marengo())  # fire-and-forget; never blocks startup
    yield
```

**Apply to:** insert cluster cache rebuild AFTER `db.init()` (depends on db) and BEFORE `asyncio.create_task(_pre_warm_marengo())` (independent). Do NOT remove or reorder existing lines — Phase 2 pre-warm must keep working.

### Deferred local imports (circular-dep break)

**Source:** `backend/app.py:29` inside `_pre_warm_marengo`:

```python
from .pipeline.embed import _sync_embed
```

**Apply to:** lifespan + `/debug/clusters` route — use `from .pipeline import cluster as cluster_mod` inside the function body, not at module top. Avoids `app.py` ↔ `pipeline/cluster.py` import order issues if cluster.py ever imports anything that transitively touches app.

### Read-only GET route style

**Source:** `backend/app.py:59-61` (`/health`) and `backend/app.py:92-95` (`/feed`)

```python
@app.get("/path")
async def handler():
    ...
    return {"top_level_key": payload}
```

**Apply to:** `/debug/clusters` — match existing style: decorator one line above, async def, single dict return, top-level key wraps the array.

---

## No Analog Found

| File | Role | Data Flow | Reason / Fallback |
|------|------|-----------|-------------------|
| `backend/seed/seed_demo.py` | utility / CLI script | request-response over HTTP | No CLI scripts exist in repo. Fallback: use RESEARCH.md §"Seed script" as literal template. |
| `backend/notebooks/calibration.ipynb` | dev tool / test | batch + HTTP probes | No notebooks exist in repo. Fallback: use RESEARCH.md §"Calibration notebook layout (cells 1-7)" as literal template. |

---

## Metadata

**Analog search scope:** `backend/`, `backend/pipeline/`, `backend/seed/` (recursive)
**Files scanned:** 9 (`backend/__init__.py`, `backend/app.py`, `backend/config.py`, `backend/db.py`, `backend/events.py`, `backend/models.py`, `backend/pipeline/__init__.py`, `backend/pipeline/embed.py`, `backend/pipeline/run.py`, `backend/requirements.txt`)
**Pattern extraction date:** 2026-04-25
**Notes:** All analog files are small (≤ 166 lines). Each was read once in full — no re-reads, no large-file paging needed. Centroid math and dataclass shape are fully specified in RESEARCH.md and are not re-derived here.
