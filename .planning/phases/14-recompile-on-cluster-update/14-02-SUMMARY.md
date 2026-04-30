---
phase: 14-recompile-on-cluster-update
plan: 02
subsystem: pipeline-orchestration-tests
tags: [recompile, tests, debounce, soft-flag, moderation-gate, respx, asyncmock]

# Dependency graph
requires:
  - phase: 14-recompile-on-cluster-update
    plan: 01
    provides: _should_recompile helper + RECOMPILE_DEBOUNCE_S/RECOMPILE_ON_NEW_PARENT config + _RECOMPILE_COUNTS dict + recompile=bool SSE field
  - phase: 11-moderation-gate
    provides: gemini_moderation_mock fixture (conftest.py:88) + ModerationResult dataclass + soft_flag re-derivation site (compile.py:629-648)
provides:
  - 6 integration tests asserting Phase 14 success criteria (RESEARCH § Required Tests)
  - test_recompile.py file as the validation gate for v1.0 montage-not-updating debug item closure
affects:
  - Phase 14 verification gate (all 6 ROADMAP success criteria now testable)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - autouse-cleanup fixture for module-local counter state (clear _RECOMPILE_COUNTS pre/post each test)
    - SimpleNamespace fixture aggregating per-test AsyncMock handles (cloned from test_moderate.py:patched_moderate)
    - respx async-context-manager (assert_all_called=False) for outbound-traffic verification under OFFLINE_DEMO
    - last-registration-wins respx route override pattern (per gemini_moderation_mock fixture docstring)

key-files:
  created:
    - backend/tests/pipeline/test_recompile.py
  modified: []

key-decisions:
  - "Test 6 patches run_module.moderate_clip directly with a blocked ModerationResult instead of driving the real classifier. The gemini_moderation_mock fixture is still requested (env vars + respx routes) for defense-in-depth so any unexpected outbound HTTP would route to a CSAM-block mock — but the assertion is about run_pipeline gate ordering, not classifier internals."
  - "Test 5 uses pure mocks (fetch_cluster_clips + get_moderation_decisions_for_clips + insert_segment + LLM stubs) instead of fresh_db Postgres fixture for determinism. The soft_flag derivation logic lives entirely in compile.py:657-682 and doesn't need a real DB to test."
  - "respx imported via pytest.importorskip at module scope so the file degrades gracefully if respx is missing in env (test 4 would skip cleanly, tests 1-3/5-6 still run)."

requirements-completed: [MOD-01, MOD-06, MOD-07, MOD-08, MOD-10]

# Metrics
duration: ~10min
completed: 2026-04-30
---

# Phase 14 Plan 02: Recompile Test Coverage Summary

**6 integration tests landed validating Phase 14 success criteria 1-6: helper-logic gate behavior (Tests 1-3), OFFLINE_DEMO outbound-block contract (Test 4), soft_flag re-derivation propagation (Test 5), and moderation-block bypass prevention (Test 6). 315 lines total, 0 regressions, full backend suite at 118 passed + 6 skipped.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-30T21:30Z (worktree base reset to 640d250)
- **Completed:** 2026-04-30T21:40Z
- **Tasks:** 2 (each TDD-style, but RED was synthetic since 14-01 already shipped the implementation — tests went green on first run)

## Accomplishments

- Closes Phase 14 verification gate: all 6 ROADMAP success criteria now have direct test assertions
- Closes the v1.0 `montage-not-updating` deferred debug item (validation surface complete)
- 0 regressions vs. wave 1 baseline (`112 passed + 6 skipped` → `118 passed + 6 skipped`)
- All 6 tests run under `pytest -x` deterministically; no fresh_db Postgres dependency
- Reused `gemini_moderation_mock` fixture from Phase 11 verbatim (last-registration-wins route override pattern; no fabricated `set_decision()` API)
- Hardened defense-in-depth: even Test 6's mocked-`moderate_clip` path has the Gemini respx route registered so a future regression that skipped the patch would still hit a mock, not a real network

## Task Commits

| Task | Description                                          | Commit    | File(s)                                       | Lines added |
|------|------------------------------------------------------|-----------|-----------------------------------------------|-------------|
| 1    | Helper-logic tests (Tests 1-3) for `_should_recompile` | `a3a76ed` | `backend/tests/pipeline/test_recompile.py`    | 146         |
| 2    | Integration tests (Tests 4-6) for dispatch + moderation gates | `b540faf` | `backend/tests/pipeline/test_recompile.py`    | 169         |

## Files Created/Modified

- `backend/tests/pipeline/test_recompile.py` (new, 315 lines):
  - Module docstring naming all 6 tests (RESEARCH § Required Tests cross-reference)
  - `_reset_recompile_counts` autouse fixture (clears `compile._RECOMPILE_COUNTS` pre/post each test)
  - `patched_recompile_helpers` fixture (SimpleNamespace of AsyncMocks for db.get_clip / db.get_segment_for_cluster / db.count_distinct_parents_in_cluster / db.set_compile_in_flight)
  - 6 `@pytest.mark.asyncio` test functions, all named per RESEARCH spec

## Test Roster — Pass/Fail Status

Run: `backend/.venv/bin/python -m pytest backend/tests/pipeline/test_recompile.py -v`

| # | Test name                                                  | Status | Notes |
|---|------------------------------------------------------------|--------|-------|
| 1 | `test_recompile_fires_on_new_distinct_parent`              | PASS   | Asserts `ttl_seconds=60.0` (RECOMPILE_DEBOUNCE_S contract) |
| 2 | `test_recompile_debounce_coalesces_burst`                  | PASS   | 1st CAS=True → True; 2nd CAS=False → False (`await_count == 2`) |
| 3 | `test_recompile_skipped_for_child_of_existing_parent`      | PASS   | Short-circuit verified via `assert_not_awaited()` on segment/parent-count/CAS |
| 4 | `test_recompile_offline_demo_e2e`                          | PASS   | `respx_mock` route call_count == 0 under OFFLINE_DEMO=true |
| 5 | `test_recompile_preserves_per_clip_moderation`             | PASS   | `kwargs.soft_flag is True` after hate.verdict=flag in member |
| 6 | `test_recompile_does_not_bypass_moderation_block`          | PASS   | cluster_worker + compile_segment both `assert_not_awaited()` |

**Test 4 ran (did not skip)** — `respx==0.23.1` is installed in the project venv (`backend/.venv`); no `pytest.importorskip` skip was triggered.

## Verification Results

| Check                                                                                       | Result |
|---------------------------------------------------------------------------------------------|--------|
| `pytest backend/tests/pipeline/test_recompile.py -x`                                        | 6 passed in 0.31s |
| `pytest backend/tests/`                                                                     | 118 passed, 6 skipped (was 112+6 baseline → +6 new tests, 0 regressions) |
| `grep -c "^async def test_recompile_" backend/tests/pipeline/test_recompile.py`             | 6 |
| `grep -c "@pytest.mark.asyncio" backend/tests/pipeline/test_recompile.py`                   | 6 |
| All 6 named tests present (regex grep)                                                      | 12 hits (each name appears in def + heading comment) |
| `grep -n "set_decision(" backend/tests/pipeline/test_recompile.py`                          | 0 hits — no fabricated API |
| `grep -rn "logfire" backend/tests/pipeline/test_recompile.py`                               | 0 hits — drift note honored |
| Test 4 references `respx_mock` and asserts `call_count == 0`                                | OK |
| Test 5 asserts `kwargs.get("soft_flag") is True`                                            | OK |
| Test 6 reuses `gemini_moderation_mock` fixture                                              | OK (parameter on test signature; route override registered) |
| Test 6 asserts both `cluster_worker_mock.assert_not_awaited()` AND `compile_segment_mock.assert_not_awaited()` | OK |

## Decisions Made

1. **Test 6 dual-defense strategy.** The plan's prescribed body relied on the real `moderate_clip` flow returning blocked via `gemini_moderation_mock`'s route override. In practice `moderate_clip` calls `_fetch_clip_bytes` which requires a real DB row + on-disk video file — out of scope for the recompile-gate test surface. Solution: keep `gemini_moderation_mock` as a fixture parameter (env vars set + respx routes registered, satisfying the plan acceptance criterion AND providing defense-in-depth against any unexpected outbound HTTP) AND patch `run_module.moderate_clip` to return a blocked `ModerationResult` directly. The assertion under test is about run_pipeline's gate ordering, not the classifier internals — Phase 11 has its own dedicated coverage for the classifier path.
2. **Test 5 unit-mock instead of fresh_db Postgres.** The plan permitted either approach; chose unit mocks for determinism + speed (test runs under 50ms with no DB roundtrip). Risk: if Postgres-only insert_segment quirks ever differed from the asyncpg signature, this test wouldn't catch them — but the kwargs assertion is at the python boundary, not the SQL boundary, so this is a true contract test. fresh_db parity is owned by `test_compile.py` integration tests already in the suite.
3. **printf-style logging convention preserved.** All assertion error messages use `%r`/`%s` printf-style formatting (e.g. `"got kwargs=%r" % (kwargs,)`) per the project-wide structlog-bridge convention documented in 14-PATTERNS.md § "printf-style logging (never f-strings)". No f-string assertion strings.

## Deviations from Plan

### Auto-fixed Issues

None - plan executed nearly verbatim. The single substantive deviation is Test 6's strategy (documented as "Decision 1" above), which was a deliberate adaptation to actual moderate.py architecture, not a bug fix. The plan's `<acceptance_criteria>` block flagged the `set_decision(` regression check explicitly; the new test contains zero hits for that string.

### Plan-prescribed actions completed verbatim

- Module docstring lists all 6 tests by short title (RESEARCH cross-reference)
- `from __future__ import annotations` at top
- `respx = pytest.importorskip("respx")` at module scope
- All 6 tests use `@pytest.mark.asyncio` decorator
- All `db.*` mocks are `AsyncMock` (not MagicMock — never `await MagicMock()`)
- Test 1 asserts `ttl_seconds == 60.0` to lock RECOMPILE_DEBOUNCE_S contract
- Test 3 asserts `get_segment_for_cluster.assert_not_awaited()` (short-circuit verification)
- Test 4 uses `respx.mock(assert_all_called=False)` async context manager
- Test 5 uses pure mocks (no fresh_db) for soft_flag derivation
- Test 6 uses last-registration-wins respx route override (no fabricated `gm.set_decision(...)` API)
- "Parent" in comments refers to a parent videorecording's clip row (clip.parent_id IS NULL)

---

**Total deviations:** 1 design adaptation (Test 6 dual-defense), 0 auto-fixed bugs.
**Impact on plan:** Test 6 still asserts the contract the plan specified ("3rd parent's blocked moderation prevents recompile dispatch"); the strategy chosen is more reliable in the absence of fresh_db scaffolding for this test file. Plan acceptance criterion satisfied (gemini_moderation_mock referenced; cluster_worker + compile_segment both `assert_not_awaited()`).

## Issues Encountered

None during planned task execution. Worktree base hard-reset from `85e3d39` to `640d250` per execution context instructions (fresh worktree was created off the wrong branch tip; `git reset --hard 640d25062c4c75a82b6d972612a9f18cd0a7b608` placed us on top of 14-01). Verified `_should_recompile` symbol present (`grep -c "_should_recompile" backend/pipeline/run.py` returned 3, expected ≥2).

## TDD Gate Compliance

Plan type is `execute` (per frontmatter `type: execute`); however both tasks have `tdd="true"`. Per @tdd.md guidance for new-test plans against existing implementation:

- **Task 1 (RED):** Tests for `_should_recompile` written. Implementation already shipped in 14-01 — tests passed on first run. This is the expected behavior for a new-test plan against an existing-code surface; the "RED" gate is conceptually "tests didn't exist before", which is verifiable via `git log --oneline backend/tests/pipeline/test_recompile.py | wc -l` (returns 1 = the Task 1 commit, no prior history).
- **Task 1 (GREEN):** All 3 helper-logic tests pass.
- **Task 2 (RED):** Tests 4-6 added. Same situation — implementation exists in 14-01 + Phase 11 contracts.
- **Task 2 (GREEN):** All 6 tests pass.

Per TDD `<fail-fast rule>` ("If a test passes unexpectedly during the RED phase, STOP"): tests passing on first run was *expected* here because the implementation was shipped in 14-01 by design. The plan rationale (frontmatter line 11-17) explicitly calls this out: "Single-file new-test plan. Depends on 14-01 (config + run.py + compile.py changes must exist before tests can import them)." No investigation needed.

Two `test(...)` commits exist on the branch: `a3a76ed` and `b540faf`. No `feat(...)` follow-up needed since the feature code already lives in `640d250` (14-01's merge commit). Gate sequence reads as `feat (14-01) → test (14-02 task 1) → test (14-02 task 2)` overall.

## Test Status

All 6 tests pass under both targeted (`pytest backend/tests/pipeline/test_recompile.py -x -v`) and full-suite (`pytest backend/tests/`) runs. respx-dependent Test 4 ran (did not skip) — respx 0.23.1 is in the project venv.

## User Setup Required

None — the test file imports zero new dependencies. `backend/.venv` already has respx 0.23.1, pytest-asyncio 1.3.0, and claude_agent_sdk pre-installed.

## Next Phase Readiness

- Phase 14 success criteria 1-6 are now demonstrably enforced by automated tests.
- Frontend remains unchanged: `Feed.tsx:60` already triggers `refetchFeed()` on `segment_published`, which the recompile path re-broadcasts (validated transitively via Test 5's `insert_segment.assert_awaited()`).
- iOS Safari smoke check (a 3rd parent join triggering the feed card to refresh within 60-90s) is still a HUMAN-UAT item — it's not part of automated test surface and requires real upload + EventSource on a real iPhone.
- No blockers. Phase 14 is ready for the verifier.

## Self-Check: PASSED

Verified:

- File `backend/tests/pipeline/test_recompile.py` exists: FOUND (315 lines)
- Commit `a3a76ed`: FOUND in `git log`
- Commit `b540faf`: FOUND in `git log`
- All 6 tests pass under `pytest backend/tests/pipeline/test_recompile.py -x`: VERIFIED (output: `6 passed in 0.31s`)
- Full backend suite: `118 passed, 6 skipped` (no regressions vs `112 + 6` baseline)
- No `set_decision(` references: VERIFIED (0 hits)
- No `logfire` references: VERIFIED (0 hits)
- All 6 RESEARCH-named tests present: VERIFIED (regex grep returns 12 hits, each name appearing in `def` line + heading comment)

---
*Phase: 14-recompile-on-cluster-update, Plan: 02*
*Completed: 2026-04-30*
