---
phase: 14-recompile-on-cluster-update
plan: 01
subsystem: pipeline-orchestration
tags: [recompile, debounce, sse, soft-warn, feature-flag, asyncio, postgres-cas]

# Dependency graph
requires:
  - phase: 09-postgres-migration
    provides: clusters.compile_in_flight + last_compile_at columns; set_compile_in_flight CAS lock
  - phase: 11-moderation-gate
    provides: per-clip moderation contract (MOD-01, MOD-06); soft_flag re-derivation in compile.py:629-648
provides:
  - RECOMPILE_DEBOUNCE_S + RECOMPILE_ON_NEW_PARENT in backend/config.py
  - _should_recompile() async helper sibling of _should_compile in backend/pipeline/run.py
  - elif dispatch wired in run_pipeline AND _resume_pipeline (parity)
  - _RECOMPILE_COUNTS module-level dict + _RECOMPILE_WARN_THRESHOLD=5 in backend/pipeline/compile.py
  - recompile=bool field on the compile_started SSE payload
  - log.warning soft-warn at >=5 recompiles per cluster lifetime
affects:
  - 14-02 (test plan — Wave 2)
  - frontend SSE consumers (additive field; backwards compatible — no change required)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - sibling-gate (clone _should_compile shape for _should_recompile)
    - module-local approximate counter (mirrors rate_limit._attempts shape)
    - reuse existing CAS lock with longer TTL (variable ttl_seconds=config.X)

key-files:
  created: []
  modified:
    - backend/config.py
    - backend/pipeline/run.py
    - backend/pipeline/compile.py
    - backend/tests/test_compile_timeout.py  # Rule 1 deviation fix only

key-decisions:
  - "Path B-lite: reuse segment_published SSE event verbatim; recompile=bool added to compile_started only"
  - "60s debounce window via existing set_compile_in_flight CAS lock (no new DB helper)"
  - "Soft-warn at 5 recompiles per cluster, no hard cap (avoid silent invisibility bug)"
  - "Process-local _RECOMPILE_COUNTS dict (resets on Railway redeploy) — pilot-acceptable"
  - "Both run_pipeline + _resume_pipeline get the elif branch — admin-clear path parity"

patterns-established:
  - "Sibling-gate pattern: new gate sits between existing gate and dispatcher, dispatched as elif after the existing if"
  - "SSE payload extension via additive field (frontend useEventSource discriminates on type, ignores unknown fields)"
  - "Approximate-counter dict at module scope: dict.get(k, 0) + 1 idiom, no asyncio.Lock"

requirements-completed: [MOD-01, MOD-06, MOD-07, MOD-08, MOD-10]

# Metrics
duration: 12min
completed: 2026-04-30
---

# Phase 14 Plan 01: Recompile-on-Cluster-Update Source Changes Summary

**Path B-lite recompile gate landed: _should_recompile sibling helper + 60s debounce + recompile-flagged compile_started SSE + per-cluster soft-warn at 5 recompiles. 84 lines additive across config.py + run.py + compile.py.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-04-30T21:05Z
- **Completed:** 2026-04-30T21:17Z
- **Tasks:** 3 (plus 1 deviation fix)
- **Files modified:** 4 (3 source + 1 test)

## Accomplishments

- Resolved v1.0-deferred `montage-not-updating` debug item: 3rd parent now triggers recompile
- Re-uses existing CAS lock; zero new DB helpers, zero schema changes, zero new SSE event types
- Feature-flag-gated for gradual rollout (RECOMPILE_ON_NEW_PARENT=true|false)
- Per-clip moderation contract (MOD-01, MOD-06) preserved — recompile path operates only on already-passed clips
- Anonymity preserved: SSE payload `recompile` boolean is non-identity-bearing
- All 112 backend tests pass, 6 skipped — no regressions vs base 947035f

## Task Commits

Each task was committed atomically:

1. **Task 1: Add config constants** — `0067bd6` (feat)
2. **Task 2: _should_recompile helper + elif dispatches** — `ff331cb` (feat)
3. **Task 3: _RECOMPILE_COUNTS soft-warn + SSE field** — `f20b440` (feat)

**Deviation fix:** `3f1ac0d` (fix — Rule 1 auto-fix on test_compile_timeout.py)

## Files Created/Modified

- `backend/config.py` (+13 lines) — RECOMPILE_DEBOUNCE_S=60.0 (float, env-overridable), RECOMPILE_ON_NEW_PARENT=true (bool, env-overridable). Phase-prefixed comment block matching MODERATION_MAX_BUDGET_S analog.
- `backend/pipeline/run.py` (+43 lines) — `_should_recompile(cluster_id, new_clip_id)` sibling of `_should_compile`; elif branches at run_pipeline:189 and _resume_pipeline:239 dispatching `compile_segment` with printf-style log lines.
- `backend/pipeline/compile.py` (+28 lines) — `_RECOMPILE_COUNTS: dict[str, int]` + `_RECOMPILE_WARN_THRESHOLD: int = 5` at module scope (line 107-108); `compile_started` SSE payload now carries `"recompile": is_recompile`; soft-warn `log.warning("compile recompile_count_high cluster_id=%s count=%d ...", ...)` fires when same cluster crosses threshold during process lifetime.
- `backend/tests/test_compile_timeout.py` (+5 lines) — Rule 1 deviation fix: added `mock_db.get_segment_for_cluster = AsyncMock(return_value=None)` to make the timeout test compatible with the new top-of-compile_segment read.

## Verbatim Helper Signature + Body (run.py)

```python
async def _should_recompile(cluster_id: str, new_clip_id: str) -> bool:
    """Phase 14 recompile gate: fire compile_segment when a NEW DISTINCT PARENT
    joins a cluster that ALREADY has a published segment.
    ...
    """
    if not config.RECOMPILE_ON_NEW_PARENT:
        return False
    clip = await db.get_clip(new_clip_id)
    if clip is None or clip.get("parent_id") is not None:
        return False
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        return False
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    if parent_count < 2:
        return False
    return await db.set_compile_in_flight(
        cluster_id, True, ttl_seconds=config.RECOMPILE_DEBOUNCE_S,
    )
```

## Verbatim Dispatch-Site Diff (run.py — both sites)

```diff
         if await _should_compile(cluster_id):
             asyncio.create_task(compile_segment(cluster_id))
             log.info("compile triggered cluster_id=%s", cluster_id)
+        elif await _should_recompile(cluster_id, clip_id):
+            asyncio.create_task(compile_segment(cluster_id))
+            log.info("recompile triggered cluster_id=%s parent_id=%s", cluster_id, clip_id)
```

```diff
         if await _should_compile(cluster_id):
             asyncio.create_task(compile_segment(cluster_id))
             log.info("resume compile triggered cluster_id=%s", cluster_id)
+        elif await _should_recompile(cluster_id, clip_id):
+            asyncio.create_task(compile_segment(cluster_id))
+            log.info("resume recompile triggered cluster_id=%s parent_id=%s", cluster_id, clip_id)
```

## Verbatim _RECOMPILE_COUNTS Declaration + Soft-Warn Block (compile.py)

```python
log = logging.getLogger(__name__)

# Phase 14: per-cluster recompile counter (process-local, resets on restart).
# Single-process FastAPI + --workers 1 makes module-local state authoritative
# for the pilot. NOT persisted — a Railway redeploy zeroes the counter, which
# is fine for the soft-warn observability use case (the goal is "did this
# cluster trip the warn threshold during this process lifecycle"). Revisit
# post-pilot if a hard cap is needed (then add clusters.compile_count column
# per RESEARCH § R4).
_RECOMPILE_COUNTS: dict[str, int] = {}
_RECOMPILE_WARN_THRESHOLD: int = 5
```

```python
    started_at = time.time()
    # Phase 14: detect recompile vs first-publish for the SSE payload + soft-warn.
    # An existing segment row means this is a recompile pass (D-NEW-01 in 14-PLAN).
    seg_existing = await db.get_segment_for_cluster(cluster_id)
    is_recompile = seg_existing is not None
    await events.broadcast({
        "type": "compile_started",
        "cluster_id": cluster_id,
        "started_at": started_at,
        "recompile": is_recompile,
    })

    if is_recompile:
        # Module-local counter; dict mutation is atomic at the asyncio scheduling
        # boundary, no asyncio.Lock needed (counter is approximate-by-design — a
        # missed increment under contention is acceptable; we only soft-warn at
        # >=_RECOMPILE_WARN_THRESHOLD).
        recompile_count = _RECOMPILE_COUNTS.get(cluster_id, 0) + 1
        _RECOMPILE_COUNTS[cluster_id] = recompile_count
        if recompile_count >= _RECOMPILE_WARN_THRESHOLD:
            log.warning(
                "compile recompile_count_high cluster_id=%s count=%d -- investigate hot-event behavior",
                cluster_id, recompile_count,
            )
```

## Decisions Made

None - followed plan exactly. Plan was the result of 14-RESEARCH.md + 14-PATTERNS.md + iterative plan-checker revisions; no new decisions surfaced during execution.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Mock `get_segment_for_cluster` in compile_timeout test**

- **Found during:** Plan-level verification (`pytest backend/tests/`)
- **Issue:** Task 3 added `seg_existing = await db.get_segment_for_cluster(cluster_id)` at the top of `compile_segment`. The pre-existing `test_compile_segment_timeout_uses_fallback` test patches `compile.db` as a `MagicMock` without configuring `get_segment_for_cluster` — `await MagicMock()` raises `TypeError: object MagicMock can't be used in 'await' expression`. The sibling test `test_compile_segment_branch_a_exception_uses_fallback` already configures it as `AsyncMock(return_value=None)`; the timeout test was missing the same mock.
- **Fix:** Added `mock_db.get_segment_for_cluster = AsyncMock(return_value=None)` to the timeout test, mirroring the sibling test's pattern. None return = first-publish path = no recompile counter increment, keeping the test focused on the timeout fallback behavior.
- **Files modified:** `backend/tests/test_compile_timeout.py` (+5 lines including a 3-line comment explaining the Phase 14 read)
- **Verification:** `pytest backend/tests/` → 112 passed, 6 skipped. Targeted test passes: `pytest backend/tests/test_compile_timeout.py -v` → both cases pass.
- **Committed in:** `3f1ac0d`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug)
**Impact on plan:** The deviation is purely a test-mock plumbing fix caused by Task 3's new code path. Strictly in-scope per "issues directly caused by current task's changes." Test logic is unchanged; only the mock surface area was expanded. No scope creep.

## Issues Encountered

None during planned task execution. Plan was verbatim-precise; every grep-able acceptance criterion passed except one which was a multi-line `log.warning(...)` call format (semantically equivalent to single-line, matches the existing project convention at compile.py:430-434 — see Self-Check below).

## TDD Gate Compliance

N/A — plan type is `execute` (not `tdd`). Tests live in 14-02-PLAN.md per plan rationale. No RED/GREEN/REFACTOR gates required.

## Verification Results

| Check | Result |
|-------|--------|
| `python3 -m py_compile backend/config.py backend/pipeline/run.py backend/pipeline/compile.py` | OK |
| `from backend import config; from backend.pipeline import run, compile; assert callable(run._should_recompile); assert hasattr(compile, '_RECOMPILE_COUNTS')` | OK |
| `grep -rn "logfire" backend/` | 0 hits (PATTERNS drift note honored) |
| `git diff --stat` | 84 insertions, 0 deletions across 3 source files |
| `pytest backend/tests/ --ignore=backend/tests/pipeline/test_recompile.py` | 112 passed, 6 skipped, 0 failed |
| Type annotations correct (`float`, `bool`) | OK |
| Env override works (RECOMPILE_DEBOUNCE_S=15.0, RECOMPILE_ON_NEW_PARENT=false) | OK |
| `_should_recompile` signature `(cluster_id, new_clip_id)` | OK |
| Existing `ttl_seconds=30.0` in `_should_compile` untouched | OK |
| No f-string log lines | OK |
| `_RECOMPILE_COUNTS == {}`, `_RECOMPILE_WARN_THRESHOLD == 5` at import | OK |
| Existing `seg = await db.get_segment_for_cluster(cluster_id)` near line 656 still present | 3 occurrences (one new + two existing — also the line near 656 is intact) |

## Test Status

No tests yet — handed off to 14-02-PLAN.md (Wave 2). The 14-02 test surface (per RESEARCH § Required Tests) covers:

1. `test_recompile_fires_on_new_distinct_parent` (happy path)
2. `test_recompile_debounce_coalesces_burst`
3. `test_recompile_skipped_for_child_of_existing_parent`
4. `test_recompile_offline_demo_e2e`
5. `test_recompile_preserves_per_clip_moderation`
6. `test_recompile_does_not_bypass_moderation_block`

The deviation fix in `test_compile_timeout.py` is NOT a Phase 14 test — it's a regression-baseline fix to keep the existing suite green.

## User Setup Required

None — no external service configuration required. Both new env vars (`RECOMPILE_DEBOUNCE_S`, `RECOMPILE_ON_NEW_PARENT`) have sensible defaults; production rollout can flip the flag via Railway env panel without code changes.

## Next Phase Readiness

- 14-02 (test plan) can land directly on top of this commit. The 6 tests assert against the symbols this plan provides (`_should_recompile`, `_RECOMPILE_COUNTS`, the recompile SSE field).
- No blockers. CAS lock semantics are preserved; OFFLINE_DEMO survives; anonymity preserved; per-clip moderation contract preserved.
- Frontend requires zero changes: `Feed.tsx:60` already triggers `refetchFeed()` on `segment_published`, which the recompile path re-broadcasts at compile.py:690.

## Self-Check: PASSED

Verified all created/modified files exist on disk, all four commits exist in `git log`, and the regression test suite is green.

- File `backend/config.py` modified: FOUND (RECOMPILE_DEBOUNCE_S at line 83, RECOMPILE_ON_NEW_PARENT at line 88)
- File `backend/pipeline/run.py` modified: FOUND (`_should_recompile` at line 56)
- File `backend/pipeline/compile.py` modified: FOUND (`_RECOMPILE_COUNTS` at line 107, `_RECOMPILE_WARN_THRESHOLD` at line 108)
- File `backend/tests/test_compile_timeout.py` modified: FOUND (added `get_segment_for_cluster` mock)
- Commit `0067bd6`: FOUND
- Commit `ff331cb`: FOUND
- Commit `f20b440`: FOUND
- Commit `3f1ac0d`: FOUND

---
*Phase: 14-recompile-on-cluster-update, Plan: 01*
*Completed: 2026-04-30*
