---
phase: 03-clustering-debug-overlay
reviewed: 2026-04-25T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - backend/pipeline/cluster.py
  - backend/db.py
  - backend/pipeline/run.py
  - backend/app.py
  - backend/seed/seed_demo.py
  - backend/tests/test_cluster.py
  - backend/tests/test_db_clusters.py
  - backend/tests/test_pipeline_integration.py
  - backend/tests/test_debug_clusters.py
  - backend/notebooks/calibration.ipynb
  - backend/requirements.txt
  - backend/requirements-dev.txt
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-04-25
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Phase 3 adds composite-score clustering (0.55×cosine + 0.30×GPS + 0.15×time), a `/debug/clusters` calibration endpoint, a seed script, and a calibration notebook. The core math and lock discipline are solid. The `asyncio.Lock` correctly serializes the score-and-mutate-and-persist critical section, and the "persist first, then mutate cache" ordering is sound.

Four warnings require attention before demo day. The most actionable one (WR-01) is a TOCTOU race in the SSE broadcast payload: `member_count` is read from the live `CLUSTERS` dict after the lock is released, so the value in the broadcast event can lag or lead reality when two clips pipeline concurrently. The `/debug/clusters` endpoint silently leaks per-clip GPS coordinates with no access control — significant given the "anonymity is load-bearing" mandate. Two production-correctness issues round out the warnings: test deps bleeding into `requirements.txt` and a GPS lat/lng asymmetry in the centroid running mean.

No critical (security/crash) issues were found.

---

## Warnings

### WR-01: Broadcast `member_count` is read after lock release — TOCTOU race

**File:** `backend/pipeline/cluster.py:195`

**Issue:** After `async with _LOCK` exits (line 186 for the new-cluster path, line 169 for join), the broadcast payload is built at line 195. Line 197 reads `CLUSTERS[cluster_id].member_count` without holding the lock. A concurrent `cluster_worker` that acquires the lock in between can increment `member_count` before this read completes, so the SSE event for clip A could report the count that reflects clip B's join. For the live demo, the SSE-driven frontend will show incorrect cluster size labels.

**Fix:** Capture `member_count` inside the lock, before the `async with` block exits:

```python
# Inside the lock, at the end of both branches, capture the value to broadcast:
# JOIN branch (around line 169):
CLUSTERS[cluster.id] = updated
cluster_id = cluster.id
broadcast_member_count = updated.member_count   # <-- capture while locked

# CREATE branch (around line 185):
CLUSTERS[cluster_id] = new_cluster
is_new = True
broadcast_member_count = 1                      # <-- always 1 for a new cluster

# Then outside the lock, use broadcast_member_count instead of CLUSTERS[cluster_id].member_count:
payload: dict = {
    ...
    "member_count": broadcast_member_count,
    ...
}
```

---

### WR-02: `/debug/clusters` leaks per-clip GPS coordinates with no access control

**File:** `backend/app.py:103`

**Issue:** The endpoint at line 103 returns every cluster member's exact `lat`, `lng`, and `ts` (lines 128–138). There is no authentication, IP restriction, or even a secret query parameter. Since `include_in_schema=False` only hides the route from the OpenAPI docs — not from the network — any client that guesses the path gets full GPS history of every upload. CLAUDE.md states "Anonymity is load-bearing." GPS coordinates are personally identifying for users who filmed at a specific location.

The endpoint is essential for demo calibration (CLU-09), but it should not be live and unguarded during the judges' demo session, where attendees may probe the API.

**Fix:** Gate the endpoint behind a configurable secret token or an `OFFLINE_DEMO`-aware flag. Simplest approach:

```python
import secrets as _secrets

DEBUG_TOKEN = os.environ.get("DEBUG_TOKEN", "")

@app.get("/debug/clusters", include_in_schema=False)
async def debug_clusters(token: str = "") -> dict:
    if DEBUG_TOKEN and not _secrets.compare_digest(token, DEBUG_TOKEN):
        raise HTTPException(status_code=404)   # 404 not 401 — don't advertise existence
    ...
```

Set `DEBUG_TOKEN=<random>` in `.env`. The calibration notebook and seed script pass `?token=...` when calling the endpoint.

---

### WR-03: GPS centroid running mean updates lat and lng independently — asymmetric update possible

**File:** `backend/pipeline/cluster.py:146-153`

**Issue:** The centroid GPS running mean checks lat and lng in separate `if` blocks:

```python
if lat is not None and cluster.centroid_lat is not None:
    new_lat = _running_mean(cluster.centroid_lat, lat, new_count)
else:
    new_lat = cluster.centroid_lat

if lng is not None and cluster.centroid_lng is not None:
    new_lng = _running_mean(cluster.centroid_lng, lng, new_count)
else:
    new_lng = cluster.centroid_lng
```

If a clip somehow has `lat` but `lng is None` (or vice versa), the centroid's latitude advances while its longitude stays frozen, drifting the centroid to a location that never existed. GPS fixes are always both-or-neither in practice, but the code does not enforce this invariant — a malformed multipart upload could send `lat` with a missing `lng` field (FastAPI defaults `lng` to 422 if declared as `Form(...)`, but if the validation is bypassed or the field type changes, this path becomes live).

**Fix:** Treat lat/lng as an atomic pair:

```python
if (lat is not None and lng is not None
        and cluster.centroid_lat is not None and cluster.centroid_lng is not None):
    new_lat = _running_mean(cluster.centroid_lat, lat, new_count)
    new_lng = _running_mean(cluster.centroid_lng, lng, new_count)
else:
    new_lat = cluster.centroid_lat
    new_lng = cluster.centroid_lng
```

This mirrors the same guard already used in `score_against` (line 102).

---

### WR-04: `pytest` and `pytest-asyncio` listed as production dependencies

**File:** `backend/requirements.txt:10-11`

**Issue:** Lines 10–11 of `requirements.txt` list `pytest>=8.0` and `pytest-asyncio>=0.23` as production dependencies. These are test-only packages; including them in the production install on Railway adds ~20 MB of unnecessary packages, and more importantly, any `pytest` import-time side effects (e.g., plugin registration via `pytest11` entry points) can interfere with the production runtime.

**Fix:** Remove both lines from `requirements.txt`. They are already correctly listed in `requirements-dev.txt` (lines 7–8). The dev install (`pip install -r requirements-dev.txt`) already pulls them in.

---

## Info

### IN-01: `asyncio.get_event_loop()` deprecated in favour of `get_running_loop()`

**File:** `backend/app.py:31`

**Issue:** `asyncio.get_event_loop()` is called inside an `async def` function. In Python 3.10+ this emits a `DeprecationWarning` when there is a running loop (which there always is inside an async function). The correct call in an async context is `asyncio.get_running_loop()`, which always succeeds and never creates a new loop.

**Fix:**
```python
loop = asyncio.get_running_loop()
_, latency_ms = await loop.run_in_executor(None, _sync_embed, pre_warm_path, "__prewarm__")
```

---

### IN-02: `seed_demo.py` upper-bounds clip count at 4 — will reject valid extension

**File:** `backend/seed/seed_demo.py:43`

**Issue:** The guard `if not (3 <= len(clips) <= 4)` exits with an error when more than 4 clip files are present. If a teammate adds a 5th demo clip for a richer CLU-07 proof, the seed script refuses to run without any explanation that the upper bound is the cause.

**Fix:** Remove the upper bound or raise it. The lower bound (at least 3 clips for CLU-07) is the meaningful constraint:

```python
if len(clips) < 3:
    print(f"ERROR: expected at least 3 demo clips matching clip-*.mp4 in {CLIP_DIR}, got {len(clips)}.",
          file=sys.stderr)
    sys.exit(1)
```

---

### IN-03: `tenacity` is unpinned in `requirements.txt`

**File:** `backend/requirements.txt:9`

**Issue:** `tenacity` has no version pin. All other direct dependencies are pinned to exact versions. An unpinned dep means `pip install` on a fresh Railway deployment can silently pull a semver-breaking release and break retry logic in `embed_worker` (where tenacity is likely used).

**Fix:**
```
tenacity==9.0.0
```
(Pin to whatever version is currently installed: `pip show tenacity | grep Version`.)

---

### IN-04: Calibration notebook `time.sleep(60)` may be too short for 4 clips with real Marengo

**File:** `backend/notebooks/calibration.ipynb` (cell `2d8cc4a9`)

**Issue:** The notebook comment says "4 clips * ~25s/embed worst case = ~100s" but then sleeps for 60 seconds. If Marengo is cold or the API is under load during the hackathon demo, some clips may not have finished embedding when CLU-07 is asserted. The assertion will fail with "CLU-07 FAILED: no clusters formed at all" and the notebook will not immediately reveal why.

**Fix:** Either increase the sleep to 120s to match the stated worst case, or poll `/debug/clusters` until `member_count` stabilises:

```python
# Poll until all clips are clustered (max 120s)
for _ in range(24):
    time.sleep(5)
    dbg = httpx.get(f"{BASE}/debug/clusters", timeout=10.0).json()
    total_members = sum(c["member_count"] for c in dbg["clusters"])
    if total_members >= len(clips):
        break
```

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
