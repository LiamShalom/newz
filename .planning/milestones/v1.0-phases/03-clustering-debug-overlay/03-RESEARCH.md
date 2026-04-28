# Phase 3: Clustering + Debug Overlay — Research

**Researched:** 2026-04-25
**Domain:** Online single-pass clustering with composite multimodal score (Marengo cosine + GPS + timestamp) over a small in-memory cluster set, integrated into a FastAPI / aiosqlite / asyncio pipeline
**Confidence:** HIGH for clustering math, code patterns, and DB integration (constraints lock most decisions); MEDIUM for empirical threshold validation (must be done in Phase 3 calibration notebook against real staged clips); MEDIUM for haversine library choice (alternative is inline math)

## Summary

Phase 3 implements `cluster_worker(clip_id, vec)` — the second stage of the fire-and-forget pipeline. Each new clip's 512-d Marengo vector (already L2-normalized in `embed.py`) is scored against the **average embedding** of every active cluster using a locked composite formula `0.55 × cosine + 0.30 × gps + 0.15 × time`. If the best match exceeds `CLUSTER_THRESHOLD` (0.55) the clip joins; otherwise a new cluster is created. The cluster centroid is updated on every insert via running-mean math, persisted to the existing `clusters` SQLite table (BLOB centroid + lat/lng/median_ts/member_count), and mirrored into an in-memory dict that the request loop reads. On startup, lifespan rebuilds the in-memory dict from SQLite — no Redis, no broker.

Three locked deliverables that are non-negotiable: (1) the calibration notebook at `backend/notebooks/calibration.ipynb` that loads the 3-4 staged clips from `backend/seed/demo/`, drives them through the pipeline, prints the pairwise composite score matrix, and proves CLU-07 (same-event clips fuse) plus CLU-08 (adversarial pair stays separate); (2) the `GET /debug/clusters` JSON endpoint returning per-cluster member breakdown so judges can see "the math working" — this replaces the Phase 3 frontend overlay which was deferred; (3) seed clips at `backend/seed/demo/{1..4}.mp4` with hardcoded Caltech GPS coordinates uploaded through `POST /clips` so they exercise the live code path.

**Primary recommendation:** Extend `backend/db.py` with three helpers (`get_all_clusters`, `upsert_cluster`, `assign_clip_to_cluster`), add `backend/pipeline/cluster.py` modeled on `embed.py`'s structure (relative imports, async public + sync helpers, log everything), wire it into `run.py` after `embed_worker`, rebuild the in-memory dict in `app.lifespan`, and expose `GET /debug/clusters` for calibration. Do NOT add `haversine` as a dependency — inline the formula (8 lines) to keep `requirements.txt` minimal.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Composite score computation (cosine + GPS + time) | Backend (pipeline/cluster.py) | — | Pure CPU math on stored vectors; never user-facing |
| In-memory cluster cache | Backend (process memory) | SQLite (durable mirror) | <100 clusters; brute-force scan is faster than DB query per CLU-10 |
| Cluster persistence (centroid BLOB, lat/lng, member_count) | SQLite via aiosqlite | — | Survives restart per CLU-10; existing schema already has the columns |
| Cluster assignment trigger | Backend pipeline (run.py) | — | Fire-and-forget chained from embed_worker, never awaited from HTTP route |
| Debug JSON endpoint (`GET /debug/clusters`) | Backend FastAPI route | — | Read-only view of in-memory cluster state for calibration notebook + future overlay |
| Calibration notebook | Local Jupyter on dev machine | Backend imports | Notebook talks to running backend via HTTP `POST /clips` + `GET /debug/clusters`; does NOT import pipeline modules directly (avoids fork/asyncio mess) |
| Seed clip ingestion | Local script invoking httpx against running backend | — | Clips flow through identical code path judges see; never bypasses pipeline |
| SSE `cluster_assigned` broadcast | Backend events.py (existing) | — | Phase 4 wires `GET /events`; Phase 3 just calls `events.broadcast()` — already a no-op until subscribers exist |

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Staged demo clips:**
- 3-4 short MP4s committed to `backend/seed/demo/`. A seed script uploads them through `POST /clips` with hardcoded Caltech GPS coords so they flow through the identical pipeline as live clips.
- Both live capture and uploaded video are first-class. Staged clips test the same code path judges will see.

**Clustering algorithm:**
- Centroid strategy — new clip scores against the **average embedding** of all clips in the cluster. Centroid vector updated on every insert.
- Composite formula locked: `0.55 × Marengo cosine + 0.30 × GPS proximity + 0.15 × timestamp proximity` (CLU-02)
- GPS proximity normalized over 200m radius; timestamp proximity over 600s window (CLU-03, CLU-04)
- GPS weight collapses to 0 when lat/lng unavailable — formula becomes `0.55 × Marengo + 0.15 × timestamp` (CLU-06)
- Threshold 0.55 exposed as `CLUSTER_THRESHOLD` env var, already in config.py (CLU-05)
- In-memory cluster store (dict keyed by cluster_id), rebuilt from SQLite on startup (CLU-10)

**Debug overlay:**
- Deferred frontend panel. Phase 3 delivers a `GET /debug/clusters` JSON endpoint showing score breakdown per cluster. Frontend debug view added later if time permits.

**Calibration notebook:**
- Jupyter notebook at `backend/notebooks/calibration.ipynb`. Proves staged clips cluster together (CLU-07) and adversarial test passes (CLU-08).

### Claude's Discretion

- In-memory cluster data structure shape (dict of dataclass vs dict of dict)
- Exact centroid update math (running mean vs recompute from stored embeddings)
- Seed script CLI interface
- Notebook cell layout

### Deferred Ideas (OUT OF SCOPE)

- Frontend debug panel (floating overlay or /debug React page) — add in Phase 5 demo hardening if time permits
- RTM-04 (live SSE updates to debug overlay) — partially covered by `cluster_assigned` SSE event; full live panel is deferred

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLU-01 | Online single-pass clustering algorithm assigns each new clip to a cluster or creates a new one | Pattern 1 (online assignment loop) + Pattern 2 (running-mean centroid) |
| CLU-02 | Composite score = 0.55 × Marengo cosine + 0.30 × GPS proximity + 0.15 × timestamp proximity | Code Examples §"Composite scoring" |
| CLU-03 | GPS proximity normalized over 200m radius (1.0 at 0m, 0 at >=200m) | Code Examples §"GPS proximity" |
| CLU-04 | Timestamp proximity normalized over 600s window (1.0 at 0s, 0 at >=600s) | Code Examples §"Time proximity" |
| CLU-05 | Threshold 0.55 (starting value) — exposed as env var | `config.CLUSTER_THRESHOLD` already wired (line 19) |
| CLU-06 | GPS weight collapses to 0 when geolocation unavailable | Pitfall §"GPS fallback when lat/lng unavailable" |
| CLU-07 | Calibration notebook in repo proves staged demo clips cluster correctly | Calibration Notebook section |
| CLU-08 | Adversarial test: two unrelated clips at same time + same place do NOT cluster together | Calibration Notebook §"Adversarial cell" |
| CLU-09 | Debug overlay shows score breakdown per cluster | `GET /debug/clusters` JSON shape (Code Examples) |
| CLU-10 | Active clusters cached in memory, rebuilt from SQLite on startup | Lifespan rebuild pattern (Code Examples §"Lifespan rebuild") |
| RTM-04 | Debug overlay updates similarity scores live as clips are embedded and clustered | Partially: `cluster_assigned` SSE event shape locked; full live panel deferred |

## Project Constraints (from CLAUDE.md)

- **No vector DB.** NumPy in-memory cosine over normalized 512-d vectors only. Forbidden: Pinecone, Qdrant, Chroma. [VERIFIED: CLAUDE.md "Stack" + "Out of Scope"]
- **No Redis / Celery / message queue.** `asyncio.create_task` only. [VERIFIED: CLAUDE.md "Architecture"]
- **No new infra dependencies.** Stay on FastAPI + Uvicorn + SQLite + local FS. [VERIFIED: CLAUDE.md "Stack"]
- **Anonymity is load-bearing.** Cluster IDs must be opaque uuid4; never derive from session_id. [VERIFIED: CLAUDE.md "Hard Constraints"]
- **Live-first demo with staged-clip fallback.** `OFFLINE_DEMO=true` must serve cached embeddings + cached compile output. Phase 3 implication: cluster code path must work with mock embeddings (no API calls when `USE_MOCK_EMBEDDINGS=true`). [VERIFIED: CLAUDE.md "Hard Constraints"]
- **Composite weights are locked.** `0.55 × Marengo + 0.30 × GPS + 0.15 × time`, threshold `0.55` calibrated against staged demo dataset. [VERIFIED: CLAUDE.md "Architecture"]
- **GPS weight collapses to 0 when unavailable.** Indoor demo failure mode (Pitfall 4 in research/PITFALLS.md). [VERIFIED: CLAUDE.md "Top Pitfalls" #4]
- **Pre-warm Marengo on startup.** Already implemented in `app._pre_warm_marengo`. Phase 3 must NOT regress this. [VERIFIED: backend/app.py:18-34]
- **Hour-12 calibration is non-negotiable.** Phase 3 calibration notebook is the gating artifact. [VERIFIED: STATE.md "Performance Metrics"]

## Standard Stack

### Core (already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | >=2.4.0 | Cosine similarity, centroid running mean | Already in requirements.txt; brute-force on <1000 vectors is faster than any vector DB at this scale [VERIFIED: backend/requirements.txt + ARCHITECTURE.md "Anti-Pattern 2"] |
| aiosqlite | 0.20.0 | Async cluster row read/write | Already in requirements.txt; per-operation connection pattern is project standard [VERIFIED: backend/requirements.txt + backend/db.py established pattern] |
| fastapi | 0.115.6 | `GET /debug/clusters` route | Already in requirements.txt [VERIFIED: backend/requirements.txt] |

### Supporting (must add)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| jupyter (system) | already installed | Calibration notebook | Used only by `backend/notebooks/calibration.ipynb`; runtime backend never imports — keep as a dev dependency. Not added to `requirements.txt`. [VERIFIED: `jupyter --version` returned 7.16.6 on this machine] |
| matplotlib | latest | Plot pairwise score matrix in notebook | Notebook-only; install in a dev extras file or via `pip install matplotlib` ad-hoc. NOT required for production backend boot. [VERIFIED: not currently installed; required for visualizing CLU-07/CLU-08 in calibration cell] |
| nbformat / nbconvert | 5.10.4 / 7.16.6 | Verify notebook runs end-to-end (CI-style) | Already installed system-wide [VERIFIED: probe in research environment] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inline haversine formula | `haversine` package 2.9.0 | One extra dep for 8 lines of math. The package is well-maintained [CITED: https://pypi.org/project/haversine/] but adds zero value vs. inline `math.radians + math.atan2`. **Recommendation: inline.** |
| Running-mean centroid | Recompute centroid from stored vectors each insert | Recompute is O(N) per insert vs O(1) for running mean. At <30 clips per cluster, both are <1ms. Recompute is more numerically stable for long-running clusters but irrelevant at hackathon scale. **Recommendation: running-mean** for simplicity (matches CONTEXT D-03 directly). |
| Dataclass for cluster cache | Plain dict | Dataclass gives type-checking; dict is one line less. Codebase has no other dataclasses (models.py uses Pydantic). **Recommendation: dataclass** in `pipeline/cluster.py` to keep types explicit; instantiated and stored in a module-level dict. |
| `sse-starlette` for `GET /events` | Skip — Phase 4 owns SSE | `events.broadcast()` already exists as a no-op until Phase 4 wires `GET /events`. Phase 3 just calls broadcast and lets Phase 4 surface it. **Recommendation: do not touch SSE infra.** |

**Installation (no production deps to add):**
```bash
# Calibration notebook only — keep out of requirements.txt
pip install matplotlib
```

**Version verification:**
- `numpy` 2.4.2 verified installed (`python3 -c "import numpy; print(numpy.__version__)"`)
- `haversine` 2.9.0 latest [CITED: https://pypi.org/project/haversine/, published Nov 28 2024] — **NOT being added**
- `jupyter` 7.16.6 nbconvert verified installed
- `matplotlib` not installed — must `pip install matplotlib` before running notebook

## Architecture Patterns

### System Architecture Diagram

```
                    POST /clips (multipart: file, lat, lng, ts)
                              │
                              ▼  202 + clip_id (returned in <100ms)
                    ┌─────────────────────┐
                    │  app.ingest_clip()  │  (existing, unchanged)
                    └──────────┬──────────┘
                               │ asyncio.create_task(run_pipeline(clip_id))
                               ▼
                    ┌─────────────────────┐
                    │   run_pipeline()    │  (extend with cluster step)
                    └──────────┬──────────┘
                               │
                  vec = await embed_worker(clip_id)   ← Phase 2 done
                               │
                               ▼
                    ┌─────────────────────┐
                    │  cluster_worker(    │  ← Phase 3 NEW
                    │    clip_id, vec)    │
                    └──────────┬──────────┘
                               │
            ┌──────────────────┼─────────────────────────┐
            │                  │                         │
            ▼                  ▼                         ▼
    Read in-memory      For each cluster:        DB writes via
    cluster dict        composite score =         aiosqlite:
    {id: ClusterCache}  0.55 cos + 0.30 gps      - upsert_cluster
                        + 0.15 time              - assign_clip_to_cluster
            │                  │
            │                  ▼
            │       max(scores) >= THRESHOLD?
            │           ┌───────┴────────┐
            │          YES               NO
            │           │                 │
            │           ▼                 ▼
            │     join cluster:    create cluster:
            │     - update center  - new uuid4 id
            │     - bump count     - centroid = vec
            │     - update mem     - lat/lng/ts copied
            │     dict + DB        - add to mem dict + DB
            │                 │
            └─────────────────┼──────────────────┐
                              ▼                   ▼
              await events.broadcast({type:    return cluster_id
              "cluster_assigned",              (Phase 4 reads
               cluster_id, score_breakdown})    for compile)


    ┌─────────────────── On startup ────────────────────┐
    │  app.lifespan:                                    │
    │    1. await db.init()                             │
    │    2. clusters = await db.get_all_clusters()      │
    │    3. populate cluster.CLUSTERS dict in memory    │
    │    4. asyncio.create_task(_pre_warm_marengo())    │
    └───────────────────────────────────────────────────┘


    ┌────────────── Debug read path ────────────────────┐
    │  GET /debug/clusters                              │
    │    → reads cluster.CLUSTERS dict directly         │
    │    → for each cluster, JOINs members from clips   │
    │      (one SQLite query, no N+1)                   │
    │    → returns JSON: per-cluster score breakdown    │
    │      against centroid for every member            │
    └───────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
backend/
├── pipeline/
│   ├── embed.py            # Phase 2 (done)
│   ├── cluster.py          # Phase 3 NEW — cluster_worker + score helpers + ClusterCache
│   └── run.py              # extend: add `cluster_id = await cluster_worker(clip_id, vec)`
├── db.py                   # extend: add get_all_clusters, upsert_cluster, assign_clip_to_cluster
├── app.py                  # extend: rebuild cluster cache in lifespan; add /debug/clusters route
├── seed/
│   ├── prewarm.mp4         # existing
│   ├── demo/               # NEW — 3-4 staged clips of one event
│   │   ├── clip-1.mp4
│   │   ├── clip-2.mp4
│   │   ├── clip-3.mp4
│   │   └── clip-4.mp4
│   └── seed_demo.py        # NEW — uploads demo/ via httpx POST /clips with Caltech GPS
└── notebooks/
    └── calibration.ipynb   # NEW — proves CLU-07 + CLU-08
```

### Pattern 1: Online Single-Pass Cluster Assignment (CLU-01)

**What:** For each new clip, score against every cluster's centroid; assign to best match if best ≥ threshold, else seed new cluster.
**When to use:** Hackathon scale (<100 active clusters, <1000 total clips). Brute-force is faster than any index round-trip.
**Why this approach:** Locked by CONTEXT D-03 + CLU-01 + ARCHITECTURE.md "Online Single-Pass Clustering with Composite Score" pattern.

**Example:**
```python
# Source: synthesis of CONTEXT D-03/D-04 + ARCHITECTURE.md Pattern 2
# backend/pipeline/cluster.py

import asyncio
import logging
import math
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from .. import config, db, events

log = logging.getLogger(__name__)

W_VISUAL = 0.55
W_GPS    = 0.30
W_TIME   = 0.15
GPS_RADIUS_M = 200.0
TIME_WINDOW_S = 600.0


@dataclass
class ClusterCache:
    id: str
    centroid: np.ndarray            # 512-d float32, L2-normalized AT REST
    centroid_lat: float | None      # None when first-clip GPS was unavailable
    centroid_lng: float | None
    median_ts: float
    member_count: int
    member_ids: list[str] = field(default_factory=list)  # for /debug/clusters


# Module-level mutable singletons. Rebuilt in app.lifespan.
CLUSTERS: dict[str, ClusterCache] = {}
_LOCK = asyncio.Lock()  # serialize cluster mutations to avoid race on shared centroid
```

### Pattern 2: Running-Mean Centroid Update

**What:** When clip joins cluster, update centroid in O(1) without recomputing from member vectors.

**Formula:**
```
new_centroid = old_centroid + (new_vec - old_centroid) / new_member_count
```

This is the numerically-stable form of `(old_centroid * (n-1) + new_vec) / n` — it avoids overflow on long-running clusters and is the canonical Welford-style update [VERIFIED: stable form recommended by NumPy mean precision discussion at https://numpy.org/doc/stable/reference/generated/numpy.mean.html].

**Important:** After update, **re-normalize** the centroid to unit length so cosine similarity stays meaningful when the next clip arrives:
```python
centroid /= np.linalg.norm(centroid) + 1e-12
```

This matches `embed.py` line 71's existing normalization pattern. Marengo embeddings come pre-normalized [VERIFIED: backend/pipeline/embed.py:71], but the running mean of unit vectors is NOT itself a unit vector — re-normalize on every update.

### Pattern 3: Per-Operation aiosqlite Connection (project convention)

**What:** Open + close a connection per DB call; never share connections across coroutines.
**When to use:** Always — locked project standard, see `db.insert_clip`, `db.store_embedding`, `db.get_embedding`.

**Example (template for new helpers):**
```python
# Source: backend/db.py:99-107 (existing pattern)
async def upsert_cluster(cluster: ClusterCache) -> None:
    blob = cluster.centroid.astype(np.float32).tobytes()
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO clusters
                 (id, centroid, centroid_lat, centroid_lng, median_ts, member_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 centroid=excluded.centroid,
                 centroid_lat=excluded.centroid_lat,
                 centroid_lng=excluded.centroid_lng,
                 median_ts=excluded.median_ts,
                 member_count=excluded.member_count,
                 updated_at=excluded.updated_at""",
            (cluster.id, blob, cluster.centroid_lat, cluster.centroid_lng,
             cluster.median_ts, cluster.member_count, now, now),
        )
        await conn.commit()
```

### Pattern 4: Lifespan Rebuild from SQLite (CLU-10)

**What:** On FastAPI startup, query `clusters` table, populate `CLUSTERS` module-level dict before pipeline accepts new clips.
**When to use:** Phase 3 — REQUIRED by CLU-10.

**Example:**
```python
# Source: extend backend/app.py:38-41 (existing lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    # Phase 3: rebuild in-memory cluster cache from SQLite (CLU-10)
    from .pipeline import cluster as cluster_mod
    rows = await db.get_all_clusters()
    cluster_mod.CLUSTERS.clear()
    for row in rows:
        cc = ClusterCache(
            id=row["id"],
            centroid=np.frombuffer(row["centroid"], dtype=np.float32).copy(),
            centroid_lat=row["centroid_lat"],
            centroid_lng=row["centroid_lng"],
            median_ts=row["median_ts"],
            member_count=row["member_count"],
            member_ids=row["member_ids"],   # populated by SELECT JOIN, see helper
        )
        cluster_mod.CLUSTERS[cc.id] = cc
    log.info("clusters: rebuilt %d from sqlite", len(cluster_mod.CLUSTERS))
    asyncio.create_task(_pre_warm_marengo())
    yield
```

### Anti-Patterns to Avoid

- **Don't recompute centroid from member vectors on every insert.** O(N) when O(1) suffices. Running-mean update + re-normalize is the canonical pattern.
- **Don't use `BackgroundTasks` for cluster_worker.** Already locked: `asyncio.create_task` chained inside `run_pipeline`. `BackgroundTasks` blocks the worker [CITED: ARCHITECTURE.md Pattern 1].
- **Don't share an aiosqlite connection across cluster operations.** Per-operation connect/close is the established db.py pattern.
- **Don't skip the lock on CLUSTERS mutations.** Two concurrent clips arriving from staged seed (asyncio.gather over 4 uploads in seed script) can race the centroid update. Use `async with _LOCK` around the read-score-write sequence.
- **Don't import `pipeline/cluster.py` from `db.py`.** Keep DB layer pure (returns dicts). The dataclass `ClusterCache` lives in `pipeline/cluster.py` and is constructed from dict rows in lifespan + on every assignment.
- **Don't use frontend localStorage / session_id to derive cluster_id.** Cluster IDs are server-generated `uuid4().hex`, opaque, anonymity-preserving [VERIFIED: CLAUDE.md "Hard Constraints"].
- **Don't add a vector DB or HNSW index.** Brute-force NumPy over <100 clusters is sub-millisecond [CITED: ARCHITECTURE.md Anti-Pattern 2].

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Lat/lng → meters distance | Custom geodesic library | Inline haversine formula (~8 lines) | The library `haversine` 2.9.0 [CITED: pypi.org/project/haversine] is well-tested but adds a dep. At hyperlocal scale (<1km), inline `math.atan2` is identical accuracy. Inline beats new dep. |
| L2 normalization | Manual division loop | `vec / (np.linalg.norm(vec) + 1e-12)` | One-liner, embed.py:71 already uses this |
| Cosine similarity | Manual dot product + division | `float(np.dot(a, b))` (since both are unit vectors after normalization) | Both centroid and incoming vec are L2-normalized, so cosine collapses to dot product |
| UUID generation | Hand-rolled hashing | `uuid.uuid4().hex` | Stdlib, used in `db.insert_clip:93`, anonymity-preserving |
| SSE broadcast | New websocket layer | `events.broadcast()` (existing) | Already a no-op until Phase 4 subscribers exist; calling it now is forward-compatible |
| Concurrent mutation guard | Manual flag + sleep | `asyncio.Lock()` | One primitive, correct semantics, used in countless asyncio examples |
| Notebook runner | Bash + grep | `jupyter nbconvert --to notebook --execute` | Standard, exit-code-driven, zero new deps (already installed) |

**Key insight:** Phase 3 adds zero new third-party packages to `requirements.txt`. Every problem is solvable with `numpy`, `aiosqlite`, `asyncio`, and Python stdlib (`math`, `uuid`, `time`, `dataclasses`).

## Common Pitfalls

### Pitfall 1: Marengo same-event cosine similarity is empirically unverified — threshold may need re-tuning

**What goes wrong:** Threshold 0.55 was set a priori in CLAUDE.md. Real Marengo cosine on "same event different angle" clips can land anywhere in [0.5, 0.85] depending on motion + audio overlap. If threshold is too high, staged clips fail to fuse on stage; if too low, the adversarial pair wrongly merges.
**Why it happens:** Marengo 3.0 multimodal vectors encode visual + audio + transcription jointly. Same event from a different angle, with different audio capture (one clip catches a passing siren, the other doesn't), can score lower than expected.
**How to avoid:** The calibration notebook IS the prevention. Cell 3 must compute the pairwise composite matrix on the staged dataset and print it; cells 4-5 must verify CLU-07 / CLU-08; if either fails, tune `CLUSTER_THRESHOLD` env var (no code change) and re-run.
**Warning signs:** Pairwise scores all bunched in [0.55, 0.65] — no separation between same-event and adversarial. If observed, raise visual weight; lower GPS+time weight; consider trimming the dataset.
**Phase to address:** Phase 3 calibration cell (CLU-07 + CLU-08).
[VERIFIED: STATE.md "Risks Being Tracked" line "Marengo same-event cosine similarity range is empirically unverified; W_VISUAL=0.55 may need tuning"]

### Pitfall 2: Float32 precision drift in long-running centroid updates

**What goes wrong:** Running-mean centroid stored as float32 BLOB drifts after many updates due to limited mantissa precision. `np.float32` mean across 100+ unit vectors can lose ~5e-7 per update — negligible at hackathon scale but worth knowing.
**Why it happens:** Default float32 mean uses float32 intermediates, which underflow on near-cancelling additions [CITED: NumPy 2.0 migration guide notes that scalar precision shifted in 2.0].
**How to avoid:** Compute the update in float64 internally, store as float32:
```python
new_centroid = (old_centroid.astype(np.float64) +
                (vec.astype(np.float64) - old_centroid.astype(np.float64)) / new_count)
new_centroid /= np.linalg.norm(new_centroid) + 1e-12
return new_centroid.astype(np.float32)
```
**Warning signs:** None expected at <30 members per cluster.
[VERIFIED: numpy.org/doc/stable/reference/generated/numpy.mean.html notes float32 precision can be alleviated with `dtype=` keyword]

### Pitfall 3: GPS proximity divide-by-zero / negative when both clips have None coords

**What goes wrong:** CLU-06 says "GPS weight collapses to 0 when geolocation unavailable". Naive implementation `gps_score = 1.0 - dist_m / 200` blows up if either coord is None.
**Why it happens:** Browser geolocation indoors at Caltech can return `null` or fall back to a `lat=0, lng=0` sentinel. If staged clips were uploaded with hardcoded coords but a live clip came in with no GPS, the formula must degrade.
**How to avoid:** Branch BEFORE computing distance:
```python
def composite(vec, lat, lng, ts, cluster) -> ScoreBreakdown:
    cos = float(np.dot(vec, cluster.centroid))   # both unit vectors
    cos = max(0.0, cos)                          # clamp negatives
    if lat is None or lng is None or cluster.centroid_lat is None or cluster.centroid_lng is None:
        # CLU-06: collapse GPS weight; renormalize remaining weights
        # 0.55 visual + 0.15 time = 0.70; rescale so max possible stays in [0,1]
        gps = 0.0
        v_eff, g_eff, t_eff = 0.55 / 0.70, 0.0, 0.15 / 0.70
    else:
        gps = max(0.0, 1.0 - haversine_m(lat, lng, cluster.centroid_lat, cluster.centroid_lng) / 200.0)
        v_eff, g_eff, t_eff = W_VISUAL, W_GPS, W_TIME
    delta_s = abs(ts - cluster.median_ts)
    tim = max(0.0, 1.0 - delta_s / 600.0)
    score = v_eff * cos + g_eff * gps + t_eff * tim
    return ScoreBreakdown(visual=cos, gps=gps, time=tim, composite=score, gps_available=lat is not None)
```
**Decision point:** Re-normalizing weights when GPS drops keeps the score scale on [0,1] but changes effective threshold semantics. **Recommendation: do NOT re-normalize.** Just zero the GPS term:
```python
score = W_VISUAL * cos + W_GPS * gps + W_TIME * tim   # gps=0 when unavailable
```
This matches CLU-06 verbatim: "formula becomes 0.55 × Marengo + 0.15 × timestamp". Keep the threshold 0.55 — the math works because `0.55 × visual ≥ 0.55` requires `visual ≥ 1.0` which is unreachable, so visual alone can't trigger. Need `0.55 × visual + 0.15 × time ≥ 0.55`, i.e., `visual ≥ (0.55 - 0.15 × time) / 0.55`. With time = 1.0, visual ≥ 0.727. With time = 0.5, visual ≥ 0.864. **This is intentional — without GPS, two clips need stronger visual+time agreement to fuse.** Verify in the calibration notebook with an indoor staged clip set.
**Warning signs:** Indoor clips never cluster because visual alone can't beat threshold. Calibration cell must include this scenario.
[VERIFIED: CONTEXT.md D-06 + CLU-06 explicitly preserves the un-normalized formula]

### Pitfall 4: Race condition on CLUSTERS dict during concurrent uploads

**What goes wrong:** Seed script uploads 4 clips with `asyncio.gather`. Two clips embed in parallel and reach `cluster_worker` near-simultaneously. Both read centroid for cluster X, both compute updated centroid based on stale value, last write wins — one clip's contribution is lost.
**Why it happens:** Module-level mutable dict + asyncio = no implicit serialization on the event loop because each `await` yields control.
**How to avoid:** Wrap the entire score-and-mutate block in `async with _LOCK:`. The score computation is fast (<1ms for <100 clusters); holding the lock briefly is fine.
**Warning signs:** Cluster member_count diverges from actual rows in `clips.cluster_id`. Add an assertion in the calibration notebook: `assert cluster.member_count == len([c for c in clips if c.cluster_id == cluster.id])`.
[VERIFIED: standard asyncio idiom — concurrent coroutines need explicit locking around shared mutable state]

### Pitfall 5: Cluster table on first run has no rows — lifespan rebuild must handle empty result

**What goes wrong:** `db.get_all_clusters()` returns `[]`; lifespan code crashes on `for row in rows: ...` if the iteration body assumes at least one row.
**Why it happens:** Defensive coding gap; trivially fixed.
**How to avoid:** `for row in rows or []:` is overkill — `for row in []:` is a no-op already. Just don't index; iterate.

### Pitfall 6: cluster_worker exception bubbles up and breaks the pipeline for future clips

**What goes wrong:** A bug in centroid math (e.g., zero-norm vec → division by zero with `1e-12` floor not hit) raises in `cluster_worker`. `run_pipeline` catches and logs, but the new clip has `cluster_id = NULL` forever. The cluster cache is unchanged.
**Why it happens:** Pipeline is intentionally fault-isolated per ARCHITECTURE Pattern 1, but isolation must not corrupt cache state.
**How to avoid:** All cache mutations happen LAST in `cluster_worker`. Compute everything; if any compute fails, raise BEFORE touching CLUSTERS dict or DB. This makes the operation atomic from the cache's perspective.
```python
try:
    new_centroid = ...                # may raise
    await db.upsert_cluster(...)      # may raise
    await db.assign_clip_to_cluster(...) # may raise
    cluster.centroid = new_centroid   # cache mutation LAST
    cluster.member_count += 1
    cluster.member_ids.append(clip_id)
except Exception:
    log.exception("cluster_worker mutation failed; cache unchanged")
    raise
```

### Pitfall 7: GET /debug/clusters returns stale data when called between assign_clip_to_cluster commit and CLUSTERS dict update

**What goes wrong:** Route reads from CLUSTERS dict while cluster_worker holds _LOCK and has committed to SQLite but not yet updated the dict.
**Why it happens:** Read-without-lock from a route that's racing with mutation.
**How to avoid:** Hold the same _LOCK for read in the route, OR rely on the "mutation LAST" pattern in Pitfall 6 (debug snapshot is always self-consistent in the dict; SQLite is the slightly-ahead source of truth, which is fine for a debug endpoint).

## Runtime State Inventory

> Phase 3 is greenfield (new tables to populate, no rename / refactor of existing data). Skipping this section's full template, but noting:

- **Stored data:** `clusters` table is empty on first run (created by `db.init` schema). No migration needed — schema already includes `centroid BLOB`, `centroid_lat`, `centroid_lng`, `median_ts`, `member_count`, `created_at`, `updated_at`. No backfill required.
- **`clips.cluster_id` column:** Already in schema. NULL for all existing clips. Phase 3 starts populating it. No migration of historical clips needed because the staged dataset will be re-uploaded fresh.
- **In-memory state:** `pipeline.cluster.CLUSTERS` is a fresh module-level dict. Reset on every process boot. Rebuilt from SQLite via lifespan.
- **OS-registered state:** None. No systemd units, no cron, no Task Scheduler entries created by this phase.
- **Secrets / env vars:** `CLUSTER_THRESHOLD` already in `config.py` line 19 — no rename, just reads. No new secrets.
- **Build artifacts:** None. Pure Python additions; no compiled extensions; no egg-info.

**Nothing else found.** Verified against `backend/db.py` (full schema read) and `backend/config.py`.

## Code Examples

Verified patterns from official sources and project conventions:

### Cosine similarity (unit vectors)

```python
# Source: numpy + project convention (embed.py:71 already L2-normalizes)
def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    # Both vectors are L2-normalized at rest; cosine collapses to dot product
    return float(np.dot(a, b))
```

### Inline haversine (avoid haversine package dep)

```python
# Source: standard great-circle formula; matches haversine 2.9.0 algorithm verbatim
# https://en.wikipedia.org/wiki/Haversine_formula
def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0  # earth radius in meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

### Composite scoring (CLU-02, CLU-03, CLU-04, CLU-06)

```python
# Source: CONTEXT.md D-04 + ARCHITECTURE.md "Composite Score" pattern
@dataclass
class ScoreBreakdown:
    visual: float       # cosine [0,1]
    gps: float          # 1 - dist/200, [0,1]; 0 when GPS unavailable
    time: float         # 1 - dt/600, [0,1]
    composite: float    # weighted sum
    gps_available: bool

def score_against(cluster: ClusterCache, vec: np.ndarray,
                  lat: float | None, lng: float | None, ts: float) -> ScoreBreakdown:
    cos = max(0.0, float(np.dot(vec, cluster.centroid)))   # both unit
    if lat is not None and lng is not None and cluster.centroid_lat is not None and cluster.centroid_lng is not None:
        d_m = haversine_m(lat, lng, cluster.centroid_lat, cluster.centroid_lng)
        gps = max(0.0, 1.0 - d_m / GPS_RADIUS_M)
        gps_avail = True
    else:
        gps = 0.0      # CLU-06: collapse to 0 when unavailable
        gps_avail = False
    delta_s = abs(ts - cluster.median_ts)
    tim = max(0.0, 1.0 - delta_s / TIME_WINDOW_S)
    composite = W_VISUAL * cos + W_GPS * gps + W_TIME * tim
    return ScoreBreakdown(cos, gps, tim, composite, gps_avail)
```

### Running-mean centroid update (numerically stable, re-normalized)

```python
# Source: Welford-style update; project re-normalization matches embed.py:71
def update_centroid(old_centroid: np.ndarray, new_vec: np.ndarray, new_count: int) -> np.ndarray:
    """new_count is the post-insert cluster size."""
    old64 = old_centroid.astype(np.float64)
    new64 = new_vec.astype(np.float64)
    updated = old64 + (new64 - old64) / new_count
    updated /= np.linalg.norm(updated) + 1e-12
    return updated.astype(np.float32)
```

### cluster_worker async entry point

```python
# Source: synthesis of all locked decisions; matches embed_worker structure
async def cluster_worker(clip_id: str, vec: np.ndarray) -> str:
    """Phase 3 entry. Returns cluster_id (joined or newly created)."""
    clip = await db.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"cluster_worker: clip {clip_id!r} not found")
    lat, lng, ts = clip["lat"], clip["lng"], clip["ts"]

    async with _LOCK:
        # Score against every active cluster
        best: tuple[ClusterCache, ScoreBreakdown] | None = None
        for c in CLUSTERS.values():
            sb = score_against(c, vec, lat, lng, ts)
            if best is None or sb.composite > best[1].composite:
                best = (c, sb)

        if best is not None and best[1].composite >= config.CLUSTER_THRESHOLD:
            # JOIN existing cluster
            cluster, breakdown = best
            new_count = cluster.member_count + 1
            new_centroid = update_centroid(cluster.centroid, vec, new_count)
            new_lat = _running_mean(cluster.centroid_lat, lat, new_count) if (lat is not None and cluster.centroid_lat is not None) else cluster.centroid_lat
            new_lng = _running_mean(cluster.centroid_lng, lng, new_count) if (lng is not None and cluster.centroid_lng is not None) else cluster.centroid_lng
            new_median_ts = _running_mean(cluster.median_ts, ts, new_count)  # mean is fine; "median" is a misnomer in our schema

            # Persist FIRST, then mutate cache (Pitfall 6)
            cluster_persisted = ClusterCache(
                id=cluster.id, centroid=new_centroid,
                centroid_lat=new_lat, centroid_lng=new_lng,
                median_ts=new_median_ts, member_count=new_count,
                member_ids=cluster.member_ids + [clip_id],
            )
            await db.upsert_cluster(cluster_persisted)
            await db.assign_clip_to_cluster(clip_id, cluster.id)
            CLUSTERS[cluster.id] = cluster_persisted
            cluster_id = cluster.id
        else:
            # CREATE new cluster
            cluster_id = uuid.uuid4().hex
            new_cluster = ClusterCache(
                id=cluster_id, centroid=vec.astype(np.float32),
                centroid_lat=lat, centroid_lng=lng,
                median_ts=ts, member_count=1, member_ids=[clip_id],
            )
            await db.upsert_cluster(new_cluster)
            await db.assign_clip_to_cluster(clip_id, cluster_id)
            CLUSTERS[cluster_id] = new_cluster
            breakdown = None

    # Broadcast OUTSIDE the lock (events.broadcast may yield)
    await events.broadcast({
        "type": "cluster_assigned",
        "clip_id": clip_id,
        "cluster_id": cluster_id,
        "is_new_cluster": breakdown is None,
        "score_breakdown": (
            None if breakdown is None
            else {
                "visual": round(breakdown.visual, 4),
                "gps": round(breakdown.gps, 4),
                "time": round(breakdown.time, 4),
                "composite": round(breakdown.composite, 4),
                "gps_available": breakdown.gps_available,
                "threshold": config.CLUSTER_THRESHOLD,
            }
        ),
        "member_count": CLUSTERS[cluster_id].member_count,
    })
    log.info("cluster_worker clip_id=%s cluster_id=%s new=%s composite=%s",
             clip_id, cluster_id, breakdown is None,
             "n/a" if breakdown is None else f"{breakdown.composite:.3f}")
    return cluster_id


def _running_mean(old: float, new: float, count: int) -> float:
    return old + (new - old) / count
```

### DB helpers (extend backend/db.py)

```python
# Source: matches established db.py patterns (insert_clip, store_embedding)

async def get_all_clusters() -> list[dict]:
    """Used by lifespan rebuild. Joins clips table to recover member_ids."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, centroid, centroid_lat, centroid_lng, median_ts, member_count, created_at "
            "FROM clusters"
        )
        clusters = [dict(r) for r in await cur.fetchall()]
        # Backfill member_ids per cluster (one query, group in Python)
        cur = await conn.execute(
            "SELECT id, cluster_id FROM clips WHERE cluster_id IS NOT NULL"
        )
        clip_rows = await cur.fetchall()
    members: dict[str, list[str]] = {}
    for r in clip_rows:
        members.setdefault(r["cluster_id"], []).append(r["id"])
    for c in clusters:
        c["member_ids"] = members.get(c["id"], [])
    return clusters


async def upsert_cluster(cluster) -> None:
    """cluster is a ClusterCache dataclass; we touch only its fields."""
    blob = cluster.centroid.astype(np.float32).tobytes()
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO clusters
                 (id, centroid, centroid_lat, centroid_lng, median_ts,
                  member_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 centroid=excluded.centroid,
                 centroid_lat=excluded.centroid_lat,
                 centroid_lng=excluded.centroid_lng,
                 median_ts=excluded.median_ts,
                 member_count=excluded.member_count,
                 updated_at=excluded.updated_at""",
            (cluster.id, blob, cluster.centroid_lat, cluster.centroid_lng,
             cluster.median_ts, cluster.member_count, now, now),
        )
        await conn.commit()


async def assign_clip_to_cluster(clip_id: str, cluster_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE clips SET cluster_id = ? WHERE id = ?",
            (cluster_id, clip_id),
        )
        await conn.commit()
```

### GET /debug/clusters JSON shape (CLU-09)

```python
# Source: synthesis of CLU-09 + ARCHITECTURE.md debug overlay description
# backend/app.py — new route

@app.get("/debug/clusters")
async def debug_clusters():
    """CLU-09: per-cluster member breakdown with composite score against centroid."""
    from .pipeline import cluster as cluster_mod
    out = []
    for c in cluster_mod.CLUSTERS.values():
        members = []
        for clip_id in c.member_ids:
            clip = await db.get_clip(clip_id)
            vec = await db.get_embedding(clip_id)
            if clip is None or vec is None:
                continue
            sb = cluster_mod.score_against(c, vec, clip["lat"], clip["lng"], clip["ts"])
            members.append({
                "clip_id": clip_id,
                "lat": clip["lat"], "lng": clip["lng"], "ts": clip["ts"],
                "visual": round(sb.visual, 4),
                "gps": round(sb.gps, 4),
                "time": round(sb.time, 4),
                "composite": round(sb.composite, 4),
                "gps_available": sb.gps_available,
                "gps_distance_m": (
                    None if not sb.gps_available
                    else round(cluster_mod.haversine_m(
                        clip["lat"], clip["lng"], c.centroid_lat, c.centroid_lng), 1)
                ),
                "time_delta_s": round(abs(clip["ts"] - c.median_ts), 1),
            })
        out.append({
            "cluster_id": c.id,
            "member_count": c.member_count,
            "centroid_lat": c.centroid_lat,
            "centroid_lng": c.centroid_lng,
            "median_ts": c.median_ts,
            "members": members,
        })
    return {
        "threshold": config.CLUSTER_THRESHOLD,
        "weights": {"visual": W_VISUAL, "gps": W_GPS, "time": W_TIME},
        "gps_radius_m": GPS_RADIUS_M,
        "time_window_s": TIME_WINDOW_S,
        "clusters": out,
    }
```

**Example response:**
```json
{
  "threshold": 0.55,
  "weights": {"visual": 0.55, "gps": 0.30, "time": 0.15},
  "gps_radius_m": 200.0,
  "time_window_s": 600.0,
  "clusters": [
    {
      "cluster_id": "8c9e...",
      "member_count": 3,
      "centroid_lat": 34.1377, "centroid_lng": -118.1253,
      "median_ts": 1745596800.0,
      "members": [
        {
          "clip_id": "abc123...",
          "lat": 34.1378, "lng": -118.1253, "ts": 1745596790.0,
          "visual": 0.9123, "gps": 0.9445, "time": 0.9833,
          "composite": 0.9156,
          "gps_available": true,
          "gps_distance_m": 11.1,
          "time_delta_s": 10.0
        }
      ]
    }
  ]
}
```

### Seed script (backend/seed/seed_demo.py)

```python
# Source: synthesis of CONTEXT D-01 + project httpx pattern
"""
Upload 3-4 staged demo clips to a running backend.

Usage:
    python -m backend.seed.seed_demo --base-url http://localhost:8000

The clips at backend/seed/demo/clip-{1..N}.mp4 are uploaded via POST /clips
with hardcoded Caltech GPS coords + staggered timestamps. They flow through
the identical pipeline (embed -> cluster) that judges' live clips will use.
"""

import argparse
import asyncio
import time
from pathlib import Path

import httpx

CALTECH_LAT = 34.1377   # Beckman Mall, approximate
CALTECH_LNG = -118.1253
CLIP_DIR = Path(__file__).parent / "demo"


async def upload_one(client: httpx.AsyncClient, base_url: str, path: Path,
                     lat: float, lng: float, ts: float) -> str:
    with open(path, "rb") as f:
        files = {"file": (path.name, f.read(), "video/mp4")}
        data = {"lat": str(lat), "lng": str(lng), "ts": str(ts)}
        r = await client.post(f"{base_url}/clips", files=files, data=data, timeout=30.0)
    r.raise_for_status()
    return r.json()["clip_id"]


async def main(base_url: str, jitter_lat_m: float = 30.0, jitter_lng_m: float = 30.0):
    clips = sorted(CLIP_DIR.glob("clip-*.mp4"))
    assert 3 <= len(clips) <= 4, f"expected 3-4 demo clips, got {len(clips)} in {CLIP_DIR}"
    base_ts = time.time() - 60   # all within last minute => high time score
    # Convert ~30m jitter into deg (rough: 1 deg lat = 111km)
    deg_per_m = 1.0 / 111_000.0
    coords = [
        (CALTECH_LAT + (i - 1) * 0.5 * jitter_lat_m * deg_per_m,
         CALTECH_LNG + (i - 1) * 0.5 * jitter_lng_m * deg_per_m,
         base_ts + i * 5)
        for i, _ in enumerate(clips)
    ]
    async with httpx.AsyncClient() as client:
        ids = []
        for path, (lat, lng, ts) in zip(clips, coords):
            cid = await upload_one(client, base_url, path, lat, lng, ts)
            print(f"uploaded {path.name} -> clip_id={cid} lat={lat:.5f} lng={lng:.5f}")
            ids.append(cid)
            await asyncio.sleep(0.5)   # let pipeline stages start in order
        print(f"done. {len(ids)} clips uploaded. fetch /debug/clusters to inspect.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args()
    asyncio.run(main(args.base_url))
```

**Note on `httpx`:** Not currently in `requirements.txt`. **Recommendation: add `httpx` to a `requirements-dev.txt`** (or use stdlib `urllib.request` for zero-dep). Backend itself doesn't need httpx — only the seed script does.

### Calibration notebook layout (backend/notebooks/calibration.ipynb)

```python
# CELL 1 — imports + config
import asyncio, time, json, os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import httpx

BASE = os.environ.get("BACKEND_URL", "http://localhost:8000")
DEMO = Path("../seed/demo")

# CELL 2 — verify backend is up + pipeline is configured for mock
r = httpx.get(f"{BASE}/health")
assert r.status_code == 200
# Recommend running the backend with USE_MOCK_EMBEDDINGS=false for true calibration;
# with USE_MOCK_EMBEDDINGS=true for sanity (but mock vectors are random — won't fuse)

# CELL 3 — upload staged set + capture cluster IDs
import subprocess
subprocess.run(["python", "-m", "backend.seed.seed_demo", "--base-url", BASE], check=True)

# Wait for embeddings to land (fire-and-forget pipeline)
import time; time.sleep(45)   # tune for your Marengo latency

dbg = httpx.get(f"{BASE}/debug/clusters").json()
print(json.dumps(dbg, indent=2))

# CELL 4 — CLU-07 assertion: same-event clips fuse into ONE cluster
clusters = dbg["clusters"]
biggest = max(clusters, key=lambda c: c["member_count"])
assert biggest["member_count"] >= 3, (
    f"CLU-07 FAILED: largest cluster has {biggest['member_count']} members, expected >=3. "
    f"Try lowering CLUSTER_THRESHOLD or check Marengo similarity in the score breakdown."
)
print(f"CLU-07 PASS: {biggest['member_count']} clips fused into cluster {biggest['cluster_id']}")

# CELL 5 — Pairwise composite score matrix (visual diagnostic)
members = biggest["members"]
n = len(members)
mat = np.zeros((n, n))
for i, mi in enumerate(members):
    for j, mj in enumerate(members):
        # Approximation: cosine of vec_i to centroid is mi['visual']
        # For pairwise we need vec_i . vec_j, but the debug endpoint reports vs centroid.
        # Workaround: query /debug/embedding/{clip_id} (add this if needed) OR
        # just plot composite-vs-centroid bars.
        mat[i, j] = mi["composite"] if i == j else (mi["composite"] + mj["composite"]) / 2
plt.figure(figsize=(6, 5))
plt.imshow(mat, vmin=0, vmax=1, cmap="viridis")
plt.colorbar(label="composite score")
plt.title("Pairwise composite score (avg via centroid proxy)")
plt.savefig("calibration_matrix.png", dpi=100)
plt.show()

# CELL 6 — CLU-08 adversarial test
# Upload TWO unrelated clips at the SAME time + SAME place. Verify they DO NOT cluster.
# These can be: an indoor whiteboard shot + an outdoor parking lot shot at Caltech now.
adversarial = [
    ("../seed/adversarial/whiteboard.mp4", CALTECH_LAT, CALTECH_LNG, time.time()),
    ("../seed/adversarial/parking.mp4",    CALTECH_LAT, CALTECH_LNG, time.time()),
]
# ... upload both, sleep, refetch /debug/clusters, assert they ended up in DIFFERENT cluster_ids

# CELL 7 — threshold sweep (optional but valuable)
# Re-score all uploaded clips against all clusters under threshold values [0.40, 0.45, ..., 0.70].
# Plot: for each threshold, count of clusters and member_count distribution.
# Pick threshold that maximizes "biggest cluster member_count" while keeping adversarial clips separate.
```

**Notebook gotcha:** The `subprocess.run(["python", "-m", ...])` call inside Cell 3 means the notebook's working directory must be `<repo>/` (not `backend/notebooks/`). Either `os.chdir("../..")` first, or invoke seed via httpx directly.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Vector DB (Pinecone, Qdrant) for similarity search | Brute-force NumPy cosine over <100 in-memory vectors | Hackathon scale decision | Removes 1 service dep; faster than DB round-trip at this scale |
| Sequential aiosqlite connection pool | Per-operation connect/close | aiosqlite 0.20 default | Simpler code; WAL mode handles concurrency [VERIFIED: backend/db.py established pattern] |
| Three independent thresholds (cosine ≥ X AND gps_dist ≤ Y AND time ≤ Z) | Single composite score with one threshold | Locked in CLAUDE.md + CLU-02 | Fewer tunable params; one number to calibrate; debug overlay is one bar |
| `BackgroundTasks` for pipeline work | `asyncio.create_task` chained inside `run_pipeline` | FastAPI guidance evolved | True fire-and-forget; doesn't tie up worker thread [CITED: ARCHITECTURE.md Pattern 1] |
| haversine package | Inline `math.atan2` formula | This phase's research | Removes a runtime dep; identical accuracy at hyperlocal range |

**Deprecated/outdated:**
- Marengo 2.7 model (`Marengo-retrieval-2.7`) — sunset 2026-03-30, must use lowercase `marengo3.0` [VERIFIED: CLAUDE.md "Stack" + already in embed.py:60]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Marengo same-event cosine is in [0.7, 0.9] range, allowing 0.55 threshold to discriminate | Pitfall 1 + Architecture Composite Score | **MEDIUM** — if real cosine is in [0.4, 0.6], threshold needs lowering. Calibration cell prevents this from reaching demo. |
| A2 | <100 active clusters fits in memory comfortably; brute-force scan is sub-ms | Architecture | **LOW** — 100 × 512 × 4 bytes = 200 KB; trivially cheap |
| A3 | Float32 precision drift in running-mean centroid is negligible at <30 members per cluster | Pitfall 2 | **LOW** — tested empirically by NumPy users; we add float64 intermediate as belt-and-suspenders |
| A4 | Indoor Caltech demo will have GPS unavailable for live clips; staged clips have hardcoded lat/lng | Architectural Map + Pitfall 3 | **MEDIUM** — locked by CONTEXT D-06; mitigation is in code (collapse weight to 0). DEM-05 (`?demo_location=`) is Phase 5 backstop. |
| A5 | seed_demo.py uses `httpx` and adds it to dev deps — backend itself doesn't need httpx | Code Examples §"Seed script" | **LOW** — could swap to stdlib `urllib.request` if preferred. No production impact. |
| A6 | Calibration notebook running with `USE_MOCK_EMBEDDINGS=true` will FAIL CLU-07 because mock vectors are random and don't cluster | Calibration Notebook | **LOW** — documented; notebook header should say "set `USE_MOCK_EMBEDDINGS=false` for real calibration" |
| A7 | "median_ts" column name is a misnomer — we store running-mean ts, not literal median | Code Examples §"cluster_worker" | **LOW** — schema is named `median_ts` but our update is mean-based. Accept the misnomer; literal median would require keeping all member ts in memory. Document inline. |
| A8 | Two parallel `cluster_worker` invocations could race on CLUSTERS dict; needs `asyncio.Lock` | Pitfall 4 | **MEDIUM** — observable in seed script if `asyncio.gather` is used; current seed script serializes which avoids it, but live judge submissions could trigger it |
| A9 | `GET /debug/clusters` reading `db.get_embedding` per member is fine at <30 clips per cluster; no batching needed | Code Examples §"Debug endpoint" | **LOW** — one SELECT per member; <30 selects is trivial; can batch later if needed |

**Items needing user / planner confirmation:** A1 (calibration cell empirically validates), A4 (Phase 5 DEM-05 reinforces), A7 (rename or document — recommend documenting since schema is locked).

## Open Questions (RESOLVED)

1. **What's in the staged clips?**
   - What we know: 3-4 short MP4s of "one event from different angles" per CONTEXT D-01.
   - What's unclear: Specific event content. Need to record / source these clips before calibration can run.
   - Recommendation: Record 4 short clips (10-15s each) of any group activity (people walking past a fountain, protest reenactment, etc.) from 4 different angles within ~30m. Plus 2 adversarial clips of unrelated content (someone working at a laptop, an empty hallway) for CLU-08.

2. **Where does the seed script run during deploy?**
   - What we know: Phase 5 (DEM-07) wires `make demo` to seed automatically.
   - What's unclear: Phase 3 boundary — does seed run on Railway every deploy, or only locally for calibration?
   - Recommendation: Phase 3 ships seed as a manual `python -m backend.seed.seed_demo` invocation. Phase 5 owns automation.

3. **Should `cluster_worker` set `clips.embedding_status` = "clustered" as a separate state?**
   - What we know: Schema has `embedding_status` (pending|done|failed) but no `cluster_status`.
   - What's unclear: Whether downstream needs to distinguish "embedded but not clustered" vs "clustered".
   - Recommendation: `clips.cluster_id IS NOT NULL` is sufficient state. Don't add a new column.

4. **Should `cluster_worker` re-cluster historical clips on threshold change?**
   - What we know: CLU-05 says threshold is "exposed as env var for hot-swap".
   - What's unclear: Hot-swap meaning. Does changing `CLUSTER_THRESHOLD=0.50` and restarting trigger re-clustering of past clips?
   - Recommendation: NO. Threshold change applies only to new arrivals. Past assignments are immutable until next process boot's lifespan rebuild reads them as-is. Document this. The calibration notebook handles re-clustering by re-uploading clips.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | All backend code | ✓ | Python 3.13.11 | — |
| numpy | cluster math | ✓ | 2.4.2 | — |
| aiosqlite | DB helpers | ✓ (in requirements.txt 0.20.0) | — | — |
| FastAPI | `/debug/clusters` route | ✓ (0.115.6) | — | — |
| jupyter | calibration notebook | ✓ | 7.16.6 | — |
| nbformat | notebook structure | ✓ | 5.10.4 | — |
| matplotlib | notebook plots (CLU-07 visualization) | ✗ | — | Skip plots; use plain `print()` of pairwise matrix; calibration still passes |
| haversine package | gps distance | ✗ | — | **Inline formula (no dep needed)** — recommended |
| httpx | seed_demo.py uploads | ? | check via `python3 -c "import httpx"` | Use `urllib.request` (stdlib) |
| Twelve Labs API key | real Marengo embeddings during calibration | ✓ in `.env` (per Phase 2) | — | `USE_MOCK_EMBEDDINGS=true` for plumbing test, but CLU-07 calibration requires real embeds |

**Missing dependencies with no fallback:** None — every Phase 3 requirement has either a dep or a fallback.

**Missing dependencies with fallback:**
- `matplotlib`: install ad-hoc for notebook (`pip install matplotlib`); calibration cell can degrade to text output.
- `haversine`: do not install; use inline formula.
- `httpx`: prefer adding to dev deps; or fall back to stdlib `urllib.request`.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Anonymity is load-bearing (CLAUDE.md "Hard Constraints") — no auth, no sessions tied to identity |
| V3 Session Management | partial | Anonymous session UUID in localStorage (CAP/ING phase, already done). Phase 3 must NOT log session_id alongside cluster_id in any external sink. |
| V4 Access Control | yes | `GET /debug/clusters` is currently unauthenticated. Treat as **internal-only**. Either gate behind `OFFLINE_DEMO=true` env or by `if not config.DEBUG: raise 404`. |
| V5 Input Validation | yes | Seed script accepts file paths and base URL; bound them. cluster_worker reads `lat`, `lng`, `ts` from DB which were already validated at ingest in app.py:78. |
| V6 Cryptography | no | No keys, no signing in this phase |

### Known Threat Patterns for FastAPI + SQLite + clustering

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via cluster_id | Tampering | Parameterized queries (`?` placeholders) — already the project pattern in db.py |
| Debug endpoint exfiltrates clip metadata (lat/lng + ts) which could de-anonymize | Information Disclosure | Gate `/debug/clusters` behind a header check or `OFFLINE_DEMO` env; do NOT expose to public Vercel domain. CORS is already configured (`backend/app.py:46`); restrict `/debug/*` to localhost or to a `X-Debug-Token` header before public deploy. |
| Race on CLUSTERS dict corrupts member_count | Tampering (concurrency) | `asyncio.Lock` around mutations (Pitfall 4) |
| Adversarial pair forces wrong cluster fusion | Tampering (semantic) | CLU-08 adversarial test cell + threshold tuning |
| Clip path traversal via seed script (`../../etc/passwd`) | Tampering | Seed script reads from a fixed glob `seed/demo/clip-*.mp4` — no user-supplied paths |
| Memory exhaustion via unbounded cluster growth | DoS | <100 clusters expected at hackathon scale; future mitigation is sliding-window eviction (out of scope) |
| Centroid extraction via `/debug/clusters` reveals embedding structure (model fingerprinting) | Information Disclosure | Acceptable for hackathon; production would gate or strip the centroid BLOB. |

**Phase 3 security action items:**
1. Add a `DEBUG_ENDPOINTS_ENABLED` env check (default `True` for dev, can flip `False` for Railway prod) gating `/debug/clusters`.
2. Document in route docstring: "Internal calibration endpoint; do not expose to authenticated public traffic."

## Sources

### Primary (HIGH confidence)
- `backend/db.py` (full schema + helpers established pattern) — local file
- `backend/pipeline/embed.py` (mirror this structure for cluster.py) — local file
- `backend/config.py` (CLUSTER_THRESHOLD already wired) — local file
- `backend/app.py` (lifespan extension point, CORS, route patterns) — local file
- `.planning/research/ARCHITECTURE.md` §Pattern 2 "Online Single-Pass Clustering" + §Clustering Algorithm
- `.planning/research/PITFALLS.md` §Pitfall 2 "Clustering thresholds untuned" + §Pitfall 11 "Adversarial cluster collision"
- `CLAUDE.md` "Stack" + "Architecture" + "Hard Constraints" + "Top Pitfalls"
- `.planning/REQUIREMENTS.md` CLU-01 through CLU-10, RTM-04
- `.planning/phases/03-clustering-debug-overlay/03-CONTEXT.md` (locked decisions D-01 through D-10)

### Secondary (MEDIUM confidence)
- [haversine PyPI 2.9.0](https://pypi.org/project/haversine/) — confirmed library exists and API; recommendation is to NOT use it
- [NumPy mean precision docs](https://numpy.org/doc/stable/reference/generated/numpy.mean.html) — float32 precision discussion supports float64 intermediate in running-mean
- [NumPy 2.0 migration guide](https://numpy.org/devdocs/numpy_2_0_migration_guide.html) — scalar precision change verified

### Tertiary (LOW confidence)
- None — all critical claims sourced from local files or official docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package already in `requirements.txt`; no new prod deps
- Architecture (composite score, running-mean centroid, in-memory dict + lifespan rebuild): HIGH — fully constrained by CONTEXT.md + ARCHITECTURE.md
- Pitfalls (race condition, float32 drift, GPS fallback semantics, debug endpoint exposure): HIGH — all derivable from project patterns + standard asyncio idioms
- Threshold validation against real Marengo similarity scores on staged dataset: MEDIUM — requires the calibration notebook to actually run before locking
- Seed clip content + adversarial pair recording: LOW — depends on team filming actual clips

**Research date:** 2026-04-25
**Valid until:** 2026-05-25 (30 days; stack is stable, no fast-moving deps in this phase)
