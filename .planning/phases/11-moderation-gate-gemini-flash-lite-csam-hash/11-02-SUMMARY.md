---
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
plan: 02
subsystem: database
tags: [alembic, postgres, migrations, moderation, ddl]

# Dependency graph
requires:
  - phase: 09 (foundation)
    provides: moderation_decisions + reported_csam baseline tables (id+clip_id+created_at)
  - phase: 01 + 10 (merge head)
    provides: 0003_merge_comments_blob revision (current head before this plan)
provides:
  - "0004_moderation_columns migration: adds decision/reason/provider/raw_response/latency_ms/prompt_version + UNIQUE INDEX(clip_id, provider) on moderation_decisions, ncmec_report_id BIGINT on reported_csam"
  - "0005_segments_soft_flag migration: adds segments.soft_flag BOOLEAN NOT NULL DEFAULT FALSE"
  - "Migration head moves from 0003_merge_comments_blob to 0005_segments_soft_flag"
affects: [11-03 (alembic upgrade gate), 11-04 (moderate.py writes moderation_decisions), 11-06 (compile.py writes segments.soft_flag), 11-07 (admin reset/audit endpoints)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Raw op.execute(...) ALTER TABLE statements (no SQLAlchemy ORM helpers — D-04 locked)"
    - "DEFAULT-then-DROP-DEFAULT idiom for non-empty-table NOT NULL ALTER on Postgres"
    - "Hackathon-grade no-rollback downgrade() raising NotImplementedError (mirrors 0001/0002 posture)"

key-files:
  created:
    - "backend/migrations/versions/20260430_0004_moderation_columns.py"
    - "backend/migrations/versions/20260430_0005_segments_soft_flag.py"
  modified: []

key-decisions:
  - "Used DEFAULT-then-DROP-DEFAULT pattern on moderation_decisions.decision and .provider so the NOT NULL ALTER succeeds against any existing rows while still requiring future application inserts to supply both columns explicitly"
  - "Added reported_csam.ncmec_report_id BIGINT NULL in 0004 (additive, post-reconciliation D-20) — cheaper to land alongside the moderation columns than ALTER again later"
  - "Segments.soft_flag uses column-over-derived shape per D-14 — cheap feed read; written at compile time when any cluster member's moderation row carries hate/violence signal (D-08 broadened policy)"

patterns-established:
  - "Phase 11 column-shape migrations descend linearly: 0003_merge → 0004_moderation_columns → 0005_segments_soft_flag"
  - "Multi-statement ALTER TABLE blocks split into one op.execute(...) per statement (matches 0002's idiom — keeps each DDL atomic for postgres write-ahead-log replay)"

requirements-completed: [MOD-06, MOD-07, MOD-08, MOD-09]

# Metrics
duration: 5min
completed: 2026-04-29
---

# Phase 11 Plan 02: Moderation + Soft-Flag Migrations Summary

**Two Alembic migrations authored for Phase 11: 0004 brings moderation_decisions to its full audit-column shape with an idempotency UNIQUE INDEX and adds reported_csam.ncmec_report_id; 0005 adds segments.soft_flag for the tap-to-view interstitial — both files only; the schema-push gate runs in Plan 03.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-29T (worktree spawn)
- **Completed:** 2026-04-29T (after Task 2 commit 63190ac)
- **Tasks:** 2
- **Files created:** 2
- **Files modified:** 0

## Accomplishments
- Authored 0004_moderation_columns.py — six ALTER TABLE statements + UNIQUE INDEX on moderation_decisions, plus ncmec_report_id BIGINT on reported_csam, descending from 0003_merge_comments_blob (verified current head).
- Authored 0005_segments_soft_flag.py — single ALTER segments ADD COLUMN soft_flag BOOLEAN NOT NULL DEFAULT FALSE, descending from 0004.
- Both files pass python smoke test (revision + down_revision strings load cleanly via importlib + alembic.op import succeeds in backend/.venv).
- All acceptance-criteria grep checks pass (revision strings exact, all six column ALTERs present, both DROP DEFAULTs present, UNIQUE INDEX present, ncmec_report_id present, raise NotImplementedError present in both files).

## Task Commits

Each task was committed atomically:

1. **Task 1: Author 0004_moderation_columns migration** — `f642544` (feat)
2. **Task 2: Author 0005_segments_soft_flag migration** — `63190ac` (feat)

## Files Created/Modified
- `backend/migrations/versions/20260430_0004_moderation_columns.py` — Alembic revision 0004; adds six audit columns + UNIQUE INDEX to moderation_decisions; adds ncmec_report_id BIGINT to reported_csam.
- `backend/migrations/versions/20260430_0005_segments_soft_flag.py` — Alembic revision 0005; adds segments.soft_flag BOOLEAN NOT NULL DEFAULT FALSE.

## Decisions Made
- None new — followed plan exactly. The plan's `<action>` blocks specified VERBATIM file content, and both files were written verbatim without modification.

## Deviations from Plan

None — plan executed exactly as written. Both files match the verbatim content blocks in 11-02-PLAN.md task `<action>` sections.

## Issues Encountered
- Initial attempt to run smoke-test against system `python` (`/opt/homebrew/bin/python3`) failed because alembic isn't installed in the global interpreter. Resolved by using the project venv at `/Users/liamshalom/Hacktech/backend/.venv/bin/python` which has alembic installed. This is an environment-discovery issue, not a code issue — both migration files are correct.

## User Setup Required

None — no external service configuration required by this plan. The actual `alembic upgrade head` execution is the [BLOCKING] task in Plan 03.

## Next Phase Readiness
- Both migration files are on disk and ready for Plan 03's `cd backend && alembic upgrade head` gate.
- Plan 03 should verify `alembic current` reports `0005_segments_soft_flag (head)` post-upgrade.
- Plan 04 (moderate.py) and Plan 06 (compile.py) can begin once Plan 03 completes the schema push — the columns they need (decision, reason, provider, raw_response, latency_ms, prompt_version, ncmec_report_id, soft_flag) are now defined in the migration files awaiting application.
- No blockers. Migration sequence is clean: 0001 → 0002_relax_clips_path_not_null + 0002_comments → 0003_merge_comments_blob → 0004_moderation_columns → 0005_segments_soft_flag.

## Self-Check

Verifying claims before returning to orchestrator.

**Files exist:**
- `backend/migrations/versions/20260430_0004_moderation_columns.py` — FOUND
- `backend/migrations/versions/20260430_0005_segments_soft_flag.py` — FOUND

**Commits exist:**
- `f642544` — FOUND (feat(11-02): add 0004_moderation_columns migration)
- `63190ac` — FOUND (feat(11-02): add 0005_segments_soft_flag migration)

**Smoke tests:**
- 0004 importlib loads, revision/down_revision assertion passes
- 0005 importlib loads, revision/down_revision assertion passes
- Combined verification (both files load, all four revision strings correct) passes

## Self-Check: PASSED

---
*Phase: 11-moderation-gate-gemini-flash-lite-csam-hash*
*Plan: 02*
*Completed: 2026-04-29*
