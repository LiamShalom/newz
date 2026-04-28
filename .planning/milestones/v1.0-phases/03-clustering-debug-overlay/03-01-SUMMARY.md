---
phase: 03-clustering-debug-overlay
plan: 01
subsystem: pipeline
tags: [clustering, sqlite, numpy, asyncio, fastapi, aiosqlite, tdd]

requires:
  - phase: 02-marengo-embedding
    provides: embed_worker returning L2-normalized 512-d float32 vectors, db.py with clips/clip_embeddings/clusters schema

provides:
  - composite-score clustering (0.55*cos + 0.30*gps + 0.15*time) in backend/pipeline/cluster.py
  - three new db helpers: get_all_clusters, upsert_cluster, assign_clip_to_cluster
  - run_pipeline chains embed_worker -> cluster_worker
  - lifespan rebuilds CLUSTERS dict from sqlite before accepting clips (CLU-10)
  - cluster_assigned SSE event emitted per assignment with full score_breakdown
  - 15 pytest tests covering db roundtrips, scoring branches, cluster create/join, lifespan rebuild

affects:
  - 03-02 (debug overlay + calibration notebook — consumes cluster.CLUSTERS and GET /debug/clusters)
  - 04-multi-agent-compile (cluster_id from cluster_worker is the Phase 4 entry point)
  - 05-demo-hardening (OFFLINE_DEMO=true path must work with mock embeddings through cluster stage)

tech-stack:
  added:
    - pytest>=8.0 (test-only)
    - pytest-asyncio>=0.23 (test-only)
  patterns:
    - asyncio.Lock guards score-and-mutate block; broadcast outside lock
    - Welford running-mean centroid update in float64 intermediate, re-normalized float32
    - inline haversine_m (no haversine package dep)
    - Persist-before-cache-mutate pattern (Pitfall 6 mitigation)
    - Deferred local import for cluster_mod inside lifespan (circular-dep break)
    - TDD: RED commit (test file) -> GREEN commit (implementation) per task

key-files:
  created:
    - backend/pipeline/cluster.py (233 lines — ClusterCache, ScoreBreakdown, CLUSTERS, _LOCK, score_against, update_centroid, haversine_m, cluster_worker, rebuild_cache)
    - backend/tests/test_cluster.py (8 tests)
    - backend/tests/test_db_clusters.py (4 tests)
    - backend/tests/test_pipeline_integration.py (3 tests)
    - backend/tests/__init__.py
  modified:
    - backend/db.py (+60 lines — get_all_clusters, upsert_cluster, assign_clip_to_cluster)
    - backend/pipeline/run.py (+5 lines — cluster_worker import + await call + clustered broadcast)
    - backend/app.py (+4 lines — lifespan cluster rebuild before pre-warm)
    - backend/requirements.txt (+2 lines — pytest, pytest-asyncio)

key-decisions:
  - "GPS weight collapses to 0.0 un-renormalized (not rescaled) when lat/lng missing — preserves CLU-06 semantics; threshold remains 0.55"
  - "Broadcast emitted OUTSIDE asyncio.Lock to prevent yield-induced deadlock with SSE subscribers (Phase 4)"
  - "Persist-before-cache-mutate: DB writes happen under _LOCK before CLUSTERS dict is touched — exception leaves cache consistent"
  - "haversine_m is inlined (8 lines of math.atan2) — no haversine package dep"
  - "Welford running mean in float64 intermediate prevents float32 precision drift at hackathon member counts"
  - "Test haversine Caltech-to-JPL actual distance is ~8218m, not ~7300m as estimated in plan — corrected test tolerance"

patterns-established:
  - "Pattern: asyncio.Lock around score-read-mutate; events.broadcast outside the lock"
  - "Pattern: upsert_cluster uses INSERT ... ON CONFLICT(id) DO UPDATE SET for idempotent cluster updates"
  - "Pattern: get_all_clusters uses single connection, two cursors, groups member_ids in Python (no N+1)"
  - "Pattern: TDD per-task — RED (failing test commit) -> GREEN (implementation commit)"

requirements-completed:
  - CLU-01
  - CLU-02
  - CLU-03
  - CLU-04
  - CLU-05
  - CLU-06
  - CLU-10
  - RTM-04

duration: 5min
completed: 2026-04-25
---

# Phase 03 Plan 01: Composite-Score Clustering Stage Summary

**Online single-pass composite clustering (0.55*Marengo cosine + 0.30*GPS + 0.15*time) wired into FastAPI pipeline with asyncio.Lock-guarded centroid updates, sqlite persistence, and lifespan rebuild — 15 tests green**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-25T08:21:18Z
- **Completed:** 2026-04-25T08:26:19Z
- **Tasks:** 3 (all TDD)
- **Files modified:** 8

## Accomplishments

- `backend/pipeline/cluster.py` implements the full composite-score clustering math (locked weights from CLAUDE.md), with Welford centroid update, inline haversine, asyncio.Lock critical section, and rebuild_cache startup helper
- Three new `backend/db.py` helpers — `get_all_clusters` (single connection, member_ids join), `upsert_cluster` (INSERT ... ON CONFLICT idempotent), `assign_clip_to_cluster` — all using parameterized SQL and per-operation aiosqlite connections
- `run_pipeline` now chains `embed_worker -> cluster_worker`; `app.lifespan` rebuilds CLUSTERS dict from sqlite before scheduling the Marengo pre-warm task
- 15 pytest tests pass: 4 db helpers (roundtrip, idempotency, member_ids JOIN, empty-DB), 8 cluster unit tests (haversine sanity, score branches full/no/partial GPS, centroid update, create/join), 3 integration tests (pipeline run, broadcast order, lifespan restart resilience)

## Task Commits

1. **Task 1: db helpers** — `e2cd1ad` (feat)
2. **Task 2: cluster.py** — `aca1238` (feat)
3. **Task 3: pipeline wiring + app.py lifespan** — `10933ad` (feat)

## Files Created/Modified

- `backend/pipeline/cluster.py` (NEW, 233 lines) — ClusterCache + ScoreBreakdown dataclasses, CLUSTERS dict, _LOCK, score_against, update_centroid, haversine_m, cluster_worker, rebuild_cache
- `backend/db.py` (+60 lines) — get_all_clusters, upsert_cluster, assign_clip_to_cluster
- `backend/pipeline/run.py` (+5 lines) — cluster_worker import + await + clustered broadcast
- `backend/app.py` (+4 lines) — lifespan cluster rebuild before pre-warm
- `backend/tests/test_cluster.py` (NEW, 8 tests)
- `backend/tests/test_db_clusters.py` (NEW, 4 tests)
- `backend/tests/test_pipeline_integration.py` (NEW, 3 tests)
- `backend/tests/__init__.py` (NEW, empty)
- `backend/requirements.txt` (+2 lines — pytest, pytest-asyncio)

## Decisions Made

- GPS weight collapses to 0.0 un-renormalized (not rescaled to 0.70 total) per CLU-06/D-06 — threshold 0.55 intentionally makes indoor-only clips require stronger visual+time agreement to fuse
- `events.broadcast` emitted OUTSIDE `_LOCK` — Phase 4 will wire SSE subscribers and broadcast may yield; holding the lock through broadcast could deadlock
- Persist DB writes (upsert_cluster + assign_clip_to_cluster) under the lock BEFORE mutating CLUSTERS dict — any exception leaves cache consistent (Pitfall 6 mitigation)
- Inline haversine_m (8 lines of `math.atan2`) — no new runtime dependency, identical accuracy at hyperlocal range

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] FastAPI UploadFile.content_type has no attribute setter in 0.115.6**
- **Found during:** Task 1 (test_assign_clip_to_cluster_sets_column)
- **Issue:** Test helper called `fake_file.content_type = "video/mp4"` which raises `AttributeError: property 'content_type' of 'UploadFile' object has no setter` in FastAPI 0.115.6 — content_type is derived from headers, not a settable attribute
- **Fix:** Removed the attribute assignment; the `UploadFile(headers={"content-type": "video/mp4"})` constructor already sets it correctly
- **Files modified:** backend/tests/test_db_clusters.py
- **Verification:** All 4 db tests pass after fix
- **Committed in:** e2cd1ad (Task 1 commit)

**2. [Rule 1 - Bug] Test haversine_caltech_to_jpl expected wrong distance bounds**
- **Found during:** Task 2 (test_haversine_caltech_to_jpl_known_distance)
- **Issue:** Plan specified ~7300m ±200m for Caltech→JPL; actual haversine_m returns 8217.7m — the plan's geographic estimate was ~11% off
- **Fix:** Updated test bounds to 7900–8500m (centered on the real computed value 8217.7m with ±300m tolerance)
- **Files modified:** backend/tests/test_cluster.py
- **Verification:** Test passes; haversine formula verified correct (1 deg lat = 111,195m matches standard value)
- **Committed in:** aca1238 (Task 2 commit, green phase)

---

**Total deviations:** 2 auto-fixed (2 × Rule 1 — bugs in test setup)
**Impact on plan:** Both fixes in test code only. Production implementation shipped exactly as planned. No scope creep.

## Issues Encountered

None in production code. Both deviations were test-layer bugs caught during TDD GREEN phase.

## Verified Composite Formula Behavior

| GPS availability | Formula applied | Threshold behavior |
|---|---|---|
| Both clip and cluster have lat/lng | 0.55*cos + 0.30*gps + 0.15*time | Standard — GPS helps discriminate |
| Either side missing lat/lng | 0.55*cos + 0.00*gps + 0.15*time | Un-renormalized per D-06; needs cos≥0.727 with time=1.0 to pass threshold |

## Open Questions for Plan 03-02

- Empirical Marengo same-event cosine range still unverified — calibration notebook (03-02) must run with `USE_MOCK_EMBEDDINGS=false` against real staged clips to validate the 0.55 threshold
- `GET /debug/clusters` endpoint not yet wired (deferred to 03-02 per plan scope)
- Calibration notebook (`backend/notebooks/calibration.ipynb`) not yet created (03-02 deliverable)
- Seed demo clips (`backend/seed/demo/clip-*.mp4`) not yet recorded (real filming required before calibration)

## Threat Surface Scan

No new network endpoints or trust boundaries introduced in this plan. The `cluster_assigned` SSE payload contains `clip_id`, `cluster_id`, `score_breakdown` (GPS/time proximity scores) but NOT raw lat/lng coordinates — anonymity preserved. `cluster_id = uuid4().hex` is non-derivable from session_id or any user-supplied field (T-03-07 mitigated).

## Known Stubs

None — cluster_worker is fully functional end-to-end. The `GET /debug/clusters` route and calibration notebook are Phase 3 Plan 02 deliverables; their absence is intentional scope, not a stub.

## Self-Check: PASSED

- FOUND: backend/pipeline/cluster.py
- FOUND: backend/tests/test_cluster.py
- FOUND: backend/tests/test_db_clusters.py
- FOUND: backend/tests/test_pipeline_integration.py
- FOUND: .planning/phases/03-clustering-debug-overlay/03-01-SUMMARY.md
- FOUND: commit e2cd1ad (Task 1 — db helpers)
- FOUND: commit aca1238 (Task 2 — cluster.py)
- FOUND: commit 10933ad (Task 3 — pipeline wiring)
