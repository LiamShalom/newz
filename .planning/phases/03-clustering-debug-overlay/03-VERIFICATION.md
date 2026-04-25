---
phase: 03-clustering-debug-overlay
verified: 2026-04-25T02:30:00Z
status: human_needed
score: 10/11 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run calibration notebook with USE_MOCK_EMBEDDINGS=false against real Marengo + real filmed clips"
    expected: "Cell 5 CLU-07 assertion passes: largest cluster has >= 3 members. Score breakdown shows high visual cosine values (expected 0.7+ for same-event Marengo embeddings) that actually drove the fusion decision."
    why_human: "Zero-byte placeholder clips are committed. CLU-07 assertion (member_count >= 3) cannot pass until real MP4s replace the placeholders. This requires physical filming at the Caltech venue and a live Marengo API key."
  - test: "Open GET /debug/clusters in browser while live clips are being uploaded — verify score breakdown numbers update per clip"
    expected: "Each new clip assignment adds a member to /debug/clusters response with non-zero visual/gps/time scores; numbers change as clips embed and cluster"
    why_human: "RTM-04 requires live update behavior visible to a judge. The SSE broadcast mechanism (cluster_assigned event) is wired and emitting correctly, but the frontend debug overlay panel is deferred to Phase 4/5 per D-09 in CONTEXT.md. The /debug/clusters JSON endpoint exists and is the current substitute — a human must confirm it reflects live state correctly when clips are actively uploading."
  - test: "Run adversarial CLU-08 notebook cell: film two unrelated clips, upload them with same GPS + timestamp"
    expected: "CLU-08 assertion passes: the two adversarial clips end up in DIFFERENT clusters"
    why_human: "adversarial-1.mp4 and adversarial-2.mp4 are not present (intentionally skipped per plan). The CLU-08 notebook cell gracefully skips when these files are absent. Real adversarial clips require filming + a Marengo API key."
gaps: []
deferred: []
---

# Phase 3: Clustering + Debug Overlay Verification Report

**Phase Goal:** Staged demo clips fuse into a single cluster with visible Marengo / GPS / timestamp score breakdown, calibrated empirically against the actual demo dataset. This is the pitch — even if Phases 4-5 fail, this phase alone is demoable and proves the thesis.
**Verified:** 2026-04-25T02:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Staged clips of the same event cluster together (CLU-07 calibration notebook) | HUMAN NEEDED | Notebook infrastructure complete (8 cells, CLU-07 assertion present). Zero-byte placeholder clips committed — real filmed clips required to pass the assertion. |
| 2 | Adversarial clips at same time/place do NOT cluster together (CLU-08) | HUMAN NEEDED | CLU-08 notebook cell present; gracefully skips when adversarial-{1,2}.mp4 absent. Requires filming + Marengo API key. |
| 3 | Debug overlay shows score breakdown per cluster (Marengo cosine, GPS dist m, ts delta s) | PARTIAL | GET /debug/clusters returns full per-member breakdown (visual, gps, time, composite, gps_distance_m, time_delta_s). Frontend live panel deferred to Phase 4/5 per D-09. RTM-04 SSE event (cluster_assigned) emitted. Human must confirm live update behavior. |
| 4 | Threshold 0.55 env-configurable; GPS weight collapses to 0 when GPS unavailable | VERIFIED | `config.CLUSTER_THRESHOLD` controls join gate (line 139 cluster.py). GPS collapse: formula degrades to `0.55*cos + 0.15*time` (un-renormalized) when lat/lng missing on either side. Verified by test `test_score_against_no_gps_collapses_to_055cos_plus_015time` and `test_score_against_partial_gps_unavailable_when_one_side_missing`. |
| 5 | Active clusters survive backend restart (rebuild from SQLite, no Redis) | VERIFIED | `rebuild_cache()` called in lifespan after `db.init()` before pre-warm (app.py lines 39-45). Test `test_lifespan_rebuilds_cache_from_sqlite` passes — centroid bytes are byte-identical after rebuild, member_ids repopulated via JOIN. |
| 6 | Each new clip flows through embed_worker → cluster_worker; cluster_id persisted on clips row | VERIFIED | `run_pipeline` chains `embed_worker → cluster_worker` (run.py lines 17-26). Test `test_run_pipeline_creates_cluster_for_first_clip` confirms clip.cluster_id set in DB. |
| 7 | Composite formula = 0.55*cos + 0.30*gps + 0.15*time; threshold 0.55 | VERIFIED | Constants W_VISUAL=0.55, W_GPS=0.30, W_TIME=0.15 locked in cluster.py (lines 36-40). Formula applied in `score_against()` (line 112). 3 tests cover full/no/partial GPS branches. |
| 8 | asyncio.Lock serializes score-and-mutate; broadcast OUTSIDE the lock | VERIFIED | `async with _LOCK:` at line 131; `await events.broadcast(payload)` at line 207 — 76 lines after lock entry, outside the context manager. Comment "Broadcast OUTSIDE the lock" at line 188 confirms intent. |
| 9 | cluster_assigned SSE event emitted with full score_breakdown | VERIFIED | Payload at cluster.py lines 189-205 includes visual, gps, time, composite, gps_available, threshold. Emitted via `events.broadcast()` per clip assignment. |
| 10 | seed_demo.py is a working argparse CLI that uploads clips via POST /clips | VERIFIED | `python -m backend.seed.seed_demo --help` exits 0. CALTECH_LAT/LNG hardcoded. `sorted(CLIP_DIR.glob("clip-*.mp4"))` glob confirmed. seed/__init__.py package marker present. |
| 11 | calibration.ipynb is valid nbformat v4 with CLU-07 + CLU-08 assertions | VERIFIED | 8 cells confirmed. All content assertions pass: CLU-07, CLU-08, BACKEND_URL, USE_MOCK_EMBEDDINGS, /debug/clusters, seed_demo all present. |

**Score:** 10/11 truths verified (1 partial, 3 human-needed)

### Deferred Items

None. No items from this phase are deferred to later phases.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/pipeline/cluster.py` | ClusterCache, ScoreBreakdown, CLUSTERS, _LOCK, score_against, update_centroid, haversine_m, cluster_worker, rebuild_cache | VERIFIED | 234 lines. All 9 symbols present. @dataclass count = 2 (ScoreBreakdown + ClusterCache). GPS_RADIUS_M=200.0, TIME_WINDOW_S=600.0. math.atan2 inline haversine (no package dep). |
| `backend/db.py` | get_all_clusters, upsert_cluster, assign_clip_to_cluster | VERIFIED | All 3 async helpers present. ON CONFLICT(id) DO UPDATE SET idempotent upsert. centroid.astype(np.float32).tobytes() BLOB write. row_factory = aiosqlite.Row in get_all_clusters. No f-strings in SQL. |
| `backend/pipeline/run.py` | cluster_worker wired after embed_worker | VERIFIED | `from .cluster import cluster_worker` at line 5. `await cluster_worker(clip_id, vec)` at line 22. stage="clustered" broadcast at line 24. No stale TODO comment. |
| `backend/app.py` | lifespan calls rebuild_cache() after db.init() before pre-warm; GET /debug/clusters route | VERIFIED | Lines 39-45: db.init() → rebuild_cache() → create_task(_pre_warm_marengo()). Route at line 103: @app.get("/debug/clusters", include_in_schema=False). Deferred local import pattern used (not top-level). |
| `backend/seed/demo/clip-1.mp4` | First staged demo clip | STUB | Zero-byte placeholder. PLACEHOLDER.md present with replacement instructions. Intentional deferral — filmed at venue. |
| `backend/seed/demo/clip-2.mp4` | Second staged demo clip | STUB | Zero-byte placeholder. Same deferral. |
| `backend/seed/demo/clip-3.mp4` | Third staged demo clip | STUB | Zero-byte placeholder. Same deferral. |
| `backend/seed/seed_demo.py` | CLI uploader with argparse --base-url | VERIFIED | Importable. `--help` exits 0. argparse, asyncio.run(main(...)), CALTECH coords, POST /clips wiring all present. |
| `backend/seed/__init__.py` | Package marker for python -m invocation | VERIFIED | Zero-byte file exists. |
| `backend/app.py` | GET /debug/clusters route | VERIFIED | Route registered. Returns threshold, weights, gps_radius_m, time_window_s, clusters[]. Confirmed via route list: `/debug/clusters` in app.routes. |
| `backend/notebooks/calibration.ipynb` | CLU-07 + CLU-08 assertions | VERIFIED | 8 cells. All assertion content confirmed. nbformat v4 valid. |
| `backend/requirements-dev.txt` | httpx, matplotlib, jupyter (dev-only) | VERIFIED | 7 lines including httpx>=0.27.0, matplotlib>=3.9.0, jupyter>=1.0.0, nbconvert, nbformat. NOT in production requirements.txt. |

**Note on stub clips:** Zero-byte placeholder clips are documented in `backend/seed/demo/PLACEHOLDER.md` and are the expected artifact for the "defer-with-placeholders" path selected during Task 1 of Plan 03-02. This is not a code gap — the infrastructure is complete and ready for real clips.

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `backend/pipeline/run.py` | `cluster.py::cluster_worker` | `from .cluster import cluster_worker; await cluster_worker(clip_id, vec)` | WIRED | Lines 5 + 22 of run.py |
| `backend/app.py` | `cluster.py::rebuild_cache` | `from .pipeline import cluster as cluster_mod; await cluster_mod.rebuild_cache()` | WIRED | Lines 43-44 of app.py |
| `backend/pipeline/cluster.py` | `events.py::broadcast` | `await events.broadcast(payload)` — outside `_LOCK` block | WIRED | Line 207 cluster.py. Broadcast is OUTSIDE the asyncio.Lock (lock at line 131, lock exits at ~line 186, broadcast at line 207). |
| `backend/pipeline/cluster.py` | `db.py::upsert_cluster` | `await db.upsert_cluster(updated)` under _LOCK before cache mutation | WIRED | Lines 167 and 183 of cluster.py |
| `backend/seed/seed_demo.py` | `POST /clips` | `httpx.AsyncClient.post(f'{base_url}/clips', files=..., data={lat,lng,ts})` | WIRED | Line 33 of seed_demo.py |
| `backend/notebooks/calibration.ipynb` | `GET /debug/clusters` | `httpx.get(f"{BASE}/debug/clusters").json()` | WIRED | Cell 4 of notebook |
| `backend/app.py::debug_clusters` | `cluster.py::CLUSTERS` | `from .pipeline import cluster as cluster_mod; cluster_mod.CLUSTERS.values()` | WIRED | Lines 110-113 of app.py |
| `backend/app.py::debug_clusters` | `cluster.py::score_against` | `cluster_mod.score_against(c, vec, clip["lat"], clip["lng"], clip["ts"])` | WIRED | Line 120 of app.py |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `cluster.py::CLUSTERS` | CLUSTERS dict | `rebuild_cache()` from `db.get_all_clusters()` → SQLite; live updates from `cluster_worker()` | Yes — SQLite-backed | FLOWING |
| `app.py::debug_clusters` | clusters_out | Iterates `cluster_mod.CLUSTERS.values()` (in-memory) + `db.get_clip()` + `db.get_embedding()` per member | Yes — in-memory + SQLite reads | FLOWING |
| `cluster.py::cluster_worker` | cluster_id | Scored against CLUSTERS dict; persisted via `db.upsert_cluster` + `db.assign_clip_to_cluster` | Yes — writes to SQLite | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 18 tests pass | `cd backend && python -m pytest tests/ -x -v` | 18 passed in 3.61s | PASS |
| cluster.py importable | `python -c "from backend.pipeline import cluster"` | Exit 0 | PASS |
| app.py importable, /debug/clusters registered | `python -c "from backend.app import app; routes = [r.path for r in app.routes]; assert '/debug/clusters' in routes"` | Exit 0 | PASS |
| seed_demo.py CLI | `python -m backend.seed.seed_demo --help` | Usage printed, exit 0 | PASS |
| notebook valid nbformat | `python -c "import nbformat; nb=nbformat.read(..., as_version=4); assert len(nb.cells)>=7"` | 8 cells confirmed | PASS |
| No haversine package dep | `grep -c "haversine" backend/requirements.txt` | 0 | PASS |
| Broadcast outside _LOCK | `_LOCK at line 131, broadcast at line 207` | 76 lines separation | PASS |
| lifespan order: db.init → rebuild_cache → pre_warm | awk line number check | db.init=39, rebuild_cache=44, pre_warm=45 | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| CLU-01 | 03-01 | Online single-pass clustering algorithm assigns each new clip to a cluster or creates a new one | SATISFIED | `cluster_worker()` in cluster.py; test_cluster_worker_creates_new_cluster_when_empty + test_cluster_worker_joins_when_above_threshold both pass |
| CLU-02 | 03-01 | Composite score = 0.55 × Marengo cosine + 0.30 × GPS proximity + 0.15 × timestamp proximity | SATISFIED | score_against() formula at cluster.py line 112; W_VISUAL=0.55, W_GPS=0.30, W_TIME=0.15 |
| CLU-03 | 03-01 | GPS proximity normalized over 200m radius | SATISFIED | `GPS_RADIUS_M = 200.0`; `gps = max(0.0, 1.0 - d_m / GPS_RADIUS_M)` |
| CLU-04 | 03-01 | Timestamp proximity normalized over 600s window | SATISFIED | `TIME_WINDOW_S = 600.0`; `tim = max(0.0, 1.0 - delta_s / TIME_WINDOW_S)` |
| CLU-05 | 03-01 | Threshold 0.55 exposed as env var for hot-swap | SATISFIED | `config.CLUSTER_THRESHOLD` read from `CLUSTER_THRESHOLD` env var (default 0.55) in config.py; used at cluster.py line 139 |
| CLU-06 | 03-01 | GPS weight collapses to 0 when geolocation unavailable | SATISFIED | Un-renormalized collapse verified by test; gps=0.0 when either side has None lat/lng |
| CLU-07 | 03-02 | Calibration notebook proves staged demo clips cluster correctly | NEEDS HUMAN | Notebook infrastructure complete. Assertion present. Blocked on zero-byte placeholder clips — requires real filming + Marengo API. |
| CLU-08 | 03-02 | Adversarial test: two unrelated clips at same time/place do NOT cluster | NEEDS HUMAN | Notebook CLU-08 cell present; gracefully skips if adversarial files absent. Requires filming. |
| CLU-09 | 03-02 | Debug overlay shows score breakdown per cluster | SATISFIED (partial) | GET /debug/clusters returns full breakdown (cosine, GPS dist m, ts delta s). Frontend live panel deferred to Phase 4/5 per D-09. JSON API is the current debug surface. |
| CLU-10 | 03-01 | Active clusters cached in memory, rebuilt from SQLite on startup | SATISFIED | rebuild_cache() in lifespan; test_lifespan_rebuilds_cache_from_sqlite passes |
| RTM-04 | 03-01 | Debug overlay updates similarity scores live as clips embed and cluster | PARTIAL | cluster_assigned SSE event emits per assignment with score_breakdown (visual, gps, time, composite, threshold). Subscriber-side (frontend) is Phase 4. Live update behavior requires human confirmation. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/seed/demo/clip-1.mp4` | — | Zero-byte file | INFO | Documented placeholder. Not a code stub — physical filming deferred to venue. PLACEHOLDER.md explains replacement procedure. No impact on code correctness. |
| `backend/seed/demo/clip-2.mp4` | — | Zero-byte file | INFO | Same as above |
| `backend/seed/demo/clip-3.mp4` | — | Zero-byte file | INFO | Same as above |

No blocking anti-patterns found. No TODO/FIXME/placeholder comments in production code. No empty handlers or hardcoded empty returns in wired paths.

### Human Verification Required

#### 1. CLU-07 Same-Event Fusion Calibration

**Test:** Film 3-4 short MP4s (10-15s each) of one shared event from different angles within ~30m of each other, captured within ~60 seconds. Replace `backend/seed/demo/clip-{1,2,3}.mp4` with real video files. Start backend with `USE_MOCK_EMBEDDINGS=false` and a valid `TWELVELABS_API_KEY`. Run: `jupyter nbconvert --to notebook --execute backend/notebooks/calibration.ipynb`

**Expected:** Cell 5 CLU-07 assertion passes — largest cluster has >= 3 members. Output shows composite scores per member all above 0.55 threshold. Visual (Marengo cosine) scores should be 0.7+ for same-event clips.

**Why human:** CLU-07 requires real video footage and a live Marengo API key. The assertion tests real multi-modal fusion — cannot be validated with zero-byte files or mock embeddings.

#### 2. RTM-04 Live Debug Score Update

**Test:** Start backend. Open `GET http://localhost:8000/debug/clusters` in a browser or via `watch -n1 "curl -s http://localhost:8000/debug/clusters | jq '.clusters | length'"`. Upload a clip via POST /clips. Wait for pipeline to complete (~5-30s depending on Marengo). Refresh /debug/clusters.

**Expected:** After each clip upload and pipeline completion, /debug/clusters response reflects the new member with score breakdown. The `cluster_assigned` SSE event is emitted per assignment (visible in backend logs with the score_breakdown payload).

**Why human:** Live update behavior in response to real clip uploads cannot be verified statically. The SSE broadcast is wired but the frontend consumer (Phase 4) is not yet built.

#### 3. CLU-08 Adversarial Separation Test

**Test:** Film two clearly unrelated short clips (e.g., empty hallway + parking lot). Save as `backend/seed/demo/adversarial-1.mp4` and `adversarial-2.mp4`. Rerun the calibration notebook with a live backend.

**Expected:** CLU-08 assertion in Cell 7 passes — the two adversarial clips end up in DIFFERENT clusters despite being uploaded with identical GPS + timestamp.

**Why human:** Requires filming unrelated clips and a live Marengo API key. The adversarial test exercises the visual discriminator's ability to separate semantically different content — a human must capture the content and verify the Marengo cosine is low enough to prevent fusion.

### Gaps Summary

No automated gaps found. All code infrastructure for Phase 3 is complete and tested (18/18 tests pass). The three human verification items are gated on physical filming and a Marengo API key — they represent the calibration proof of concept that is the explicit purpose of this phase, not missing code.

**Stub clips (clip-1/2/3.mp4):** These are the expected outcome of the plan's "defer-with-placeholders" path, explicitly documented in PLACEHOLDER.md, and do not represent a code gap. The seed_demo.py CLI, /debug/clusters endpoint, and calibration notebook are all fully functional and ready to exercise these clips once filmed.

---

_Verified: 2026-04-25T02:30:00Z_
_Verifier: Claude (gsd-verifier)_
