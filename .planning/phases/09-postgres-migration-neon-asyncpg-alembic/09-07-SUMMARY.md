---
phase: 09-postgres-migration-neon-asyncpg-alembic
plan: 07
subsystem: infra
tags: [postgres, asyncpg, fastapi, lifespan, neon, keepalive]

# Dependency graph
requires:
  - phase: 09-postgres-migration-neon-asyncpg-alembic/03
    provides: db_postgres.init_pool / close_pool / get_pool helpers + asyncpg pool config (max_size=10, sslmode=require parsed natively)
  - phase: 09-postgres-migration-neon-asyncpg-alembic/04
    provides: backend/db.py dispatcher contract (`hasattr(db, "init_pool")` ⇒ postgres branch active)
provides:
  - backend/app.py lifespan with strict startup ordering (RESEARCH Pitfall 7) — init_pool → db.init → rebuild_cache → keepalive task → pre-warm tasks → yield
  - _neon_keepalive coroutine (DEMO-03): pool.fetchval("SELECT 1") every config.KEEPALIVE_INTERVAL_S (240s default)
  - Try/finally shutdown: cancel keepalive task, await it (suppress CancelledError), close asyncpg pool
  - Postgres-branch detection via dispatcher hasattr (no direct config.METADATA_BACKEND check in lifespan)
affects:
  - 09-08 (production cutover — METADATA_BACKEND=postgres flip will exercise this lifespan path against Neon)
  - 09-09 (smoke tests / OFFLINE_DEMO audit — must verify both branches still boot)

# Tech tracking
tech-stack:
  added: []  # No new deps; uses asyncio + logging (already imported) + asyncpg via dispatcher
  patterns:
    - "Dispatcher-trust pattern: lifespan checks `hasattr(db, ...)` instead of branching on config flags directly"
    - "Long-running asyncio task with cooperative-cancel idiom (CancelledError re-raise inside try/except, finally cancels + awaits + suppresses)"
    - "Lifespan ordering enforced by structural separation (numbered steps with comments) rather than orchestration framework"

key-files:
  created: []
  modified:
    - backend/app.py — _neon_keepalive coroutine added; lifespan body fully rewritten with ordered startup + try/finally shutdown (+54/-5 lines)

key-decisions:
  - "Postgres-branch detection in lifespan uses hasattr(db, 'init_pool') — the dispatcher contract from 09-04 — rather than re-checking config.METADATA_BACKEND. The dispatcher is the single source of truth; lifespan trusts it."
  - "Keepalive task cancellation re-raises CancelledError inside the coroutine so shutdown propagates, then suppresses it once in the lifespan finally block. No double-suppression."
  - "Pool init runs BEFORE db.init() (which is a no-op for postgres) BEFORE rebuild_cache() so the rebuild gets a populated pool slot. Keepalive task starts AFTER rebuild so the rebuild's queries are not contended (Pitfall 7)."
  - "Shutdown closes the pool inside try/finally so it runs even if yield raises mid-request — asyncpg's pool.close() drains active connections before returning."

patterns-established:
  - "Lifespan ordering pattern: pool → schema/init → in-memory cache rebuild → background tasks → application-level pre-warm → yield. Reverse for shutdown."
  - "Background-task lifecycle pattern in FastAPI lifespan: capture task handle, cancel on shutdown, await it inside try/except CancelledError to drain, then close the resource the task held."

requirements-completed: [DB-01, DB-04, DB-05, DB-07, DEMO-03]

# Metrics
duration: 4min
completed: 2026-04-28
---

# Phase 09 Plan 07: backend/app.py lifespan — asyncpg pool init + Neon keepalive Summary

**FastAPI lifespan now eagerly initializes the asyncpg pool, rebuilds CLUSTERS from the active backend, launches a 240s SELECT 1 keepalive task to defeat Neon scale-to-zero, and tears everything down cleanly on shutdown via try/finally — all without breaking the SQLite/OFFLINE_DEMO branches that have no pool.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-28T22:09:43Z
- **Completed:** 2026-04-28T22:13:33Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- _neon_keepalive(pool) coroutine added — async-safe loop, cooperative cancellation, structured logging through Phase 8's stdlib bridge.
- lifespan body fully rewritten with the Pitfall 7 ordering: init_pool → db.init → rebuild_cache → keepalive task → pre-warm tasks → yield.
- Shutdown reverses the order via try/finally: cancel keepalive task, await it (suppress CancelledError), close the pool.
- Branch detection via hasattr(db, "init_pool") — both the SQLite default branch and the OFFLINE_DEMO=true forced-sqlite branch boot unchanged (verified end-to-end with TestClient + /health=200).
- DB-01 (pool exists before first query), DB-04 (CLUSTERS rebuild from active backend), DB-05 (Neon-backed durability survives Railway redeploy), DB-07 (pool max_size=10 invocation site), and DEMO-03 (240s keepalive defeats 5min scale-to-zero) all wired in a single file change.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _neon_keepalive coroutine + rewrite lifespan in backend/app.py** — `1a322ba` (feat)

## Files Created/Modified
- `backend/app.py` *(modified, +54/-5 lines)* — Added `_neon_keepalive(pool)` coroutine immediately after `_pre_warm_sdk` and before the `@asynccontextmanager` decorator. Replaced the entire lifespan body with the Pitfall 7-ordered startup + try/finally shutdown. No other functions, middleware, routes, or imports touched.

## Decisions Made
- **`hasattr(db, "init_pool")` is the dispatcher contract.** Lifespan never reads `config.METADATA_BACKEND` or `config.OFFLINE_DEMO` directly; the 09-04 dispatcher already collapses both env vars into the import-time selection. Re-checking them here would risk drift between dispatcher and lifespan if either flag's semantics ever change.
- **CancelledError handled in two places, on purpose.** The keepalive coroutine's `except asyncio.CancelledError: raise` ensures the cancel propagates through `await asyncio.sleep(...)` if it arrives during the sleep, AND through the `try` block if it arrives during `pool.fetchval`. The lifespan's `try: await keepalive_task except CancelledError: pass` then suppresses the propagated exception exactly once — Python's standard "task cleanup on shutdown" idiom.
- **`db.close_pool()` is gated by `hasattr(db, "close_pool")` independently of `init_pool`.** In the postgres branch both are present; in the sqlite branch both are absent. The two-hasattr pattern is symmetric and survives if `close_pool` were ever exported without `init_pool` (it cannot, per dispatcher D-08, but the symmetry is cheap and defensive).

## Deviations from Plan

None — plan executed exactly as written. The `_neon_keepalive` coroutine and lifespan body were inserted verbatim per the plan body (Steps 1.1 and 1.2).

## Issues Encountered

- **9 pre-existing test failures.** When running `pytest backend/tests/`, 9 tests in `test_db_clusters.py`, `test_debug_clusters.py`, `test_pipeline_integration.py`, and `test_segments_db.py` fail. Root cause: `db_sqlite.DB_PATH` is bound at module import from `config.DATA_DIR / "newz.db"`, and the test fixtures monkeypatch the dispatcher (`db.DB_PATH`) but not the underlying module reference, so writes still hit the persistent `data/newz.db`. **Verified pre-existing** by stashing this plan's diff and running the same failure on the base commit (`3a4ef00`). Already documented in `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/deferred-items.md` from Wave 3 (09-04). Out of scope per executor SCOPE BOUNDARY rule (failures are not caused by lifespan changes; lifespan touches no test fixtures and no `db_sqlite` internals).
- **Verification used the project venv at `/Users/liamshalom/Hacktech/backend/.venv` (Python 3.11 + structlog + asyncpg installed).** The system Python 3.14 in this worktree's PATH does not have the project deps. No code change — environment hygiene only.

## Verification Results

| Verification | Command | Result |
|---|---|---|
| `_neon_keepalive` defined | `grep -c "^async def _neon_keepalive" backend/app.py` | 1 ✓ |
| Keepalive uses `pool.fetchval("SELECT 1")` | `grep -c 'await pool\.fetchval("SELECT 1")' backend/app.py` | 1 ✓ |
| Keepalive uses `config.KEEPALIVE_INTERVAL_S` | `grep -c 'config\.KEEPALIVE_INTERVAL_S' backend/app.py` | 2 ✓ (coroutine + comment) |
| Lifespan calls `init_pool` | `grep -c 'await db\.init_pool()' backend/app.py` | 1 ✓ |
| Lifespan calls `close_pool` | `grep -c 'await db\.close_pool()' backend/app.py` | 1 ✓ |
| Postgres-branch via `hasattr` | `grep -cE 'hasattr\(db, "init_pool"\)' backend/app.py` | 1 ✓ |
| `keepalive_task.cancel()` present | `grep -c 'keepalive_task\.cancel()' backend/app.py` | 1 ✓ |
| Lifespan ordering | regex extract on lifespan body | init_pool < db.init < rebuild_cache < _neon_keepalive create_task < _pre_warm_marengo create_task < yield ✓ |
| No new imports | `git diff backend/app.py \| grep "^+" \| grep -E "^\+(import\|from)" \| wc -l` | 0 ✓ |
| SQLite branch boots | `METADATA_BACKEND=sqlite OFFLINE_DEMO=false python -c "TestClient(app); /health"` | 200 ✓ |
| OFFLINE_DEMO=true forced-sqlite branch boots | `METADATA_BACKEND=postgres OFFLINE_DEMO=true python -c "TestClient(app); /health"` | 200 ✓ |
| Adjacent tests still green (40 in lifespan-adjacent suites) | `pytest test_observability_* test_events_sse test_db_postgres -q` | 40 passed ✓ |
| Other tests unaffected | full suite delta vs base commit | 9 pre-existing failures (documented in `deferred-items.md`); 104 passing — no regressions introduced |

## User Setup Required

None — no external service configuration required for this plan. The keepalive task only activates when the postgres branch is selected at process start (`METADATA_BACKEND=postgres` + `OFFLINE_DEMO=false`); the cutover that flips this is owned by 09-08, and `DATABASE_URL` provisioning is owned by 09-08's USER-SETUP. SQLite/OFFLINE_DEMO branches are unchanged for local dev.

## Next Phase Readiness
- Phase 09 lifespan integration complete. The postgres branch now has full lifecycle coverage (pool open → cluster rebuild → keepalive ticking → pool close), satisfying DB-01/04/05/07 and DEMO-03.
- 09-08 (cutover) can flip `METADATA_BACKEND=postgres` in production env; on next process start the dispatcher re-routes and this lifespan picks up `db.init_pool` automatically.
- 09-09 (OFFLINE_DEMO audit / smoke tests) has two stable boot paths to assert against: SQLite default and OFFLINE_DEMO=true forced-sqlite.

## Threat Flags

None. All five threat-model items in the plan (T-09-07-01 pool-starvation by keepalive, T-09-07-02 keepalive failure log info disclosure, T-09-07-03 silent-failure repudiation, T-09-07-04 lifespan-order tampering, T-09-07-05 pool resource leak on shutdown) are mitigated as planned:

- T-09-07-01: keepalive uses `pool.fetchval` (acquire-release one slot for ~ms) every 240s; max_size=10 leaves 9 slots for handlers.
- T-09-07-02: log line uses `%s` of exception type; asyncpg connection errors do not embed the DSN.
- T-09-07-03: every successful ping → INFO; every failure → WARNING. Observable in JSON logs.
- T-09-07-04: ordering enforced by code structure (numbered steps + comments); regression check is the regex-based ordering verification above.
- T-09-07-05: `await db.close_pool()` lives in lifespan's `finally`; runs even when `yield` raises. asyncpg's `pool.close()` drains active connections before returning.

No new attack surface beyond what the threat model enumerates.

## Self-Check: PASSED

- File `backend/app.py` modified ✓ (`_neon_keepalive` + ordered lifespan + try/finally shutdown)
- Commit `1a322ba` exists in `git log` ✓
- All plan acceptance criteria verified pre-commit ✓
- All plan-level success criteria verified post-commit ✓
- SQLite + OFFLINE_DEMO branches both boot to /health=200 ✓
- 0 new imports; 1 new function; 1 rewritten function (lifespan) ✓

---
*Phase: 09-postgres-migration-neon-asyncpg-alembic*
*Plan: 07*
*Completed: 2026-04-28*
