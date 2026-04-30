---
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
plan: 06
subsystem: pipeline+db+frontend
tags: [moderation, soft-flag, compile, segments, insert-segment, frontend-types, mod-07, mod-08]

# Dependency graph
requires:
  - phase: 11-02
    provides: segments.soft_flag column (migration 0005_segments_soft_flag)
  - phase: 11-03
    provides: db.fetch_cluster_clips + db.get_moderation_decisions (read side)
  - phase: 11-04
    provides: moderation_decisions audit rows with raw_response.{hate,violence}.verdict written by moderate_clip
provides:
  - "compile_segment scans all cluster members' moderation_decisions and derives segments.soft_flag at compile time (D-08 broadened policy)"
  - "db.insert_segment (both backends) accepts soft_flag: bool = False kwarg, writes through to segments.soft_flag with ON CONFLICT refresh"
  - "frontend Segment.soft_flag boolean wired into the type system (Roan picks up UI under feature-track #6)"
affects:
  - "11-07 (integration tests will exercise the soft-flag derivation across hate/violence/pass-only fixtures + the malformed raw_response defensive path)"
  - "feature-track #6 / Roan (frontend tap-to-reveal interstitial reads Segment.soft_flag — no further backend change needed for the UI handoff)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-member iterate-and-short-circuit over moderation_decisions: outer loop on cluster members, inner loop on decision rows, innermost check on (hate, violence) categories x (flag, block) verdicts"
    - "Defensive try/except around the entire derivation block — soft-flag failure never blocks segment publication; defaults to False with a WARN log carrying cluster_id"
    - "ON CONFLICT(cluster_id) DO UPDATE SET soft_flag = EXCLUDED.soft_flag in insert_segment — re-compile path refreshes the flag rather than stale-pinning it"
    - "SQLite parity binds soft_flag as integer 0/1 explicitly (mirrors is_hidden binding pattern from 11-03 db_sqlite.set_clip_hidden)"

key-files:
  created: []
  modified:
    - "backend/pipeline/compile.py — soft-flag derivation block inserted between Phase 1.5 parent-diversity guard and Phase 3 insert_segment; soft_flag=soft_flag appended to the Phase 3 insert_segment kwarg list (~33 lines added)"
    - "backend/db_postgres.py — insert_segment signature gains soft_flag: bool = False; INSERT column list + VALUES placeholder + ON CONFLICT SET clause extended (~7 lines added/modified)"
    - "backend/db_sqlite.py — insert_segment signature parity; INSERT column list + VALUES + ON CONFLICT excluded.soft_flag mirror; binds 1/0 integer for the bool (~10 lines added/modified)"
    - "frontend/src/types.ts — Segment interface gains soft_flag: boolean with JSDoc citing D-15/MOD-07/MOD-08 + the Roan handoff (5 lines added)"
    - "frontend/src/components/SegmentCard.test.tsx — fixture extended with soft_flag: false to satisfy the now-required field (1 line added — Rule 3 blocking-issue auto-fix)"

key-decisions:
  - "compile.py derivation block placed AFTER the Phase 1.5 parent-diversity guard but BEFORE Phase 3 insert_segment — same scope-pattern as the diversity guard (read cluster member signal, conditionally update segment row at insert time). soft_flag is computed once, threaded through the existing Phase 3 insert_segment call, and the existing intermediate insert_segment calls (run_id save at L233, fallback at L367, diversity-guard re-insert at L435) intentionally do NOT pass soft_flag — they default to False. This is correct: the canonical Phase 3 insert at L626 is the last writer and overwrites the column via ON CONFLICT, so any pre-Phase-3 rows that landed with soft_flag=False are immediately corrected when the canonical insert fires. Rationale: keeps the derivation atomic at one call site and avoids re-reading moderation_decisions at every insert."
  - "SQLite insert_segment binds soft_flag as `1 if soft_flag else 0` rather than passing the raw Python bool — same convention as db_sqlite.set_clip_hidden from Plan 03 for parity with the SQL log (SQLite stores BOOLEAN as 0/1 integers regardless, but the explicit cast keeps the binding readable and avoids relying on aiosqlite's implicit coercion behavior)."
  - "The plan suggested keyword-only signatures for insert_segment (`*` before the kwargs). The existing Phase 9 codebase uses positional-or-keyword args for both backends (see db_postgres.py:324 pre-edit). Per the plan's explicit fallback guidance — 'If it uses positional args, keep the calling convention' — I appended soft_flag as the last positional-or-keyword arg with a default of False rather than reshaping the signature to keyword-only. Backward-compat is preserved for all existing call sites in compile.py (5 call sites — the run-id save at L233, fallback at L367, diversity-guard re-insert at L435, and pre-existing call patterns), all of which pass kwargs already and gracefully accept the new default."

patterns-established:
  - "Phase 11 segments.soft_flag derivation lives ONLY at the canonical Phase 3 insert in compile_segment; pre-Phase-3 insert_segment calls (run-id save, fallback, diversity-guard) are deliberately permitted to land soft_flag=False because the ON CONFLICT(cluster_id) DO UPDATE on the canonical insert overwrites the column. Future Phase 11 follow-ups that add new insert_segment call sites should NOT replicate the derivation — they should rely on the canonical Phase 3 insert as the last-writer."

requirements-completed: [MOD-07, MOD-08]

# Metrics
duration: ~3min
completed: 2026-04-30
---

# Phase 11 Plan 06: compile.py + insert_segment + frontend types — soft_flag wiring Summary

**compile_segment now scans every cluster member's moderation_decisions for hate/violence verdicts in (flag, block) and threads a single soft_flag boolean into the canonical Phase 3 insert_segment; both DB backends gained an additive soft_flag: bool = False kwarg with ON CONFLICT refresh; frontend Segment interface gained the soft_flag: boolean field for the Roan tap-to-reveal handoff.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-30T15:44:35Z (worktree spawn after Wave 3 merge)
- **Completed:** 2026-04-30T15:47:47Z (after Task 2 commit 80fa81e)
- **Tasks:** 2 (Task 1: compile.py derivation + both backends' insert_segment; Task 2: frontend Segment.soft_flag)
- **Files created:** 0
- **Files modified:** 5 (backend/pipeline/compile.py, backend/db_postgres.py, backend/db_sqlite.py, frontend/src/types.ts, frontend/src/components/SegmentCard.test.tsx)
- **Lines added:** 73 (per `git diff --stat HEAD~2 HEAD`)

## Accomplishments

- **compile_segment soft-flag derivation block (Task 1).** Inserted between the Phase 1.5 parent-diversity guard (L592-596) and the Phase 3 canonical insert_segment (originally L626, now shifted by the new block). The block iterates `await db.fetch_cluster_clips(cluster_id)` → for each member, `await db.get_moderation_decisions(member["id"])` → for each decision row, walks `raw_response[cat]["verdict"]` for `cat in ("hate", "violence")`. First match where verdict ∈ ("flag", "block") triggers `soft_flag = True` and short-circuits all three loops. Wrapped in `try / except Exception` with a WARN log line `"soft_flag derivation failed cluster_id=%s: %s -- defaulting false"` for ops triage on malformed-raw-response failures.
- **Defensive raw_response handling.** The block accepts `raw_response` as either dict (Postgres asyncpg JSONB codec auto-decodes) or str (SQLite stores TEXT — Plan 03's `db_sqlite.get_moderation_decisions` already deserializes, but the defensive `isinstance(raw, str)` + try/except json.loads guards against any future call site that bypasses the deserializer).
- **soft_flag=soft_flag threaded into Phase 3 insert (Task 1).** The existing canonical Phase 3 `await db.insert_segment(...)` call at L626 (now L661 post-edit) appended `soft_flag=soft_flag` as the final kwarg. Pre-Phase-3 insert sites (run-id save L233, fallback L367, diversity-guard re-insert L435) intentionally retain their existing kwarg lists — soft_flag defaults to False from the new signature, and the ON CONFLICT(cluster_id) DO UPDATE on the canonical Phase 3 insert overwrites the column on the second write.
- **db_postgres.insert_segment extension (Task 1).** Signature gained `soft_flag: bool = False` as the final positional-or-keyword param. INSERT column list extended `(..., video_url, soft_flag)`; VALUES placeholder list extended `(..., $9, $10)`; parameter tuple extended `(..., video_url, soft_flag)`. ON CONFLICT(cluster_id) DO UPDATE SET clause extended with `soft_flag = EXCLUDED.soft_flag` so re-compiles refresh the flag.
- **db_sqlite.insert_segment parity (Task 1).** Mirrored exactly: `soft_flag: bool = False` final param; INSERT column list extended; `VALUES (..., ?, ?)` extended; parameter tuple binds `1 if soft_flag else 0` (matching the explicit-cast convention from Plan 03 set_clip_hidden); ON CONFLICT(cluster_id) DO UPDATE SET extended with `soft_flag = excluded.soft_flag`. Function docstring carries a note that SQLite SCHEMA_SQL does not yet declare segments.soft_flag (Plan 03 deferred issue under SQLite-backend retirement).
- **Frontend Segment.soft_flag (Task 2).** Added `soft_flag: boolean` after `video_urls` and before the closing brace of the Segment interface. JSDoc cites Phase 11 D-15 / MOD-07 / MOD-08 with the Roan / feature-track #6 UI handoff. No `soft_flag_reason` field, no enum, no rationale string — D-15 boolean-only contract honored.
- **Verification confirmed.** `python -m py_compile backend/pipeline/compile.py backend/db_postgres.py backend/db_sqlite.py` exits 0. `inspect.signature(insert_segment)` confirms `soft_flag` parameter exists with default False on BOTH backends (verified via the project's parent venv Python at `/Users/liamshalom/Hacktech/backend/.venv/bin/python`). All seven plan-specified grep patterns pass: `soft_flag = False` (compile.py), `soft_flag derivation failed` (compile.py log line), `for cat in ("hate", "violence")` (compile.py), `cat_signal.get("verdict") in ("flag", "block")` (compile.py), `soft_flag=soft_flag` (compile.py kwarg), `soft_flag: bool = False` (both backends), `soft_flag: boolean` (types.ts).
- **TypeScript compile passes (Task 2).** `tsc --noEmit -p tsconfig.json` exits 0 after the SegmentCard.test.tsx fixture fix (see Deviations).

## Task Commits

| Task | Name                                                                          | Commit    | Files                                                                                       |
| ---- | ----------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------- |
| 1    | Soft-flag derivation in compile.py + insert_segment soft_flag kwarg parity    | `a32bf85` | backend/pipeline/compile.py, backend/db_postgres.py, backend/db_sqlite.py                   |
| 2    | Add Segment.soft_flag boolean to frontend types (handoff to Roan)             | `80fa81e` | frontend/src/types.ts, frontend/src/components/SegmentCard.test.tsx                          |

## Files Created/Modified

- `backend/pipeline/compile.py` — modified. Added the Phase 11 soft-flag derivation block (~30 lines) inside `compile_segment` between the parent-diversity guard and the Phase 3 insert. Threaded `soft_flag=soft_flag` into the canonical Phase 3 `await db.insert_segment(...)` call.
- `backend/db_postgres.py` — modified. `insert_segment` signature extended with `soft_flag: bool = False`; INSERT and ON CONFLICT clauses extended; docstring updated with D-08/D-14/D-15 citation.
- `backend/db_sqlite.py` — modified. Parity extension; binds `1 if soft_flag else 0`; docstring updated with parity citation + the SCHEMA_SQL deferred-issue pointer.
- `frontend/src/types.ts` — modified. `Segment` interface gained `soft_flag: boolean` with JSDoc citing D-15 / MOD-07 / MOD-08.
- `frontend/src/components/SegmentCard.test.tsx` — modified. Test fixture extended with `soft_flag: false` to satisfy the now-required field. Rule 3 blocking-issue auto-fix triggered by the type extension.

## Decisions Made

- **Single-call-site derivation (canonical Phase 3 insert is the last writer).** Pre-Phase-3 insert_segment calls (run-id save L233, fallback L367, diversity-guard re-insert L435) intentionally do NOT pass soft_flag. They default to False, and the canonical Phase 3 insert at L626 (now L661) overwrites the column via `ON CONFLICT(cluster_id) DO UPDATE SET soft_flag = EXCLUDED.soft_flag`. This keeps the derivation atomic at one call site (one DB read of moderation_decisions per cluster instead of three) and avoids re-reading at every insert. Trade-off: a brief window exists where the segment row is visible with soft_flag=False before the canonical insert lands; in practice this window is closed before the SSE broadcast at the end of compile_segment, so the feed never sees an intermediate row. Documented in patterns-established so future Phase 11 follow-ups don't replicate the derivation at non-canonical insert sites.
- **Positional-or-keyword signature retained (no `*` keyword-only forcing).** Plan suggested keyword-only signatures; existing Phase 9 code uses positional-or-keyword. Per the plan's explicit fallback guidance ("if it uses positional args, keep the calling convention"), I appended `soft_flag: bool = False` as the final positional-or-keyword param. Backward-compat preserved for all existing call sites — none pass positionally past `source_count`, so the new param is reachable only by kwarg, which is what the new compile.py call uses anyway.
- **SQLite binds soft_flag as integer 0/1 explicitly.** Mirrors the convention from Plan 03 db_sqlite.set_clip_hidden which also binds `1 if hidden else 0`. SQLite stores BOOLEAN as 0/1 integers regardless of binding, but the explicit cast keeps the SQL log readable and decouples from aiosqlite's implicit-coercion behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking issue] SegmentCard.test.tsx fixture broke after types.ts extension**
- **Found during:** Task 2 (post-edit `tsc --noEmit` check)
- **Issue:** Adding `soft_flag: boolean` as a required field on the `Segment` interface caused `frontend/src/components/SegmentCard.test.tsx:35` to fail TS2322 — the existing `segment` fixture object literal omitted `soft_flag`, which is now required.
- **Fix:** Added `soft_flag: false` to the fixture between `video_urls` and `url`. The `blobSegment` fixture spreads `...segment` so it inherits the field automatically; only the base fixture needed the explicit addition.
- **Files modified:** `frontend/src/components/SegmentCard.test.tsx` (1 line)
- **Commit:** `80fa81e` (rolled into Task 2 commit since it's directly caused by the types.ts change in the same commit)
- **Why Rule 3, not Rule 2:** The fixture was correct before Task 2; the new field made it broken. Auto-fix is in scope per the deviation rules ("Only auto-fix issues DIRECTLY caused by the current task's changes").

**No other deviations.** Plan executed exactly as specified for both tasks.

## Acceptance Criteria

All acceptance criteria from the plan's `<acceptance_criteria>` blocks pass:

**Task 1:**
- ✅ `grep -q "soft_flag = False" backend/pipeline/compile.py` — line 624.
- ✅ `grep -q "soft_flag derivation failed" backend/pipeline/compile.py` — line 648.
- ✅ `grep -q 'for cat in ("hate", "violence")' backend/pipeline/compile.py` — line 637.
- ✅ `grep -q 'cat_signal.get("verdict") in ("flag", "block")' backend/pipeline/compile.py` — line 639.
- ✅ `grep -q "soft_flag=soft_flag" backend/pipeline/compile.py` — line 669.
- ✅ `grep -q "soft_flag: bool = False" backend/db_postgres.py` — line 332.
- ✅ `grep -c "soft_flag" backend/db_postgres.py` returns 6 lines (signature + INSERT col + VALUES + RETURNING-context + ON CONFLICT SET + parameter tuple).
- ✅ `grep -q "soft_flag: bool = False" backend/db_sqlite.py` — line 351.
- ✅ `grep -c "soft_flag" backend/db_sqlite.py` returns 7 lines (parity + the explicit `1 if soft_flag else 0` binding).
- ✅ `python -m py_compile pipeline/compile.py db_postgres.py db_sqlite.py` exits 0.
- ✅ `inspect.signature(insert_segment)` confirms `soft_flag` parameter exists with default `False` on both backends (via `from backend.db_postgres import insert_segment` / `from backend.db_sqlite import insert_segment`).

**Task 2:**
- ✅ `grep -q "soft_flag: boolean" frontend/src/types.ts` — line 90.
- ✅ `grep -c "soft_flag" frontend/src/types.ts` returns 1 (only the field declaration; no `soft_flag_reason` or other variants — D-15 boolean-only honored).
- ✅ `grep -q "Phase 11 (D-15" frontend/src/types.ts` — line 85.
- ✅ Original Segment fields verified intact: `id`, `cluster_id`, `ordered_clip_ids`, `title`, `caption`, `location`, `source_count`, `created_at`, `centroid_lat`, `centroid_lng`, `video_url`, `video_urls` — all 12 present at lines 53-83 within the Segment block.
- ✅ `tsc --noEmit -p tsconfig.json` exits 0 after the SegmentCard.test.tsx fixture fix.

## Verification

- ✅ `python3 -m py_compile backend/pipeline/compile.py backend/db_postgres.py backend/db_sqlite.py` exits 0.
- ✅ `from backend.db_postgres import insert_segment as p; assert 'soft_flag' in inspect.signature(p).parameters and inspect.signature(p).parameters['soft_flag'].default == False` succeeds.
- ✅ `from backend.db_sqlite import insert_segment as s; assert 'soft_flag' in inspect.signature(s).parameters and inspect.signature(s).parameters['soft_flag'].default == False` succeeds.
- ✅ `tsc --noEmit -p tsconfig.json` exits 0 (verified by symlinking parent `node_modules` into the worktree, running tsc, then removing the symlink — symlink not committed).
- ✅ `grep -q "soft_flag: boolean" frontend/src/types.ts` exits 0.
- ✅ `grep -q "soft_flag = False" backend/pipeline/compile.py && grep -q "soft_flag=soft_flag" backend/pipeline/compile.py` exits 0.
- (Plan 07 owns the integration test suite — fixture-driven assertions on hate/violence/pass-only paths + the malformed raw_response defensive path.)

## Threat Model Coverage

All `<threat_model>` threats with `mitigate` disposition are addressed:

- **T-11-25 (malformed raw_response crashes compile_segment):** The entire derivation block is wrapped in `try / except Exception` with a WARN log carrying `cluster_id`. Inner `isinstance(raw, str)` + try/except `json.loads` guards against any deserialization edge case. Default `soft_flag = False` on any failure — visible-by-default for ops, missing soft-flag preferable to a missing montage. Plan 07 will add a fixture with malformed raw_response (e.g. truncated JSON, non-dict at category key) to assert the segment still publishes.
- **T-11-26 (boolean reveals "contains hate/violence"):** Disposition is `accept` per the plan — this IS the desired behavior driving the tap-to-view interstitial. D-15 boolean-only contract prevents leaking rationale strings or scores via the JSON surface.
- **T-11-27 (race between Phase 12 admin override and compile_segment):** Disposition is `accept` per the plan. compile_segment reads decisions at compile-time; the resulting soft_flag is immutable for that segment row until re-compile (which re-reads). Phase 12 admin write path is out of scope here.
- **T-11-28 (segment publishes with soft_flag=false despite hate=flag):** The derivation iterates ALL cluster members + ALL their decision rows, checks BOTH "flag" and "block" verdicts, and BOTH "hate" and "violence" categories. Idempotency on the underlying moderation_decisions row is enforced by the UNIQUE(clip_id, provider) constraint from migration 0004 (Plan 02), so each clip has at most one Gemini decision and the iteration cannot miss it. Plan 07 will assert this with multi-member fixtures.

## Threat Flags

None — no new security-relevant surface introduced beyond the threat model's already-enumerated boundaries (DB read at compile time, segments JSON → frontend feed). The soft_flag boolean is explicitly in the threat register's "accept" column for the disclosure path.

## Deferred Issues

- **(Pre-existing, out-of-scope)** SQLite SCHEMA_SQL still does not declare `segments.soft_flag` (Plan 03 Deferred Issue tracked under STATE.md SQLite-backend retirement). The new `db_sqlite.insert_segment` signature accepts `soft_flag` for D-07 dispatcher parity, but writing it through requires the column to exist in the runtime SQLite DB. Plan 11 path requires Postgres or the SQLite SCHEMA_SQL extension. Documented in the new docstring on `db_sqlite.insert_segment`.
- **None within Plan 06 scope.** Plan 07 lands the integration test suite (compile_segment soft-flag derivation across hate/violence/pass-only/malformed-raw-response fixtures).

## Self-Check: PASSED

Verified post-write:

- `backend/pipeline/compile.py` — FOUND (modified; soft-flag derivation block inserted at lines 617-650; soft_flag=soft_flag threaded into Phase 3 insert at line 669).
- `backend/db_postgres.py` — FOUND (modified; insert_segment signature now has soft_flag at line 332; INSERT/CONFLICT clauses extended).
- `backend/db_sqlite.py` — FOUND (modified; parity at line 351; binds 1/0 integer).
- `frontend/src/types.ts` — FOUND (modified; Segment.soft_flag at line 90 with JSDoc at lines 84-89).
- `frontend/src/components/SegmentCard.test.tsx` — FOUND (modified; soft_flag: false fixture line added — Rule 3 auto-fix).
- Commit `a32bf85` (Task 1) — FOUND in `git log --oneline`.
- Commit `80fa81e` (Task 2) — FOUND in `git log --oneline`.
- `.planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-06-SUMMARY.md` — created at this path.
- `python3 -m py_compile` on all three backend files — exits 0.
- `inspect.signature(insert_segment)['soft_flag'].default == False` — verified for both backends via parent venv Python.
- `tsc --noEmit` — exits 0 after SegmentCard.test.tsx fixture extension (symlink to parent node_modules used during verification, removed before commit).
