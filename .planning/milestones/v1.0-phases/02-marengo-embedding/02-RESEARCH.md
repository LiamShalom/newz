# Phase 2: Marengo Embedding — Research

**Researched:** 2026-04-24
**Domain:** Twelve Labs Marengo 3.0 embedding integration (Python SDK 1.2.3), async pipeline wiring, SQLite BLOB storage, mock-mode and pre-warm patterns
**Confidence:** HIGH for SDK API surface and architecture; MEDIUM for pre-warm response-time guarantee (empirically unverified)

---

## Summary

Phase 2 wires the Twelve Labs Marengo 3.0 embedding call into the async pipeline established in Phase 1. Every clip that lands in SQLite as `embedding_status=pending` must produce a 512-d float32 vector stored as a BLOB on its row and advance to `embedding_status=done`. The Phase 1 contract is: `POST /clips` returns 202 with `clip_id`, then `asyncio.create_task(run_pipeline(clip_id))` fires. Phase 2 implements the first stage of that pipeline — `embed_worker(clip_id)`.

**Critical SDK finding:** The research docs in `STACK.md` and `ARCHITECTURE.md` reference the pre-v2 API pattern (`client.embed.create(video_file=...)` or `client.embed.task.create()`). These are **outdated**. Twelve Labs introduced Embed API v2 in November 2025. In SDK 1.2.3, the correct path is: `client.assets.create(method="direct", file=...)` to upload the local file, then `client.embed.v_2.create(...)` for sync embedding (clips <10 min) or `client.embed.v_2.tasks.create(...)` for async. The planner MUST use the v2 path.

Three non-negotiable Phase 2 deliverables: (1) real v2 embed call storing 512-d vector in SQLite, (2) `USE_MOCK_EMBEDDINGS=true` returning deterministic fake vectors for offline dev, (3) pre-warm on startup using a tiny real clip. All three are demo-survival mechanisms.

**Primary recommendation:** Implement `pipeline/embed.py` with the two-step `assets.create → embed.v_2.create` pattern, wrap every call in `tenacity` retry (3x exponential), store vectors as `numpy.float32.tobytes()` in a `clip_embeddings` table, and gate the mock path early so the rest of the pipeline can be built without any Twelve Labs API access.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EMB-01 | Twelve Labs `marengo3.0` (lowercase) embedding generated for each ingested clip | SDK v2 two-step pattern documented below; model_name="marengo3.0" confirmed |
| EMB-02 | 512-dimension embedding vector stored in SQLite as BLOB on the clip row | numpy float32 tobytes() = 2048 bytes; schema design documented below |
| EMB-03 | `USE_MOCK_EMBEDDINGS=true` flag returns deterministic fake vectors | seeded `numpy.random.default_rng(hash(clip_id)).random(512)` pattern; no API key needed |
| EMB-04 | Embed worker logs latency for every call (visible in debug overlay) | `time.monotonic()` diff wrapping the embed call; stored in SQLite for overlay query |
| EMB-05 | Pipeline pre-warms Marengo with throwaway call on backend startup | FastAPI `lifespan` event; throwaway asset + embed call on startup |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Embed API call (Marengo) | API / Backend | — | API key must never reach browser; latency (5-30s) must not block HTTP response |
| Vector storage (SQLite BLOB) | Database / Storage | — | 2048-byte float32 blob per clip; queried by cluster worker |
| Embed status tracking | API / Backend | Database | `embedding_status` column on `clips` table drives pipeline state machine |
| Mock mode | API / Backend | — | Environment variable read at startup; fake vectors structurally identical to real ones |
| Pre-warm on startup | API / Backend | — | FastAPI `lifespan` async context manager; one throwaway asset + embed call |
| Latency logging | API / Backend | Database | `embed_latency_ms` stored on clip row; surfaced via existing `/clusters/:id` debug endpoint |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `twelvelabs` | 1.2.3 | Twelve Labs Python SDK — the only ergonomic path to Marengo 3.0 | Locked in CLAUDE.md; Marengo 2.7 sunset 2026-03-30 |
| `aiosqlite` | latest | Async SQLite for FastAPI context | Locked stack; WAL mode handles concurrent reads/writes |
| `numpy` | 2.x (2.4.2 present) | Vector normalization, serialization, cosine ops | Locked stack; float32 tobytes/frombuffer for BLOB I/O |
| `tenacity` | latest | Retry decorator wrapping Marengo API calls | Standard pattern for external API resilience in hackathon code |
| `python-dotenv` | latest | `TWELVELABS_API_KEY`, `USE_MOCK_EMBEDDINGS` env var loading | Standard; already in stack |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `httpx` | 0.27+ | Async HTTP; if you need to check TwelveLabs task status outside SDK | Only if SDK's sync path blocks the event loop |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `tenacity` | manual try/except retry loop | tenacity is one decorator; manual loop is 20 lines; use tenacity |
| BLOB in `clips` table | separate `clip_embeddings` table | Separate table allows multiple segment vectors per clip; for Phase 2 single asset-scope vector, either works; separate table is cleaner for Phase 3 |

**Installation (backend):**
```bash
pip install twelvelabs==1.2.3 aiosqlite tenacity numpy
```

**Version verification:**
```
twelvelabs: 1.2.3 — verified on PyPI 2026-04-24 (latest stable)
numpy: 2.4.2 — confirmed installed on dev machine
```

---

## Architecture Patterns

### System Architecture Diagram

```
POST /clips (202 returned immediately)
       |
       v asyncio.create_task
  run_pipeline(clip_id)
       |
       v
  [embed_worker] ─── USE_MOCK_EMBEDDINGS=true? ──> generate_mock_vector(clip_id)
       |                                                     |
       | false                                               |
       v                                                     |
  client.assets.create(method="direct",               store to SQLite
    file=open(clip_path, "rb"))                       embedding_status=done
       |                                                     |
       v                                                     v
  client.embed.v_2.create(                         broadcast cluster_worker
    input_type="video",
    model_name="marengo3.0",
    video=VideoInputRequest(
      media_source=MediaSource(asset_id=asset.id),
      embedding_option=["visual","audio","transcription"],
      embedding_scope=["asset"],
      embedding_type=["fused_embedding"]
    )
  )
       |
       v
  response.data[0].embedding  (list of 512 floats)
       |
       v
  normalize -> numpy.float32.tobytes() -> SQLite BLOB
  log latency_ms -> clips.embed_latency_ms
  clips.embedding_status = "done"
       |
       v
  cluster_worker(clip_id, embedding)
```

### Recommended Project Structure

```
backend/
├── pipeline/
│   └── embed.py        # Marengo wrapper: generate_embedding(), _mock_embedding()
├── db.py               # store_embedding(), update_embed_status(), get_embedding()
├── config.py           # USE_MOCK_EMBEDDINGS, TWELVELABS_API_KEY, PRE_WARM_CLIP_PATH
└── app.py              # lifespan pre-warm call
```

### Pattern 1: Two-Step Asset Upload + Sync Embed (SDK v2)

**What:** Upload the local clip file as an asset first, then call embed.v_2.create() with the returned asset_id. The sync path (embed.v_2.create) returns immediately for clips <10 min without polling.

**When to use:** All Phase 2 clip embedding — our clips are 4-30 seconds, well under the 10-minute sync threshold.

**Example:**
```python
# Source: docs.twelvelabs.io/docs/guides/create-embeddings/video/new (2026-04-24)
import time
import numpy as np
from twelvelabs import TwelveLabs
from twelvelabs.models.embed import VideoInputRequest, MediaSource

async def generate_embedding(clip_path: str, clip_id: str) -> np.ndarray:
    """Upload clip to TL, run marengo3.0 sync embed, return normalized 512-d vector."""
    client = TwelveLabs(api_key=config.TWELVELABS_API_KEY)
    t0 = time.monotonic()

    # Step 1: upload local file as a TwelveLabs asset
    with open(clip_path, "rb") as f:
        asset = client.assets.create(method="direct", file=f)

    # Step 2: synchronous embed (returns immediately for clips <10min)
    response = client.embed.v_2.create(
        input_type="video",
        model_name="marengo3.0",
        video=VideoInputRequest(
            media_source=MediaSource(asset_id=asset.id),
            embedding_option=["visual", "audio", "transcription"],
            embedding_scope=["asset"],        # one vector per clip
            embedding_type=["fused_embedding"],  # single 512-d combined vector
        ),
    )

    latency_ms = int((time.monotonic() - t0) * 1000)
    vec = np.array(response.data[0].embedding, dtype=np.float32)
    vec /= np.linalg.norm(vec) + 1e-12  # L2 normalize for cosine ops

    log.info("embed clip=%s latency_ms=%d dims=%d", clip_id, latency_ms, len(vec))
    return vec, latency_ms
```

**CRITICAL NOTE:** Do not use `embedding_scope=["clip"]` for Phase 2 — that returns one vector per ~6s segment. Phase 2 stores ONE vector per clip (asset scope). Phase 3 cluster worker expects a single clip-level vector.

**CRITICAL NOTE:** The `embedding_type=["fused_embedding"]` returns a single combined multimodal vector. This is what CLAUDE.md and REQUIREMENTS.md mean by "512-d embedding" — a single vector fusing visual+audio+transcription. If you use `separate_embedding` you get three separate vectors per clip, which complicates Phase 3 cosine ops. Use `fused_embedding`.

### Pattern 2: Mock Embedding (USE_MOCK_EMBEDDINGS=true)

**What:** Deterministic fake 512-d unit vector keyed by clip_id. Structurally identical to real output — same numpy float32 array, same normalization. No API key needed.

**When to use:** All offline dev, CI, and the DEM-04 OFFLINE_DEMO path.

**Example:**
```python
# [ASSUMED] — pattern not from TL docs; standard practice for mock API modes
def _mock_embedding(clip_id: str) -> np.ndarray:
    """Deterministic fake 512-d unit vector. Same on every call for the same clip_id."""
    rng = np.random.default_rng(abs(hash(clip_id)) % (2**32))
    vec = rng.random(512).astype(np.float32)
    vec /= np.linalg.norm(vec) + 1e-12
    return vec
```

**Why deterministic:** If the same clip is re-embedded after a restart, it must return the same vector so cluster assignments are stable. A random mock would cause re-clustering on restart.

### Pattern 3: Pre-warm in FastAPI Lifespan

**What:** On backend startup, upload a tiny clip asset and run one Marengo embed call to pay the cold-start cost before any judge submits. The result is discarded.

**When to use:** Always (non-negotiable per EMB-05 and CLAUDE.md).

**Example:**
```python
# Source: FastAPI lifespan docs (fastapi.tiangolo.com/advanced/events/) [CITED]
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm Marengo — fire and forget, don't block startup
    asyncio.create_task(_pre_warm_marengo())
    yield
    # cleanup if needed

app = FastAPI(lifespan=lifespan)

async def _pre_warm_marengo():
    if config.USE_MOCK_EMBEDDINGS:
        return  # no-op in mock mode
    try:
        # Use the smallest valid clip we have on disk (any clip from seed/)
        await generate_embedding(config.PRE_WARM_CLIP_PATH, clip_id="__prewarm__")
        log.info("Marengo pre-warm complete")
    except Exception as e:
        log.warning("Marengo pre-warm failed (non-fatal): %s", e)
```

**Note:** Pre-warm failure must NOT crash the server. Wrap in try/except and log a warning.

### Pattern 4: Tenacity Retry Wrapper

**What:** Wrap the two-step asset+embed call in a tenacity retry so transient 5xx/network errors don't kill the pipeline.

**When to use:** Always for production Marengo calls.

**Example:**
```python
# [ASSUMED] — standard tenacity pattern; not from TL docs specifically
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, Exception)),
    reraise=True,
)
async def generate_embedding_with_retry(clip_path: str, clip_id: str):
    return await generate_embedding(clip_path, clip_id)
```

### Anti-Patterns to Avoid

- **Using `client.embed.create()` or `client.embed.task.create()` directly with a file**: These are pre-v2 patterns. The v2 API (SDK 1.2.3) requires `assets.create()` first. Using old patterns will result in SDK errors.
- **`embedding_scope=["clip"]` for Phase 2**: Returns multiple vectors per clip (one per ~6s segment). Phase 3 expects a single clip-level vector. Use `embedding_scope=["asset"]`.
- **`embedding_type=["separate_embedding"]`**: Returns 3 separate vectors (visual/audio/transcription). Use `fused_embedding` for a single 512-d combined vector.
- **Blocking the HTTP handler on the embed call**: `generate_embedding` takes 5-30s. It MUST run inside `asyncio.create_task` (already in the Phase 1 pipeline pattern), never inside the POST /clips handler.
- **Polling `embed.v_2.tasks` for short clips**: For clips <10 min, use `embed.v_2.create()` (sync) not `embed.v_2.tasks.create()` (async + poll). Polling adds complexity for zero benefit at our clip lengths.
- **Non-deterministic mock vectors**: Using `numpy.random.random(512)` without a seeded RNG means cluster assignments change across restarts — breaks the demo recovery story.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry with backoff on Marengo | Custom try/except loop | `tenacity` decorator | Edge cases: max attempts, jitter, re-raise vs swallow — tenacity handles all |
| Async SQLite access | sqlite3 module | `aiosqlite` | `sqlite3` blocks the event loop in async context; `aiosqlite` is non-blocking |
| Float vector serialization | JSON array in TEXT column | `numpy.float32.tobytes()` as BLOB | BLOB is 2048 bytes vs ~12KB JSON; no parse overhead; numpy frombuffer for reads |
| L2 normalization | Custom loop | `vec /= np.linalg.norm(vec)` | One-liner; correct with epsilon guard; pre-normalize once at write, not at every cluster read |

**Key insight:** The only custom code Phase 2 needs is the two-step API call and the SQLite schema. Everything else has a standard primitive.

---

## Common Pitfalls

### Pitfall 1: Old SDK API Pattern (Pre-v2)
**What goes wrong:** Code uses `client.embed.create(video_file=open(...), model_name="marengo3.0")` or `client.embed.task.create(...)`. SDK 1.2.3 will raise AttributeError or an API error.
**Why it happens:** All existing project research docs (STACK.md, ARCHITECTURE.md) document the pre-v2 pattern. The Embed API v2 was introduced November 2025 and changed the method hierarchy.
**How to avoid:** Always use the two-step pattern: `assets.create()` then `embed.v_2.create()`. Verify with `python3 -c "from twelvelabs import TwelveLabs; c = TwelveLabs(api_key='x'); print(dir(c.embed))"` on day 1.
**Warning signs:** `AttributeError: 'Embed' object has no attribute 'task'`; or API returns 404/400 on embed calls.

### Pitfall 2: Asset Not Deleted After Embed
**What goes wrong:** Each pre-warm and embed call creates a persistent TwelveLabs asset that counts against your account storage/rate limits. Across 50 demo clips this becomes noise.
**Why it happens:** `assets.create()` is permanent unless explicitly deleted.
**How to avoid:** After a successful embed, optionally call `client.assets.delete(asset.id)` — or at minimum be aware that assets accumulate. For the hackathon, leaving them is fine but acceptable to delete.
**Warning signs:** TwelveLabs dashboard shows unexpected asset count; rate limit headers degrading.

### Pitfall 3: Marengo Latency Surprise on First Real Call
**What goes wrong:** First embed call at demo time takes 20-30s. The UI shows a spinning indicator. Judges see nothing for 30 seconds after the first clip is submitted.
**Why it happens:** Cold-start cost — Marengo requires warm-up even on the sync path. The pre-warm call (EMB-05) pays this cost, but only if it runs far enough in advance.
**How to avoid:** Pre-warm fires in the FastAPI `lifespan` event on startup. Start the backend at least 60 seconds before first demo clip. Confirm pre-warm completed in logs before going live.
**Warning signs:** First embed latency is 3-5x subsequent embed latency; pre-warm log line is absent.

### Pitfall 4: event loop blocking with synchronous SDK calls
**What goes wrong:** `client.embed.v_2.create()` is a synchronous call inside an async function. If called with `await` it raises a TypeError; if called without, it blocks the event loop for 5-30s, freezing all other requests.
**Why it happens:** The TwelveLabs SDK (as of 1.2.3) is synchronous. It does not provide an async client.
**How to avoid:** Run the synchronous SDK call in a thread pool executor: `await asyncio.get_event_loop().run_in_executor(None, _sync_embed, clip_path, clip_id)` where `_sync_embed` is a plain (non-async) function. This keeps the async event loop unblocked.
**Warning signs:** Backend freezes for 10-30s during embed; all other requests queue up; uvicorn access log shows no response to any request while embed is running.

### Pitfall 5: SQLite Write Contention Under Concurrent Embeds
**What goes wrong:** Three judges submit simultaneously. Three embed workers each try to write to SQLite at the same time, causing `sqlite3.OperationalError: database is locked`.
**Why it happens:** SQLite WAL mode handles concurrent reads well but write contention under heavy concurrency can still deadlock.
**How to avoid:** Use a single shared `aiosqlite` connection (or connection pool) with WAL mode and `PRAGMA busy_timeout=5000`. WAL mode is already a project constraint. Do NOT open a new connection per embed call.
**Warning signs:** `OperationalError: database is locked` in embed worker logs; clips stuck in `embedding_status=pending`.

---

## Code Examples

### SQLite Schema for Phase 2

```sql
-- Source: ARCHITECTURE.md (project research, 2026-04-24) [CITED]
-- Add embed_latency_ms and embedding_status to clips table (if not from Phase 1)
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL,
  lng REAL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
  embed_latency_ms INTEGER,                          -- NEW: for debug overlay (EMB-04)
  cluster_id TEXT,
  created_at REAL NOT NULL
);

-- Separate table for the 512-d vector BLOB
CREATE TABLE IF NOT EXISTS clip_embeddings (
  clip_id TEXT PRIMARY KEY,
  vector BLOB NOT NULL,           -- np.float32.tobytes() — 512 × 4 = 2048 bytes
  FOREIGN KEY (clip_id) REFERENCES clips(id)
);
```

### Storing and Retrieving Vectors

```python
# [ASSUMED] — standard numpy BLOB pattern
import numpy as np

async def store_embedding(clip_id: str, vec: np.ndarray, latency_ms: int, conn):
    blob = vec.astype(np.float32).tobytes()
    await conn.execute(
        "INSERT OR REPLACE INTO clip_embeddings (clip_id, vector) VALUES (?, ?)",
        (clip_id, blob)
    )
    await conn.execute(
        "UPDATE clips SET embedding_status='done', embed_latency_ms=? WHERE id=?",
        (latency_ms, clip_id)
    )
    await conn.commit()

async def get_embedding(clip_id: str, conn) -> np.ndarray | None:
    row = await conn.execute_fetchone(
        "SELECT vector FROM clip_embeddings WHERE clip_id=?", (clip_id,)
    )
    if row is None:
        return None
    return np.frombuffer(row[0], dtype=np.float32).copy()
```

### Running Sync SDK in Thread Pool (Pitfall 4 Fix)

```python
# [ASSUMED] — standard asyncio.run_in_executor pattern
import asyncio

async def embed_worker(clip_id: str, clip_path: str) -> None:
    loop = asyncio.get_event_loop()
    vec, latency_ms = await loop.run_in_executor(
        None,  # default thread pool
        _sync_embed,  # plain synchronous function
        clip_path,
        clip_id,
    )
    await store_embedding(clip_id, vec, latency_ms, db_conn)

def _sync_embed(clip_path: str, clip_id: str) -> tuple[np.ndarray, int]:
    """Synchronous TwelveLabs embed call — safe to run in thread pool."""
    if config.USE_MOCK_EMBEDDINGS:
        return _mock_embedding(clip_id), 0
    client = TwelveLabs(api_key=config.TWELVELABS_API_KEY)
    t0 = time.monotonic()
    with open(clip_path, "rb") as f:
        asset = client.assets.create(method="direct", file=f)
    response = client.embed.v_2.create(
        input_type="video",
        model_name="marengo3.0",
        video=VideoInputRequest(
            media_source=MediaSource(asset_id=asset.id),
            embedding_option=["visual", "audio", "transcription"],
            embedding_scope=["asset"],
            embedding_type=["fused_embedding"],
        ),
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    vec = np.array(response.data[0].embedding, dtype=np.float32)
    vec /= np.linalg.norm(vec) + 1e-12
    return vec, latency_ms
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `client.embed.task.create(model_name=..., video_file=...)` | `client.assets.create()` then `client.embed.v_2.create()` | Embed API v2 introduced November 2025 | CRITICAL: old pattern raises SDK error in 1.2.3 |
| `Marengo-retrieval-2.7` model name string | `marengo3.0` (lowercase, no hyphen) | Sunset 2026-03-30 | Use the new name — old returns API error |
| `embedding_scope` as a string | `embedding_scope` as a list | SDK v2 | `["asset"]` not `"asset"` |
| 1024-d embedding vectors (Marengo 2.7) | 512-d (Marengo 3.0) | Marengo 3.0 GA | Smaller, faster cosine ops |
| Async polling (`wait_for_done`) for all clips | Sync `embed.v_2.create()` for <10 min clips | Embed API v2 | No polling needed for our 4-30s clips |

**Deprecated/outdated:**
- `client.embed.create(video_file=...)`: Pre-v2 pattern. Will raise AttributeError in SDK 1.2.3.
- `client.embed.task.create(...)`: Pre-v2 async task pattern. Use `embed.v_2.tasks.create()` if async path is needed.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Mock embedding determinism via `numpy.random.default_rng(hash(clip_id))` | Pattern 2 | If hash() is not stable across Python versions (it isn't for str in 3.3+ due to hash randomization — use `int.from_bytes(clip_id.encode()[:8], 'big')` instead) | HIGH: same clip_id must always produce same vector |
| A2 | TwelveLabs SDK 1.2.3 is synchronous (no async client) and requires `run_in_executor` | Pitfall 4 | If SDK exposes an async client, `run_in_executor` is unnecessary overhead but still safe |
| A3 | Pre-warm at startup pays the full cold-start cost for subsequent calls | Pitfall 3 | Marengo may have a per-request warm-up cost independent of connection warm-up; verify empirically on day 1 |
| A4 | `response.data[0].embedding` is a Python list of floats | Pattern 1 | If response structure differs slightly, traversal may need adjustment; verify with `python3 -c "print(type(response.data[0].embedding))"` on day 1 |

**Correction on A1 (IMPORTANT for planner):** Python's `hash()` for strings is randomized per process (PYTHONHASHSEED). Use `int.from_bytes(clip_id.encode('utf-8')[:8], 'big')` as the seed for a stable, deterministic mock vector:
```python
seed = int.from_bytes(clip_id.encode('utf-8')[:8], 'big') % (2**32)
rng = np.random.default_rng(seed)
```

---

## Open Questions

1. **Does `client.assets.create()` block until the asset is fully uploaded before returning?**
   - What we know: The SDK docs show it returns an `asset` object with an `id` — no polling described for assets.
   - What's unclear: Large files (approaching 200 MB) may have variable upload time.
   - Recommendation: For our clips (typically <20 MB for 30s at mobile resolution), blocking upload is fine. Log asset creation time separately from embed time for latency debugging.

2. **Should `client.assets.delete(asset.id)` be called after embed completes?**
   - What we know: Assets persist on TwelveLabs unless deleted; no storage cost is documented for dev tier.
   - What's unclear: Whether asset accumulation affects rate limits.
   - Recommendation: Skip deletion for the hackathon to save code complexity; one cleanup call at end of demo is sufficient.

3. **What error does the SDK raise if the clip is <4s (minimum Marengo requirement)?**
   - What we know: Marengo requires duration ≥4s. REQUIREMENTS.md CAP-05 enforces a 30s cap; there is no explicit minimum cap in the UI spec.
   - Recommendation: Add a 5-second minimum hold on the record button in Phase 1 if not already present (PITFALL-07 / CAP-05). In `embed_worker`, catch the error, set `embedding_status=failed`, and log clearly.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | Backend runtime | PARTIAL | 3.13.11 installed (not 3.11) | Use pyenv or system python; 3.13 may have patchy wheels for some deps — install 3.11 via pyenv before backend setup |
| `twelvelabs` | EMB-01 | ✓ (PyPI) | 1.2.3 | Mock mode (USE_MOCK_EMBEDDINGS=true) |
| `aiosqlite` | EMB-02 | Not confirmed | — | Required — `pip install aiosqlite` |
| `numpy` | EMB-02 | ✓ | 2.4.2 | — |
| `tenacity` | Retry wrapper | Not confirmed | — | `pip install tenacity` |
| `TWELVELABS_API_KEY` | EMB-01 | Not confirmed | — | USE_MOCK_EMBEDDINGS=true for dev |
| FastAPI + Uvicorn | Pipeline integration | ✓ | FastAPI 0.135.1, Uvicorn 0.41.0 | — |

**Missing dependencies with no fallback:**
- `aiosqlite` — required for async SQLite; install before starting
- `tenacity` — required for retry resilience; install before starting

**Missing dependencies with fallback:**
- Python 3.11 — project specifies 3.11; 3.13 is installed. CLAUDE.md says "avoid 3.13 — wheel availability still patchy." Set up `pyenv` virtual environment with Python 3.11 before beginning backend development.

---

## Project Constraints (from CLAUDE.md)

| Directive | Scope | Impact on Phase 2 |
|-----------|-------|-------------------|
| `twelvelabs==1.2.3` | Locked version | Pin exactly; do not upgrade |
| `marengo3.0` (lowercase, no hyphen) | model_name string | Literal string; not "Marengo-retrieval-3.0" or any other form |
| 512-d embeddings | Architecture | Use `fused_embedding` + `asset` scope to get exactly one 512-d vector per clip |
| `USE_MOCK_EMBEDDINGS=true` returns deterministic fake vectors | EMB-03 | Seeded RNG on clip_id; not random per call |
| Pre-warm Marengo on backend startup | EMB-05 | FastAPI `lifespan` event; must not crash server on pre-warm failure |
| SQLite aiosqlite WAL mode | Storage | All DB writes use aiosqlite; WAL pragma set on startup |
| No Celery, no message broker | Architecture | `asyncio.create_task` only; embed runs in thread pool executor (for sync SDK compat) |
| Embed latency is KILL-DEMO pitfall | PITFALL-1 | Fire-and-forget pattern locked in Phase 1; Phase 2 must not introduce any blocking in the HTTP path |
| `OFFLINE_DEMO=true` is a Phase 5 deliverable | Out of scope for Phase 2 | Mock mode (EMB-03) satisfies dev needs; full OFFLINE_DEMO built in Phase 5 |
| No accounts, no PII | Anonymity | Do not log user IP alongside clip_id in embed worker |
| Embed latency visible in debug overlay | EMB-04 | `embed_latency_ms` stored on clips row; served via `/clusters/:id` or debug endpoint |

---

## Validation Architecture

> `nyquist_validation` is `false` in `.planning/config.json`. Skipping this section.

---

## Security Domain

Phase 2 introduces the Twelve Labs API key. Relevant controls:

| Risk | Control |
|------|---------|
| `TWELVELABS_API_KEY` in source code | Load from `.env` via `python-dotenv`; `.env` in `.gitignore`; never in requirements.txt or any committed file |
| API key exposed in error logs | Catch SDK exceptions and log message only (not the full exception object which may include headers with auth) |
| Anonymous clip data: no PII in embed call | Only the video file binary is sent to TwelveLabs; no lat/lng, no session UUID, no user data. This is correct and should stay that way. |
| Upload size limit | Enforce max 100MB in FastAPI before calling assets.create(); prevents accidental giant upload |

---

## Sources

### Primary (HIGH confidence)
- [Twelve Labs Embed API v2 — Video Embeddings for new videos](https://docs.twelvelabs.io/docs/guides/create-embeddings/video/new) — two-step asset+embed pattern, sync vs async paths, response structure (verified 2026-04-24)
- [Twelve Labs Release Notes](https://docs.twelvelabs.io/docs/get-started/release-notes) — Embed API v2 introduced November 2025; Marengo 2.7 sunset March 2026 (verified 2026-04-24)
- [twelvelabs PyPI](https://pypi.org/project/twelvelabs/) — confirmed 1.2.3 is the latest stable version (verified 2026-04-24)
- [CLAUDE.md project constraints](/Users/roanhoward/Desktop/newz/CLAUDE.md) — pinned versions, model name, architecture constraints
- [.planning/research/STACK.md](/Users/roanhoward/Desktop/newz/.planning/research/STACK.md) — background stack context (HIGH confidence but pre-dates Embed API v2)
- [.planning/research/ARCHITECTURE.md](/Users/roanhoward/Desktop/newz/.planning/research/ARCHITECTURE.md) — pipeline patterns, SQLite schema (HIGH; patterns valid, embed call examples are pre-v2)

### Secondary (MEDIUM confidence)
- [Twelve Labs Create Embeddings overview](https://docs.twelvelabs.io/docs/guides/create-embeddings) — confirms Embed API v2 is the current path; `embedding_type` fused vs separate (verified 2026-04-24)
- [FastAPI Lifespan Events docs](https://fastapi.tiangolo.com/advanced/events/) — pre-warm pattern in lifespan context manager

### Tertiary (LOW confidence / training knowledge)
- Tenacity retry patterns — standard Python library; retry decorator usage is well-established [ASSUMED]
- `asyncio.run_in_executor` for sync libraries in async context — Python standard library pattern [ASSUMED]

---

## Metadata

**Confidence breakdown:**
- SDK API surface (embed.v_2 two-step): HIGH — verified against live TwelveLabs docs 2026-04-24
- Embed API v2 deprecation of old pattern: HIGH — release notes confirm November 2025 introduction
- Pre-warm effectiveness: MEDIUM — conceptually verified; actual cold-start reduction is empirical
- Mock embedding pattern: MEDIUM — standard pattern; hash seed caveat documented
- SQLite schema: HIGH — from project research ARCHITECTURE.md

**Research date:** 2026-04-24
**Valid until:** 2026-05-24 (stable API; Marengo 3.0 is current; SDK 1.2.3 pinned)

**Day-1 verification steps (planner should include as Wave 0 tasks):**
1. `pip show twelvelabs` — confirm 1.2.3
2. `python3 -c "from twelvelabs import TwelveLabs; c = TwelveLabs(api_key='x'); print(dir(c.embed)); print(dir(c.embed.v_2))"` — confirm v_2 subresource exists
3. `python3 -c "from twelvelabs.models.embed import VideoInputRequest, MediaSource; print('imports ok')"` — confirm model imports
4. Run one real embed against a 5s test clip and print `response.data[0].embedding[:5]` — confirm 512-d float list
