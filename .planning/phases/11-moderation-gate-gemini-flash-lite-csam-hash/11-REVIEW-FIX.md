---
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
fixed_at: 2026-04-29T00:00:00Z
review_path: .planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 11
skipped: 0
status: all_fixed
---

# Phase 11: Code Review Fix Report

**Fixed at:** 2026-04-29
**Source review:** .planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (4 Critical + 7 Warning; 6 Info findings out of scope)
- Fixed: 11
- Skipped: 0
- Tests: 22/22 passing in Phase 11 suite (17 baseline + 5 new regression tests)

## Fixed Issues

### CR-01: `_drain_task` swallows BaseException and breaks cancellation propagation

**Files modified:** `backend/pipeline/moderate.py`
**Commit:** `5d336d7`
**Applied fix:** Replaced overly-broad `except (asyncio.CancelledError, BaseException)` with separate handlers — `except asyncio.CancelledError` re-raises when the current task is itself being cancelled by the outer scope (Python 3.11 `cancelling()`), and `except Exception` swallows the drained task's own non-cancel exception. KeyboardInterrupt / SystemExit no longer absorbed; outer-scope cancel propagates.

### CR-02: CSAM-block path deletes evidence when preservation write fails

**Files modified:** `backend/pipeline/moderate.py`, `backend/tests/pipeline/test_moderate.py`
**Commit:** `6eaf4c3`
**Applied fix:** Gated `cleanup_blocked_clip` on a `safe_to_cleanup` flag that flips False when `write_reported_csam` raises on a `gemini_csam_block` path. Added regression test `test_moderate_csam_preservation_failure_skips_cleanup` that injects a preservation write failure and asserts cleanup was NOT awaited. § 2258A 1-year retention obligation no longer destroyed by silent error swallowing. Non-CSAM hard-blocks still proceed to cleanup unconditionally.

### CR-03: Typed-exception ladder cannot match real Gemini SDK errors

**Files modified:** `backend/pipeline/moderate.py`, `backend/tests/pipeline/test_moderate.py`
**Commit:** `e09d94d`
**Applied fix:** Added `google.genai.errors.ClientError` (4xx → blocked) and `ServerError` (5xx → unknown) branches to `_classify_exception` BEFORE the legacy httpx branches. Local-imported the genai errors module to keep OFFLINE_DEMO load-safe. Status code extracted from `exc.code` per the SDK's surface. Added regression tests `test_moderate_genai_client_error_blocked` and `test_moderate_genai_server_error_unknown` using real `genai_errors.ClientError(400, ...)` and `ServerError(503, ...)` instances. D-05 routing now matches real-prod traffic.

### CR-04: SQLite OFFLINE_DEMO path crashes on first clip — missing tables/columns

**Files modified:** `backend/db_sqlite.py`, `backend/tests/test_offline_demo_firewall.py`
**Commit:** `e60a419`
**Applied fix:** Added Phase 11 schema parity to `db_sqlite.init()` — `moderation_decisions` table with UNIQUE(clip_id, provider) index, `reported_csam` table with UNIQUE(content_hash) index, and `clips.is_hidden` column (PRAGMA-gated ALTER for idempotency). Updated the deferred-issue comment block. Added regression test `test_offline_demo_writes_moderation_row_to_sqlite` that runs `moderate_clip` end-to-end against a fresh tmp_path SQLite DB without mocking `write_moderation_decision` and asserts the row landed correctly. OFFLINE_DEMO contract restored.

### WR-01: Branch B masks gemini-passed decisions when embed fails

**Files modified:** `backend/pipeline/moderate.py`, `backend/tests/pipeline/test_moderate.py`
**Commit:** `14b6161` (combined with WR-02)
**Applied fix:** In `_moderate_real`'s Branch B (`gemini_task` finished first), narrowed `except BaseException` to `except Exception` plus an explicit `except asyncio.CancelledError: raise` so outer-scope cancels still propagate. Added a structured WARNING log line when embed raises, naming the exception type so ops can correlate the metric muddling between in-gate `stage="moderate"` and the retry's `stage="embed"`.

### WR-02: `_fetch_clip_bytes` + outer `db.get_clip` is a duplicate read

**Files modified:** `backend/pipeline/moderate.py`, `backend/tests/pipeline/test_moderate.py`
**Commit:** `14b6161` (combined with WR-01)
**Applied fix:** `_fetch_clip_bytes` now returns a 3-tuple `(bytes, local_path, is_owned_tempfile)`. `_moderate_real` uses the boolean directly instead of doing a second `db.get_clip(clip_id)` round-trip. Updated the test fixture's `fetch_mock` to return the new 3-tuple shape. One DB roundtrip eliminated per clip.

### WR-03: `db_sqlite.write_moderation_decision` returns wrong id under conflict

**Files modified:** `backend/db_sqlite.py`
**Commit:** `5b7c6cd`
**Applied fix:** Added `RETURNING id` to the SQLite UPSERT and read `row[0]` from the returned cursor. SQLite supports RETURNING since 3.35.0 (2021); aiosqlite passes it through. SQLite now matches the Postgres branch's behavior — on conflict, the existing row's id is returned. Falls back to the generated `dec_id` if RETURNING yields no row (defensive).

### WR-04: `db_postgres.get_moderation_decisions` doc-comment falsely claims auto-decode

**Files modified:** `backend/db_postgres.py`
**Commit:** `2962a27`
**Applied fix:** Added module-level `_set_jsonb_codec` async function that registers `json.loads` / `json.dumps` codec on every connection. Wired it via `init=_set_jsonb_codec` in `asyncpg.create_pool`. Updated `get_moderation_decisions` doc-comment to confirm the codec is registered. compile.py's defensive `isinstance(raw, str)` branch is left in place as a no-op safety net (no harm; happens to also cover the SQLite TEXT path).

### WR-05: Missing GEMINI_API_KEY produces silent unknown-everywhere outage

**Files modified:** `backend/app.py`
**Commit:** `aaca968`
**Applied fix:** Added a fail-loud guard in `lifespan` startup: when `not OFFLINE_DEMO and METADATA_BACKEND == "postgres" and not GEMINI_API_KEY`, raise `RuntimeError`. Mirrors the existing DATABASE_URL fail-loud at `db_postgres.init_pool`. OFFLINE_DEMO branch is exempt (the gate short-circuits before any Gemini call); SQLite-only local-dev is exempt (no production traffic).

### WR-06: `_route_verdict` precedence — soft-flag drops categories on hard-block

**Files modified:** `backend/pipeline/moderate.py`, `backend/tests/pipeline/test_moderate.py`
**Commit:** `630647c`
**Applied fix:** Hoisted the `soft_flag_categories` list-comprehension above the hard-block scan loop in `_route_verdict`, so hard-block returns now include the populated list rather than `[]`. Added regression test `test_moderate_hard_block_preserves_soft_flag_categories` that supplies a CSAM-block + violence-flag verdict and asserts `result.soft_flag_categories` includes `"violence"`. The in-memory ModerationResult dataclass is now consistent with the persisted raw_response JSONB.

### WR-07: `compile.py` soft-flag derivation is N+1 over cluster members

**Files modified:** `backend/db_postgres.py`, `backend/db_sqlite.py`, `backend/pipeline/compile.py`
**Commit:** `e308ba2`
**Applied fix:** Added `get_moderation_decisions_for_clips(clip_ids: list[str])` to both backends with byte-identical signatures (D-07 dispatcher contract honored — both backends export it via `__all__`). Postgres version uses `ANY($1::text[])`; SQLite uses an `IN (?,?,...)` placeholder render with positional binds. Updated `compile.py:624-650` to call the batched function once and iterate decisions in pure Python — N+1 collapsed to 1+0. Empty-input fast-path returns `[]` without a DB roundtrip.

## Skipped Issues

None — every Critical and Warning finding was applied successfully. Five new regression tests added; all 22 tests in the Phase 11 suite pass.

---

_Fixed: 2026-04-29_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
