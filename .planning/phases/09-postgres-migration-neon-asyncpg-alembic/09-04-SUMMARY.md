---
phase: 09-postgres-migration-neon-asyncpg-alembic
plan: 04
subsystem: database
tags: [postgres, sqlite, asyncpg, dispatcher, feature-flag, fastapi]

# Dependency graph
requires:
  - phase: 09-postgres-migration-neon-asyncpg-alembic/02
    provides: backend/db_sqlite.py with __all__ (25 names) — SQLite branch target
  - phase: 09-postgres-migration-neon-asyncpg-alembic/03
    provides: backend/db_postgres.py with __all__ (28 names incl. init_pool/close_pool/get_pool) — Postgres branch target
provides:
  - backend/db.py thin module-import-time dispatcher (D-08, ≤35 lines)
  - METADATA_BACKEND env-var feature flag plumbing (DB-06 rollback)
  - D-11 hard-override (OFFLINE_DEMO=true forces sqlite regardless of METADATA_BACKEND)
  - /debug/dbstate guard returning 503 under postgres branch (DB_PATH=None stub)
  - Single startup log line per branch (`metadata_backend=sqlite|postgres|sqlite (forced ...)`)
affects:
  - 09-05 (Alembic migrations — needs dispatcher routing in place)
  - 09-07 (app.lifespan postgres pool init — uses hasattr(db, 'init_pool') from postgres branch)
  - 09-08 (cutover — METADATA_BACKEND=postgres flips production path)

# Tech tracking
tech-stack:
  added: []  # No new deps; uses stdlib logging + existing config module
  patterns:
    - "Module-import-time dispatcher (forbids per-request branching) — D-08"
    - "Feature flag with hard-override (env var dominates other env var) — D-11"
    - "Endpoint guard via stub-sentinel (DB_PATH=None signals postgres branch)"
    - "from .module import * with explicit __all__ for controlled re-export"

key-files:
  created:
    - backend/db.py — 24-line dispatcher (selects db_sqlite vs db_postgres at import)
  modified:
    - backend/app.py — 5-line guard + docstring extension on /debug/dbstate

key-decisions:
  - "Dispatcher runs at module-import time, not per-request (D-08 / RESEARCH Anti-Patterns)"
  - "OFFLINE_DEMO=true takes precedence over METADATA_BACKEND=postgres (D-11 hard-override)"
  - "Unknown METADATA_BACKEND values fall through to safe sqlite default (no fail-loud at dispatcher; pool init owns DSN validation)"
  - "/debug/dbstate retained but gated; sqlite-only utility, 503 under postgres rather than 500"

patterns-established:
  - "Backend dispatcher pattern: thin if/elif at module import, three branches, exactly one log.info line"
  - "Endpoint stub-sentinel guard: read backend-specific stub (DB_PATH=None) before doing any I/O"

requirements-completed: [DB-01, DB-06]

# Metrics
duration: 5min
completed: 2026-04-28
---

# Phase 09 Plan 04: METADATA_BACKEND dispatcher + /debug/dbstate guard Summary

**Thin module-import-time dispatcher routing backend/db imports to db_sqlite or db_postgres per METADATA_BACKEND, with D-11 OFFLINE_DEMO hard-override and a 5-line /debug/dbstate guard returning 503 under postgres.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-28T22:01:01Z
- **Completed:** 2026-04-28T22:05:42Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- backend/db.py recreated as a 24-line thin dispatcher (≤35-line limit met) — the keystone integrating the rest of Phase 9.
- Three env-var combinations route correctly: sqlite-default, postgres-prod, postgres+OFFLINE_DEMO→sqlite (D-11).
- All 25 db_sqlite public names re-exported regardless of branch; 3 lifecycle helpers (init_pool/close_pool/get_pool) added on postgres branch only.
- Exactly one log.info line emitted at module import per branch — verified for all three branches.
- /debug/dbstate guard prevents `aiosqlite.connect(None)` TypeError under postgres; returns 503 with informative detail.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backend/db.py thin dispatcher** — `e221ff7` (feat)
2. **Task 2: Guard /debug/dbstate against postgres DB_PATH=None stub** — `f04ed9f` (feat)

Housekeeping:

3. **Deferred items log** — `f4600bd` (docs) — pre-existing test isolation issues logged for future triage

## Files Created/Modified
- `backend/db.py` *(created, 24 lines)* — Module-import-time dispatcher. Three branches:
  - `METADATA_BACKEND=postgres` + `OFFLINE_DEMO=false` → `from .db_postgres import *` + `log.info("metadata_backend=postgres")`
  - `METADATA_BACKEND=postgres` + `OFFLINE_DEMO=true` → `from .db_sqlite import *` + `log.info("metadata_backend=sqlite (forced by OFFLINE_DEMO=true; D-11)")`
  - else (sqlite or unknown) → `from .db_sqlite import *` + `log.info("metadata_backend=sqlite")`
- `backend/app.py` *(modified, +10/-1 lines)* — `debug_dbstate` function gets a 5-line early-return guard plus docstring extension. No changes outside this function. `HTTPException` and `config` already imported at top of file (no new imports).

## Decisions Made
- **No fail-loud check on missing DATABASE_URL in the dispatcher.** The dispatcher's job is selection, not pool init. `db_postgres.init_pool()` owns DSN validation per its 09-03 contract. This keeps the dispatcher pure (zero side effects beyond the chosen import + one log line).
- **No contextvars binding on the log line.** Per RESEARCH §Open Question 3 — there's no request scope at module-import time, so structlog contextvars binding would be a no-op or worse, leak across processes. Plain `log.info("metadata_backend=...")` only.
- **Guard fires before any I/O.** The DB_PATH-None check raises HTTPException before `aiosqlite.connect(...)` is reached, so no DB connection is attempted under postgres. This converts what would be a TypeError-500 into a 503 with informative detail (T-09-04-03 mitigation).

## Deviations from Plan

None — plan executed exactly as written. The dispatcher and guard were inserted verbatim per the plan body.

## Issues Encountered

- **Pre-existing test isolation issues** discovered during `pytest backend/tests/` verification. Several tests fail when `data/newz.db` accumulates rows across runs — `db_sqlite.DB_PATH` is bound at import time and the `tmp_db` fixture doesn't fully monkeypatch the production module reference. **Verified pre-existing on the v1.0 baseline (HEAD~1)**, so out of scope per executor scope-boundary rule (Rule 4: not directly caused by current task changes). Logged to `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/deferred-items.md`. Tests directly relevant to 09-04 (dispatcher routing for all three env-var combinations + `/debug/dbstate` 200/503) all pass.
- **asyncpg not installed in local venv at the start of verification.** Installed `asyncpg==0.31.0` (already in `backend/requirements.txt` from 09-01) into the venv at `/Users/liamshalom/Hacktech/backend/.venv` to allow the postgres-branch verification to import. This is local-environment hygiene, not a code change.

## Verification Results

| Verification | Command | Result |
|---|---|---|
| Line count ≤ 35 | `wc -l backend/db.py` | 24 ✓ |
| Single dispatcher block | `grep -cE "^if config\.METADATA_BACKEND ..."` | 1 ✓ |
| Three from-imports | `grep -cE "^\s*from \.db_(sqlite|postgres) import \*"` | 3 ✓ |
| No SQLAlchemy/asyncpg in db.py | `grep -c "import asyncpg\|sqlalchemy"` | 0 ✓ |
| No function defs in db.py | `grep -c "^async def \|^def "` | 0 ✓ |
| sqlite branch: 25 names exported | runtime hasattr check | OK ✓ |
| postgres branch: +init_pool/get_pool/close_pool | runtime hasattr + DB_PATH is None | OK ✓ |
| D-11 override: pg+OFFLINE_DEMO→sqlite | runtime hasattr check (no init_pool) | OK ✓ |
| Log line: sqlite branch | `grep -c "metadata_backend=sqlite$"` | 1 ✓ |
| Log line: postgres branch | `grep -c "metadata_backend=postgres"` | 1 ✓ |
| Log line: D-11 override | regex match `\(forced by OFFLINE_DEMO=true; D-11\)` | matched ✓ |
| /debug/dbstate sqlite=200 | TestClient with lifespan | 200 ✓ |
| /debug/dbstate postgres=503 | TestClient (guard fires before pool) | 503 with `'sqlite-only' in detail` ✓ |
| Diff scope | `git diff backend/app.py` | only `debug_dbstate` body modified ✓ |

## User Setup Required

None — no external service configuration required for this plan. METADATA_BACKEND defaults to `sqlite` (v1.0 path); flipping to `postgres` belongs to 09-08 (cutover) once 09-05 (migrations) and 09-07 (lifespan pool init) ship.

## Next Phase Readiness
- Dispatcher in place — 09-05 (Alembic) and 09-07 (lifespan) can build against `from backend import db` knowing the routing contract is fixed.
- 09-07 will use `hasattr(db, 'init_pool')` to gate pool init at app startup (postgres branch only).
- 09-08 cutover will set `METADATA_BACKEND=postgres` in production env; the dispatcher then re-routes on next process start (no code change needed).

## Threat Flags

None. All threat-model items (T-09-04-01 dispatcher tampering, T-09-04-02 503 detail info disclosure, T-09-04-03 DoS via aiosqlite.connect(None)) are addressed by the implementation as planned. No new attack surface beyond what the threat model already enumerates.

## Self-Check: PASSED

- File `backend/db.py` exists ✓
- File `backend/app.py` modified ✓ (`/debug/dbstate` guard + docstring)
- Commit `e221ff7` exists in `git log --oneline` ✓
- Commit `f04ed9f` exists in `git log --oneline` ✓
- Commit `f4600bd` exists in `git log --oneline` ✓
- All plan acceptance criteria verified pre-commit ✓
- All plan-level success criteria verified post-commit ✓

---
*Phase: 09-postgres-migration-neon-asyncpg-alembic*
*Plan: 04*
*Completed: 2026-04-28*
