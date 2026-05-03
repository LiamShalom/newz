# Phase 14 — Recompile Montage on New Parent in Existing Cluster — Research

**Researched:** 2026-04-30
**Domain:** Pipeline orchestration / SSE event design / Alembic migration / async asyncio coalescing
**Confidence:** HIGH (all findings grounded in current codebase reads — no training-data assumptions on framework behavior)

## Summary

The bug is a pure orchestration gap, not a data-model gap. The existing `segments` table already upserts on `cluster_id` conflict, the `clusters.last_compile_at` and `compile_in_flight` columns already exist, the SSE fan-out already broadcasts a typed event, and the frontend already does a simple full-feed refetch on `segment_published`. The gap is exactly: when a new distinct parent joins an already-compiled cluster, `_should_compile()` returns False because `last_compile_at` is inside the 30s TTL, and after the TTL expires nothing re-evaluates compile-readiness for that cluster. There is no second trigger.

The cleanest fix is **Path B-lite (hybrid)**: lift the `last_compile_at` lockout when the join is a *new distinct parent* on a cluster that already has a segment, and reuse the existing `segment_published` SSE event with no schema/event-type change. This collapses the frontend cost to zero (the existing handler at `frontend/src/views/Feed.tsx:60` already triggers a full feed refetch on `segment_published`, so a re-emitted event auto-replaces the card data). Path B's `montage_dirty` column and `segment_updated` event are not load-bearing for the pilot — the `segments` row UPDATE inside `compile.py:664` is already idempotent and `fetchSegments()` always reads the latest row.

**Primary recommendation:** Path B-lite — add a `_should_recompile()` sibling gate in `run.py`, fire it whenever `cluster_worker` reports `is_new_cluster=False` AND a segment row already exists for that cluster AND the new clip's `parent_id IS NULL` (i.e., is a parent, not a child). Use a new TTL constant (`RECOMPILE_DEBOUNCE_S=60.0`) to coalesce burst arrivals. Reuse the existing `segment_published` SSE event. Add no new columns. Add no new event types. The whole feature is ~40 lines of backend code + 3 tests.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Owner:** Liam (backend). Frontend touchpoint only if SSE event-type change is needed; the recommendation in this research is to **reuse `segment_published` with no event-type change**, eliminating the frontend touchpoint entirely.
- **Branch:** `liam/montage-recompile-on-cluster-update` (already cut).
- **300s LLM compile budget unchanged.**
- **No new infra** — single-process asyncio only; no Redis, no Celery.
- **Anonymity preserved** — no identity-bearing fields, no per-user state.
- **OFFLINE_DEMO must work end-to-end** for the recompile path.
- **Phase 11 hooks are locked-in** — branch is descended from `liam/phase-11-moderation-gate`; `moderate_clip()`, `_resume_pipeline()`, `aggregate_verdict()` are all available.

### Claude's Discretion

- Path A vs Path B vs Hybrid (research recommends Path B-lite — see Decision Matrix).
- Debounce window length (research recommends 60s).
- Moderation re-flow: re-run on stitch vs. trust per-clip decisions (research recommends trust per-clip; rationale below).
- Recompile cap policy (research recommends per-cluster soft cap of 5 with structured warning, no hard stop).

### Deferred Ideas (OUT OF SCOPE)

- Multi-cluster reassignment (a clip moving between clusters).
- Retroactive recompile of historically stale montages (covered by `/admin/reset`).
- Changes to clustering thresholds or composite scoring.
- Marengo embedding pipeline changes.
- Frontend redesign — only SSE consumer touched if needed.

## Phase Requirements

No Phase 14 row exists in `REQUIREMENTS.md` — the v1.1 requirements table caps at REPORT-10 / OBS-09 / DEMO-03 (Phase 12/13). Phase 14 was hand-scaffolded after the requirements lock. The applicable upstream requirement IDs that *touch* what this phase changes:

| ID | Description | Phase 14 relevance |
|----|-------------|--------------------|
| MOD-01 | Every uploaded clip runs through moderation gate before cluster/compile. | Recompile path MUST NOT bypass — clips already passed individually before cluster join, so no new gate run needed. |
| MOD-06 | Every moderation decision recorded in `moderation_decisions`. | Audit table is per-clip, not per-segment — no new rows required for recompile. |
| MOD-07 | Hate/violence soft-flag is decoupled from corroboration. | Recompile invokes the same `compile.py:629-648` `soft_flag` derivation, so the flag re-derives correctly when membership changes. |
| MOD-08 | Feed UI shows interstitial on `soft_flag=true` segments. | Re-emitted segment row carries fresh `soft_flag` value; frontend interstitial follows automatically. |
| MOD-10 | OFFLINE_DEMO bypasses external moderation APIs. | Recompile path under OFFLINE_DEMO already uses passthrough (mod gate fires per-clip, not per-recompile). |
| (no DB-/BLOB-/REPORT-/OBS- impact) | — | Recompile reuses existing tables, blob paths, observability spans. |

**No new requirement IDs are introduced by Phase 14.** This is a defect-fix phase against the existing CMP-* implicit contract ("compile fires when cluster has ≥2 distinct parents").

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Detect "new distinct parent on existing-segment cluster" | API / Backend | — | Cluster state lives in Postgres + in-memory `CLUSTERS`; SSE consumers don't see joins. |
| Coalesce burst arrivals (debounce window) | API / Backend | — | `set_compile_in_flight` CAS lock already runs in Postgres. |
| Re-stitch ffmpeg output | API / Backend | — | `_sync_stitch` already writes to `.part-*` then `os.replace` (test_stitch_recompile.py confirms atomic publish). |
| Idempotent segment row update | Database / Storage | — | `insert_segment` already does `ON CONFLICT(cluster_id) DO UPDATE` (compile.py:664-673). |
| SSE re-broadcast | API / Backend | Browser / Client | Backend re-broadcasts `segment_published`; existing frontend handler at `Feed.tsx:60` triggers full refetch. |
| Re-render updated montage card | Browser / Client | — | `fetchSegments()` returns the latest row; `setSegments` reconciles via React diff. |

## Decision Matrix

> Recommendation: **Path B-lite** (hybrid). Rationale below the table.

| Dimension | Path A (TTL hack) | Path B (full) | **Path B-lite (recommended)** |
|-----------|-------------------|---------------|-------------------------------|
| **Code surface** | ~10 lines: clear `last_compile_at` when new parent joins existing-segment cluster. | ~150 lines: Alembic migration adding `montage_dirty` (or `version int`) column; new `segment_updated` SSE event; frontend handler for new event; new DB helpers; bump TS `ServerEvent` union. | **~40 lines:** new `_should_recompile()` sibling gate in `run.py`; new `set_recompile_in_flight()` CAS variant in `db_postgres.py` (or reuse `set_compile_in_flight` with `RECOMPILE_DEBOUNCE_S` arg); branch in `run.py` after `cluster_worker` returns. **No migration. No new SSE event. No frontend change.** |
| **Correctness under repeated joins** | Brittle — relies on TTL gymnastics. If two parents join within the same 30s window after a compile, the second one re-fires another compile (correct), but if 5 parents trickle in over 5 minutes, you get 5 sequential compiles (likely correct, but no debounce). | Robust — explicit `dirty` flag means recompile is owed exactly when state diverges. | **Robust** — `set_compile_in_flight` is already a CAS lock; sized debounce window (60s) coalesces bursts; when the window closes, the gate re-evaluates `count_distinct_parents_in_cluster` which is the single source of truth. Same correctness floor as Path B. |
| **Frontend integration cost** | Zero — existing `segment_published` handler refetches feed (`Feed.tsx:60`). | Non-zero — new `segment_updated` event type, new branch in `Feed.tsx:60`, possibly new badge UI ("new angle added"), TS union update in `types.ts:113-127`. | **Zero** — same handler path as Path A. Frontend already calls `fetchSegments()` on `segment_published` and reconciles by segment id. |
| **Moderation re-flow story** | Compatible — `compile.py` already re-derives `soft_flag` from per-member `moderation_decisions` (lines 629-648). Per-clip moderation gate already ran for each parent before cluster join. | Compatible (same story). | **Compatible** — Phase 11 `moderate_clip()` runs at clip ingest, before cluster_worker (`run.py:90`). By the time a parent joins an existing cluster, it has already passed the gate. The `soft_flag` derivation re-runs on every `compile.py` invocation, so the re-emitted segment row carries up-to-date moderation aggregates. |
| **OFFLINE_DEMO survival** | Survives — no external dependencies in the trigger logic. | Survives — same. | **Survives** — recompile path uses identical compile machinery; OFFLINE_DEMO short-circuits already exist in `moderate_clip` (`moderate.py:199-211`) and don't interact with the recompile gate. |
| **SQLite parity** | N/A. **SQLite is dead.** Confirmed: `backend/db_sqlite.py` does not exist on disk; `backend/db.py` re-exports `db_postgres` unconditionally; `aiosqlite` was dropped from requirements per STATE.md PR #11; CONTEXT.md "SQLite parity" caveat is vestigial. | N/A. | **N/A.** No constraint. |
| **Observability** | Logfire span tree gets a second `compile` span on the same cluster — easy to read but no semantic distinction. | New span attribute `recompile=true` would help. | **Add `recompile=true` attribute** to the existing Logfire `compile` span in `compile.py:551` and emit `log.info("recompile triggered cluster_id=%s reason=new_parent", ...)` in `run.py`. ~3 lines, no new tracing infra. |

### Why Path B-lite over Path B

The retrospective principle "Native model capabilities > clever workarounds" applies in reverse here. Path B treats `montage_dirty` as a new state machine the system needs to manage; Path B-lite recognizes that the database **already** carries the truth — `last_compile_at`, `count_distinct_parents_in_cluster`, and `get_segment_for_cluster` together answer "does this cluster need a recompile?" without inventing a new flag. Adding a column to express derived state is exactly the kind of accidental complexity v1.0 retrospective warns against ("Calibration is anchored to specific inputs" — adding columns invalidates analysis tooling).

The only justification for full Path B would be if the frontend needed to *visually distinguish* a re-emitted segment from a first-emitted one (e.g., a "new angle added" toast). CONTEXT.md does not call this out as a UX requirement, and the v1.1 reliability bias ("does it work when I try it") favors zero frontend touch.

### Path A reject rationale

Path A's "clear `last_compile_at`" trick works but encodes the recompile policy as a side-effect of the compile lock — making it harder to reason about ("why did this cluster compile twice?"). Path B-lite costs 30 more lines and gives explicit, named gate logic. Cheap upgrade.

## Debounce Strategy

**Recommendation:** new constant `RECOMPILE_DEBOUNCE_S = 60.0` in `backend/config.py`. Reuse the existing `set_compile_in_flight` CAS pattern with this longer TTL when called from the recompile path; the original 30s TTL stays for first-publish.

**Why 60s, not 30s:** 30s is tuned for first-compile collision protection (two parents arriving in same `_should_compile` race). The recompile case is different — we genuinely want to *wait* for additional parents that might be uploading concurrently before spending 300s of LLM budget. 60s is the same order as the typical upload-to-embed latency window, so a 4-parent burst from a single event coalesces into one recompile. Citing CONTEXT.md open question 2: this is the "fixed 60s window" answer.

**Code site for the change:**

```python
# backend/pipeline/run.py — after Phase 11 moderation gate, after cluster_worker returns

# Existing gate (unchanged):
if await _should_compile(cluster_id):
    asyncio.create_task(compile_segment(cluster_id))

# NEW gate (Path B-lite):
elif await _should_recompile(cluster_id, parent_clip_id):
    asyncio.create_task(compile_segment(cluster_id))  # same coroutine; idempotent at compile.py:664
    log.info("recompile triggered cluster_id=%s parent_id=%s", cluster_id, parent_clip_id)
```

```python
# new helper, also in backend/pipeline/run.py

async def _should_recompile(cluster_id: str, new_clip_id: str) -> bool:
    """Recompile gate: fire when a NEW DISTINCT PARENT joins a cluster that ALREADY
    has a published segment, debounced by RECOMPILE_DEBOUNCE_S window.

    Negative cases (intentionally do nothing):
      - new_clip is a child of an existing parent — no new angle, just slicing metadata
      - cluster has no segment yet — first compile path handles it via _should_compile
      - debounce window still warm — burst coalesces; next join inside the window re-checks
    """
    clip = await db.get_clip(new_clip_id)
    if clip is None or clip.get("parent_id") is not None:
        return False  # child of an existing parent — no recompile
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        return False  # no segment yet — _should_compile owns first publish
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    if parent_count < 2:
        return False  # impossible if seg exists, but defensive
    return await db.set_compile_in_flight(
        cluster_id, True, ttl_seconds=config.RECOMPILE_DEBOUNCE_S,
    )
```

**Coalescing logic:** `set_compile_in_flight`'s CAS UPDATE clause is `WHERE compile_in_flight = 0 OR last_compile_at < $now - $ttl`. Calling with `ttl_seconds=60.0` means a second parent arriving 30s after the first will see `last_compile_at` inside the 60s window and the CAS returns False → no second compile fires. Once `compile_segment` finishes (`set_compile_in_flight(cluster_id, False)` at `compile.py:688`), the next parent join can immediately try again. Result: at most one recompile per 60s window, with the most-recent membership. This is the correct semantic for a hot event drawing parents.

## Moderation Re-flow Hook

**Recommendation:** **Trust per-clip moderation; do NOT re-run moderation on recompile.**

Phase 11 moderation gate (`backend/pipeline/moderate.py:190-214`) runs **before** `cluster_worker` (`run.py:89`). Every clip in any cluster has already produced a `moderation_decisions` row with `decision in ('passed', 'blocked', 'unknown')`. Blocked clips never reach `cluster_worker` (`run.py:92-102`, `return` after broadcast). Unknown clips are hidden and gated behind admin clear (`run.py:104-114`); on clear, `_resume_pipeline` re-enters at `cluster_worker` with a fresh `decision='passed'` row.

The recompile path is a re-stitch of clips that have **already individually** passed the gate. There is no new content being introduced — the bytes were classified at ingest. Re-running moderation on the stitched output would:

1. Cost a Gemini Flash-Lite call per recompile (`MODERATION_MAX_BUDGET_S` budget impact).
2. Submit *concatenated* video to a classifier trained on per-clip semantics — false-positive risk.
3. Bypass the per-clip audit trail mandated by **MOD-06** (audit table is keyed on `clip_id`, not `segment_id`).
4. Violate **MOD-04** classifier-only contract (CSAM detection happens once per clip, with a `reported_csam` row written; re-running on a stitched output is not in the locked taxonomy).

**The soft-flag re-derivation already runs** on every recompile via `compile.py:629-648`:

```python
# compile.py:629-648 (already in main, not new)
soft_flag = False
try:
    members = await db.fetch_cluster_clips(cluster_id)
    member_ids = [m["id"] for m in members]
    decisions = await db.get_moderation_decisions_for_clips(member_ids)
    for d in decisions:
        ...
        for cat in ("hate", "violence"):
            cat_signal = raw.get(cat) or {}
            if isinstance(cat_signal, dict) and cat_signal.get("verdict") in ("flag", "block"):
                soft_flag = True
                break
        ...
```

This is the moderation re-flow hook. When a new parent joins, it's already in `fetch_cluster_clips(cluster_id)`, so its hate/violence signals (if any) automatically propagate into the re-derived `segments.soft_flag`. **No code change needed for moderation re-flow.** Verify with the test specified below.

**Reference for `_resume_pipeline` re-entry:** `backend/pipeline/run.py:160-207`. This is the existing entry point if a clip's moderation decision is later changed by an admin — Phase 14 does NOT need to wire to this; the recompile-on-new-parent path is upstream of any admin clear.

## Recompile Cap

**Recommendation:** **No hard cap. Add a soft warning at 5 recompiles per cluster.**

Rationale:

1. **Pathological "hot event keeps drawing parents" is a Logfire / metrics question, not a correctness question.** Phase 8 (shipped) already exposes `STAGE_DURATION.labels(stage="compile")` and per-cluster span tracing. A cluster getting 10 recompiles in an hour will surface as a cluster_id with 10 spans — directly visible in Logfire / Prometheus.
2. **A hard cap silently breaks user expectation.** If a cluster reaches the cap and the 6th parent joins, that parent is invisible — exactly the bug we're fixing.
3. **The 60s debounce window is the natural cap.** Worst-case at steady-state: one recompile per minute = 60/hour. At 300s LLM budget per recompile, that's a 5x compute overrun even for a sustained hot event — manageable for pilot scale.
4. **Soft-warning code:**

```python
# in compile.py, near top of compile_segment (after line 551)
seg_existing = await db.get_segment_for_cluster(cluster_id)
recompile_count = 0
if seg_existing is not None:
    # Recompile counter: cheap, derived from segment row's updated_at deltas if you want it
    # Or just track in-memory per cluster_id via a module-level dict
    recompile_count = _RECOMPILE_COUNTS.get(cluster_id, 0) + 1
    _RECOMPILE_COUNTS[cluster_id] = recompile_count
    if recompile_count >= 5:
        log.warning(
            "compile recompile_count_high cluster_id=%s count=%d — investigate hot-event behavior",
            cluster_id, recompile_count,
        )
```

The `_RECOMPILE_COUNTS` dict is process-local and resets on backend restart — that's fine. Surfacing the warning to Logfire / Sentry breadcrumb is sufficient observability for the pilot.

**Hard-cap option (rejected):** if a stop is needed in the future (post-pilot), the right gate is a per-cluster `compile_count` integer column on `clusters` checked against a `MAX_COMPILES_PER_CLUSTER` env var. Defer.

## Frontend SSE Consumer

**Recommendation:** **No change.**

Current handler (`frontend/src/views/Feed.tsx:59-65`):

```typescript
useEventSource((ev: ServerEvent) => {
  if (ev.type === "segment_published" || ev.type === "cluster_assigned") {
    void refetchFeed();
  } else if (ev.type === "comment_added") {
    dispatchCommentAdded(ev.segment_id, ev.comment);
  }
});
```

`refetchFeed()` calls `fetchSegments()` which returns `Segment[]` keyed by `segment.id`. When the recompile re-emits `segment_published` for an existing `cluster_id`, the `segments` table row is `UPDATE`d (not `INSERT`ed) inside `compile.py:664-673`, so the segment id is unchanged. The next `fetchSegments()` call returns a `Segment` with the same `id` but updated `ordered_clip_ids`, `source_count`, `caption`, `video_url`, `soft_flag`. React's `setSegments(next)` triggers a diff; `FeedShell` re-renders with the updated card.

**iOS Safari verification:** No new code paths exposed to the browser; existing EventSource auto-reconnect (RTM-02) covers any flakiness. iPhone smoke check is "upload a 3rd parent video to a cluster that has a published montage and confirm the feed card reflects the new angle within 60-90s of the upload completing." Add to UAT.

**If a UX upgrade is wanted later** (e.g., "new angle added" badge), the lowest-cost path is to add `montage_version: number` to `Segment` in `types.ts` and bump it server-side on recompile. The frontend then compares incoming version to local cache and animates if higher. Defer to post-pilot.

## SQLite Parity Status

**Status: DEAD. No constraint on Phase 14.**

Evidence:

1. `ls /Users/liamshalom/Hacktech/backend/db_sqlite.py` → "No such file or directory."
2. `backend/db.py` reads in full:
   ```python
   """Single backend — Neon Postgres via asyncpg."""
   from .db_postgres import *
   ```
3. `git log --oneline -- backend/db_sqlite.py` returns 4 commits, none after PR #11 (commit `85e3d39`, "Feature/UI polish comments share").
4. `grep "db_sqlite\|aiosqlite" backend/**/*.py` (excluding `.venv` and `__pycache__`) returns only **historical comments** in migrations and `db_postgres.py:10-13` ("History note: until 2026-04-29 a sibling db_sqlite.py existed…").
5. STATE.md line 90 confirms: "Retire SQLite (db_sqlite.py) — DONE 2026-04-29 (PR #11)."
6. `aiosqlite` survives only inside `.venv/lib/python3.11/site-packages/` (transitive install, not imported by app code).

CONTEXT.md's open question 6 ("SQLite parity dead?") and the constraint "Backend-mode parity: Must work identically in SQLite and Postgres modes" are **vestigial**. The plan should explicitly drop the SQLite-parity constraint and update the plan's "Constraints" section accordingly.

## Validation Architecture

> Note: `.planning/config.json` has `workflow.nyquist_validation: false`, so Nyquist sampling is not required. Tests below are the standard `pytest` integration suite. Test framework is **pytest 9.0.3** (per `__pycache__` filename `*-pytest-9.0.3.pyc`).

### Required Tests

| Test name | File | Type | What it asserts |
|-----------|------|------|-----------------|
| `test_recompile_fires_on_new_distinct_parent` | `backend/tests/pipeline/test_recompile.py` (new) | Integration | 2 parents → `compile_segment` invoked once → 3rd parent joins same cluster_id → `compile_segment` invoked twice total → `get_segment_for_cluster` returns row with `source_count=3` and `len(ordered_clip_ids) ≥ 3 distinct parent_ids`. |
| `test_recompile_debounce_coalesces_burst` | `backend/tests/pipeline/test_recompile.py` (new) | Integration | After 1st compile, 3 parents arrive within `RECOMPILE_DEBOUNCE_S` window → exactly 1 recompile dispatched (not 2 or 3). Verify via mock `compile_segment` call count. |
| `test_recompile_skipped_for_child_of_existing_parent` | `backend/tests/pipeline/test_recompile.py` (new) | Negative | New child clip with `parent_id != None` joins cluster → `_should_recompile` returns False → `compile_segment` NOT invoked. |
| `test_recompile_offline_demo_e2e` | `backend/tests/pipeline/test_recompile.py` (new) | Integration | Set `OFFLINE_DEMO=true`. Run 3-parent recompile path end-to-end. Assert: moderate_clip returned passthrough each time; segment row exists with `source_count=3`; no httpx calls made (use `respx` or `httpx.MockTransport`). |
| `test_recompile_preserves_per_clip_moderation` | `backend/tests/pipeline/test_recompile.py` (new) | Moderation re-flow | 2 parents pass mod gate, 3rd parent has `decision='passed'` with hate `verdict='flag'` raw_response → recompile fires → re-emitted segment row has `soft_flag=true`. Verifies the existing `compile.py:629-648` derivation runs on recompile membership. |
| `test_recompile_does_not_bypass_moderation_block` | `backend/tests/pipeline/test_recompile.py` (new) | Moderation re-flow / negative | Existing 2-parent compiled cluster + 3rd "parent" arrives but moderation returns `decision='blocked'` → `cleanup_blocked_clip` runs → `cluster_worker` never sees the clip → no recompile fires (the blocked clip is invisible to clustering). |

### Test Fixtures Needed

- `gemini_moderation_mock` fixture (already exists per Phase 11 STATE.md) — reuse.
- New fixture `multi_parent_compiled_cluster` — sets up 2-parent cluster with completed `compile_segment` and a published `segments` row. Builds on existing `test_compile.py` fixtures.
- Mock `compile_segment` call counter (use `unittest.mock.AsyncMock(wraps=...)`).

### Wave 0 Gaps

- [ ] `backend/tests/pipeline/test_recompile.py` — new file, all 6 tests above.
- [ ] (No new fixtures or framework install — pytest + asyncpg test scaffolding already in place per `conftest.py`.)
- [ ] Add `RECOMPILE_DEBOUNCE_S` to `backend/config.py` (default 60.0, env-overridable).

## Risk & Mitigation

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| **R1 — Recompile thrashing during a hot event** (10+ recompiles in an hour for a single cluster) | Medium (depends on burst pattern) | 60s debounce window enforces ≤60 recompiles/hr ceiling. Soft-warn at 5 recompiles per cluster lifetime via Logfire `log.warning`. Per-cluster compile span counts visible in Logfire — alertable post-pilot. No hard cap (avoid silent invisibility bug). |
| **R2 — Moderation bypass via stitch transformation** (concatenated content trips a category that no per-clip would alone) | Low | Per-clip gate is the contract per **MOD-01** + **MOD-06**. Audit table is keyed on `clip_id`. Soft-flag re-derivation in `compile.py:629-648` already runs on every recompile, so hate/violence aggregates update. Hard-block categories (csam/sexual/extremist/self_harm) are per-clip by design — Phase 11 D-04 reconciliation explicitly specifies classifier-only at clip ingest. Documenting this as a known trade-off with a verify-phase test (`test_recompile_does_not_bypass_moderation_block`). |
| **R3 — SSE event-type collision with future `segment_updated` event** | Low | Path B-lite reuses `segment_published` deliberately — no new event type. If a future feature wants `segment_updated` (e.g., "new angle added" badge), it's additive — both events can coexist (the union in `types.ts:113` is open). |
| **R4 — `_RECOMPILE_COUNTS` dict leaking on long-lived process** | Low | In-memory dict scoped to `backend/pipeline/compile.py` module. Reset on Railway redeploy. For the pilot this is fine. Post-pilot move to `clusters.compile_count` column when adding a hard cap. |
| **R5 — `set_compile_in_flight` lock held forever if compile_segment crashes between line 688 (`set_compile_in_flight(False)`) and the broadcast** | Already mitigated | The `finally` block at compile.py:687 guarantees the flag clears even on exception. The 60s TTL provides a safety net if `finally` itself fails (e.g., DB connection lost) — the next `_should_recompile` call past the TTL window will re-acquire. |

## Open Questions for the Planner

1. **Should `RECOMPILE_DEBOUNCE_S` be env-overridable or hard-coded?** Recommend env-overridable for the same reason `CLUSTER_THRESHOLD` is (`backend/cluster.py:148`). Default 60.0; env var `RECOMPILE_DEBOUNCE_S`.
2. **Should the soft-warning threshold (5 recompiles per cluster) be configurable?** Recommend hard-coded at module level for the pilot; revisit if a hot event in real traffic crosses 5 frequently.
3. **Does the recompile dispatch need its own `STAGE_DURATION.labels(stage=...)` label (e.g., `stage="recompile"`)?** Phase 8 currently treats compile and recompile as the same stage. Recommend keeping it as `stage="compile"` with a `recompile=true` label or span attribute for filtering. Avoid label cardinality blowup per **OBS-04**.
4. **Should `_RECOMPILE_COUNTS` be persisted across restarts?** No for pilot — see R4. Plan should note "if needed post-pilot, add `clusters.compile_count` column."
5. **Is the iOS Safari verification step a HUMAN-UAT gate or part of automated UAT?** No automated mobile-Safari test exists in the repo; recommend adding to `14-HUMAN-UAT.md` as a Roan smoke check (5-min effort: upload 3rd video to an existing montage's location, watch the feed update).
6. **Does the planner want a feature flag (`RECOMPILE_ON_NEW_PARENT=true|false`) for gradual rollout?** Recommend yes — add `config.RECOMPILE_ON_NEW_PARENT` (default `True`); gate the new branch in `run.py` on the flag. Cheap rollback if the recompile-storm scenario manifests in pilot traffic.
7. **Plan's "Constraints" section should drop SQLite parity** — confirmed dead per § "SQLite Parity Status" above.

## Sources

### Primary (HIGH confidence — direct codebase reads, 2026-04-30)

- [VERIFIED: `backend/pipeline/run.py:42-53, 56-158`] — `_should_compile` gate, pipeline structure, moderation hook integration.
- [VERIFIED: `backend/pipeline/cluster.py:125-220`] — `cluster_worker` flow, `is_new_cluster` flag, `db.upsert_cluster` + `db.assign_clip_to_cluster` ordering.
- [VERIFIED: `backend/pipeline/compile.py:537-695`] — `compile_segment` body, idempotent segment upsert at 664-673, `soft_flag` re-derivation at 629-648, SSE broadcast at 690-694.
- [VERIFIED: `backend/db_postgres.py:590-625`] — `set_compile_in_flight` / `is_compile_in_flight` CAS lock, 30s TTL semantics.
- [VERIFIED: `backend/db_postgres.py:451-457, 716-735`] — `get_segment_for_cluster`, `count_distinct_parents_in_cluster` — single-source-of-truth helpers.
- [VERIFIED: `backend/pipeline/moderate.py:190-214, 485-697`] — Phase 11 hooks already merged in this branch.
- [VERIFIED: `backend/migrations/versions/20260430_0005_segments_soft_flag.py`] — Alembic migration template (used as reference if Path B were chosen).
- [VERIFIED: `frontend/src/views/Feed.tsx:59-65`] — SSE handler refetches feed on `segment_published`.
- [VERIFIED: `frontend/src/types.ts:113-127`] — `ServerEvent` discriminated union.
- [VERIFIED: `frontend/src/hooks/useEventSource.ts`] — single EventSource mount, auto-reconnect via browser.
- [VERIFIED: `backend/tests/test_stitch_recompile.py`] — confirms ffmpeg atomic-publish path is recompile-safe.
- [VERIFIED: `ls backend/db_sqlite.py` → not found] — SQLite retirement confirmed on disk.
- [VERIFIED: `backend/db.py` (read full file)] — single re-export of `db_postgres`.
- [VERIFIED: `.planning/STATE.md:90`] — STATE confirms PR #11 dropped SQLite.
- [VERIFIED: `.planning/REQUIREMENTS.md`] — no Phase 14 requirement IDs; impacted upstream IDs listed in § Phase Requirements.
- [VERIFIED: `.planning/config.json`] — `nyquist_validation: false`, `commit_docs: true`.

### Secondary (none used)

No WebSearch / Context7 / external docs needed — phase is entirely about existing-codebase orchestration. All claims are codebase-grounded.

### Tertiary (none used)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| (none) | All claims verified against codebase | — | — |

**No `[ASSUMED]` claims in this research.** Every recommendation is grounded in a current file read on 2026-04-30. The planner can lock decisions without needing user confirmation on training-data assumptions.

## Metadata

**Confidence breakdown:**
- Path B-lite recommendation: HIGH — codebase reads confirm every required hook already exists; recompile is purely additive plumbing.
- 60s debounce window: MEDIUM — engineering judgment based on existing 30s TTL precedent; could be tuned post-pilot against real burst patterns.
- "No moderation re-flow" recommendation: HIGH — grounded in Phase 11 audit-table contract (MOD-06) and existing `compile.py:629-648` soft-flag re-derivation.
- "No frontend change" recommendation: HIGH — verified existing handler at `Feed.tsx:60` already triggers full refetch on `segment_published`.
- Recompile cap = soft-warn-only: MEDIUM — pilot-scale judgment; might revisit if hot-event traffic crosses 5/cluster regularly.

**Research date:** 2026-04-30
**Valid until:** 2026-05-30 (codebase moves quickly; re-verify any claim if compile.py / run.py / cluster.py changes before plan-phase)

## RESEARCH COMPLETE
