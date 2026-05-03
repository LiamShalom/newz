# Phase 14 — Recompile Montage on New Parent in Existing Cluster

**Status:** Open — awaiting `/gsd-plan-phase 14`
**Owner:** Liam (backend), with frontend touchpoint only on the SSE consumer
**Branch:** `liam/montage-recompile-on-cluster-update`
**Created:** 2026-04-30

Resolves the long-standing v1.0-deferred debug item `montage-not-updating` and ROADMAP Mando feature-track #8 ("Adding videorecordings to existing montages").

## Problem

When a new videorecording is uploaded and its parent embedding matches an **existing** cluster (one that already has a published montage), the new content lands in cluster metadata but the existing montage is **never** re-stitched. The new angle is invisible to viewers; the segment row stays stale.

Code-level investigation (2026-04-30) confirmed the gap is purely orchestration; the DB schema is already idempotent re-compile-safe.

## Root Cause (file:line)

| File | Line(s) | Role |
|---|---|---|
| `backend/pipeline/run.py` | 42–53 | `_should_compile` gate — TTL-debounced |
| `backend/pipeline/run.py` | 149–150 | Post-cluster-join compile dispatch |
| `backend/pipeline/cluster.py` | 148–179 | Existing-cluster join path (`db.upsert_cluster` + `db.assign_clip_to_cluster`) |
| `backend/pipeline/compile.py` | 664–673 | Idempotent segment upsert (`ON CONFLICT(cluster_id) DO UPDATE`) — **already safe** |
| `backend/db_postgres.py` | 560–576 | `set_compile_in_flight` 30s TTL CAS lock |
| `backend/pipeline/compile.py` | 690–694 | SSE `segment_published` broadcast site |

**Failing path:**
1. Parent A uploads → cluster C1, no compile (needs ≥2 parents).
2. Parent B uploads → joins C1, now ≥2 distinct parents → `_should_compile` True → compile fires → segment S1 published, `last_compile_at` set.
3. Parent C uploads (same location/time bucket) → joins C1 via cluster.py:148–179 → control returns to run.py:149 → `_should_compile` returns **False** because `last_compile_at` is within the 30s TTL window → compile **never** fires → S1 stays stale, parent C is invisible.

After 30s, nothing re-evaluates compile-readiness for already-compiled clusters either. The gate only ever fires reactively on a cluster-join event.

## Scope IN

1. Detect when a **new distinct parent** joins a cluster that already has a compiled segment. (A new child of an existing parent does NOT need re-compile — the montage already had access to that videorecording's embedding range.)
2. Trigger a recompile path. Two candidate approaches to evaluate during plan-phase:
   - **Path A (light):** On new-distinct-parent join with an existing segment, reset/extend `last_compile_at` so `_should_compile` fires the next pass. Minimal code surface; reuses existing machinery.
   - **Path B (robust):** Add `montage_dirty` (bool) or `version` (int) column to segments. Flip on parent-scope cluster mutation. Broadcast a distinct `segment_updated` SSE event (separate from `segment_published`). Frontend re-fetches and replaces the card. Likely preferred — gives the frontend a real signal and decouples re-compile from the TTL.
3. Add an integration test: 2 parents → compile fires → 3rd parent joins → re-compile fires → segment row reflects all 3 parents (verifiable via `clip_ids` list / `parents` count / segment `updated_at`).
4. Verify SSE broadcast at `compile.py:690–694` emits an event the frontend can act on for an UPDATE (vs. initial publish). If Path B, ensure `segment_updated` is a distinct event type so the frontend can choose replace-card vs. animate-update vs. badge "new angle added."

## Scope OUT

- No changes to clustering thresholds or composite scoring (Marengo cosine + GPS + timestamp).
- No changes to Marengo embedding pipeline.
- No frontend redesign — only whatever is needed to consume the new SSE event.
- No retroactive re-compile of historical stale montages (covered by `/admin/reset` if needed).
- No multi-cluster reassignment (a clip moving between clusters) — out of scope.
- No changes to the `compile_in_flight` lock semantics for the *single-publish* path.

## Constraints

- **Owner:** Liam (backend). Frontend touchpoint only if Path B and only on the SSE consumer.
- **Moderation re-flow:** Re-emitted segment must respect the Phase 11 moderation gate. If the recompile produces materially different content (new clips selected), moderation should re-evaluate before public emission. Open question — see below.
- **LLM budget unchanged:** 300s wall-clock per compile run.
- **Backend-mode parity:** Must work identically in SQLite and Postgres modes. (Note: SQLite was retired in PR #11 per STATE.md; verify whether SQLite parity is still a real constraint or vestigial.)
- **No new infra:** No Redis, no Celery, no new external services.
- **Anonymity preserved:** No identity-bearing fields introduced; no per-user state added.
- **OFFLINE_DEMO survives:** Re-compile path must work end-to-end with `OFFLINE_DEMO=true`.

## Schema Evidence (Path B feasibility)

- `backend/pipeline/compile.py:664–673` — segment upsert is idempotent; row update on `cluster_id` conflict is the existing behavior.
- No `montage_dirty` / `version` / `compiled_at` column on segments today — would need an Alembic migration if Path B chosen.
- Cluster rows already carry `compile_in_flight` and `last_compile_at` (Phase 9 Postgres migration).

## Test Coverage Gap

- `backend/tests/test_cluster.py:208-238` — covers second-clip joining a cluster.
- `backend/tests/test_stitch_recompile.py:22-61` — covers ffmpeg-level re-compile safety (atomic `.part` → `os.replace`).
- **Zero coverage** for: "new distinct parent joins compiled cluster → recompile fires → segment reflects new parent." This is the first test the plan must add.

## Open Questions (for `/gsd-discuss-phase` or `/gsd-plan-phase` step)

1. **Path A vs Path B vs hybrid?** Path B is more correct but adds an Alembic migration + frontend SSE consumer change. Path A is fast but couples re-compile to a TTL hack.
2. **Debounce window for re-compile.** Don't want to re-stitch 5 times in 30s if parents arrive in rapid succession. What's the right coalescing window — 60s? Until N parents added? Until parent-count plateau detected?
3. **Moderation re-flow on recompile.** If the new compile selects different clip windows, does the re-emitted segment need to re-pass moderation? Or is it sufficient that all *clips* already individually passed moderation? Phase 11 owner (Liam) to decide.
4. **Frontend UX for updated segment.** Replace the card in place? Animate the update? Show a "new angle added" badge? Affects whether Path B's SSE event is `segment_updated` (full replace) or `segment_amended` (delta).
5. **Cap on re-compiles per cluster?** Pathological case: a hot event keeps drawing parents. After how many re-compiles do we stop? (Per-cluster limit, time window, or never?)
6. **SQLite parity dead?** STATE.md says SQLite was retired in PR #11. Confirm `db_sqlite.py` is gone before designing migrations.

## Dependencies

- **Phase 9** (Postgres migration) — landed; provides `set_compile_in_flight` and `last_compile_at`.
- **Phase 10** (Vercel Blob migration) — landed; segment URLs already absolute, re-compile overwriting is safe.
- **Phase 11** (Moderation gate) — shipped on `liam/phase-11-moderation-gate`, awaiting merge to main. Re-flow semantics depend on Phase 11 hooks.

This phase **must not start planning** until Phase 11 is merged to main, otherwise moderation re-flow design is speculative.

## Suggested Next Step

`/clear` then `/gsd-plan-phase 14` once Phase 11 is merged.

If Phase 11 merge is imminent (days), wait. If indefinite, narrow scope to Path A only (no moderation re-flow) and revisit Path B post-Phase-11.
