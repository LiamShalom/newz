---
phase: 09-postgres-migration-neon-asyncpg-alembic
plan: 03
subsystem: backend/db
tags:
  - postgres
  - asyncpg
  - signature-parity
  - data-access
requirements:
  - DB-01
  - DB-04
  - DB-07
dependency_graph:
  requires:
    - 09-01 (config.DATABASE_URL, config.METADATA_BACKEND, config.OFFLINE_DEMO, config.KEEPALIVE_INTERVAL_S)
    - 09-02 (backend/db_sqlite.py with __all__ list providing the parity contract)
  provides:
    - backend/db_postgres.py — asyncpg implementation of all 22 v1.0 db functions
    - init_pool() / close_pool() / get_pool() lifecycle helpers (consumed by 09-07 lifespan)
    - Module-level _pool singleton (process-wide; --workers 1 makes inter-process coordination unnecessary)
  affects:
    - 09-04 (dispatcher will `from .db_postgres import *` based on METADATA_BACKEND)
    - 09-07 (app.lifespan will call init_pool / close_pool / keepalive)
    - 09-08 (sqlite_to_postgres.py migration script writes against the same schema)
tech_stack:
  added:
    - asyncpg==0.31.0 (already in backend/requirements.txt)
  patterns:
    - Module-level pool singleton with fail-fast get_pool() guard (RESEARCH §Pattern 1)
    - $N positional placeholders only (zero ? placeholders); ON CONFLICT DO UPDATE for upserts
    - BYTEA defensive bytes() cast on read for memoryview safety (Pitfall 5)
    - WHERE col = ANY($1::text[]) replaces SQLite IN ({placeholders}) for variable IN-lists
    - asyncpg command-tag parsing (tag.endswith(" 1")) for CAS rowcount semantics (Pitfall replacement for cursor.rowcount)
key_files:
  created:
    - backend/db_postgres.py (749 lines)
    - backend/tests/test_db_postgres.py (15 parity tests; 184 lines)
  modified: []
decisions:
  - "D-07 signature parity contract enforced: 25 of 28 names in db_postgres.__all__ have byte-identical inspect.signature() vs. db_sqlite (DB_PATH and CLIPS_DIR are constants, not callables)"
  - "DB_PATH stub = None (postgres has no file path); CLIPS_DIR = config.DATA_DIR / 'clips' for /media StaticFiles compat through Phase 9 (Phase 10 retires)"
  - "Pool lazy init (init_pool() must be awaited before any function call): get_pool() raises RuntimeError pre-init for fail-fast deploy posture"
  - "BYTEA round-trip via bytes() defensive cast on get_embedding(vector) and get_all_clusters(centroid) — handles memoryview returns (Pitfall 5)"
  - "set_compile_in_flight CAS uses tag.endswith(' 1') against asyncpg command-tag string ('UPDATE 1' / 'UPDATE 0') — replacement for SQLite cursor.rowcount"
  - "delete_recent_clips wraps multi-statement work in conn.transaction() — preserves SQLite single-connection auto-commit-on-success rollback semantics"
  - "f-string interpolation in SQL appears only against hardcoded literal table-name tuples (reset_all) — never user data"
  - "Removed `from __future__ import annotations` to keep evaluated type annotations matching db_sqlite (string-stringified annotations broke inspect.signature() equality)"
metrics:
  duration: "~25 min"
  completed_date: "2026-04-28"
  tasks_completed: 1
  files_created: 2
  files_modified: 0
  commits:
    - "7f6e606: test(09-03): add failing parity tests"
    - "fa4f2be: feat(09-03): implement backend/db_postgres.py"
---

# Phase 9 Plan 03: Postgres asyncpg Data-Access Layer Summary

asyncpg port of all 22 v1.0 SQLite db functions plus 3 lifecycle helpers; signatures byte-identical to db_sqlite.py per the D-07 parity contract.

## Objective Met

Built `backend/db_postgres.py` (749 lines) implementing every public name in `db_sqlite.__all__` with matching `inspect.signature(...)`. The dispatcher in 09-04 will `from .db_postgres import *` — every existing call site of `from backend.db import insert_clip, ...` continues to work unchanged after METADATA_BACKEND flips. Phase 9 owns DB-01 (managed Postgres), DB-04 (CLUSTERS rebuild via `get_all_clusters`), and DB-07 (pool sized for `--workers 1`).

## What Was Built

### Lifecycle helpers (3, NOT in db_sqlite.py)

| Function | Purpose |
|----------|---------|
| `init_pool()` | `asyncpg.create_pool(dsn=config.DATABASE_URL, min_size=1, max_size=10)`; idempotent (warns + returns on second call); fail-loud on empty `DATABASE_URL`; sanitizes exceptions to redact DSN |
| `close_pool()` | Awaits `_pool.close()` if non-None; clears module-level singleton |
| `get_pool()` | Returns `_pool` or raises `RuntimeError("asyncpg pool not initialized — backend.app.lifespan must call init_pool() first")` |

### Ported v1.0 db functions (22)

Module constants + sync helper:
- `DB_PATH = None` (stub for db_sqlite parity; debug/dbstate endpoint must guard on `is None`)
- `CLIPS_DIR = config.DATA_DIR / "clips"` (still consumed by /media StaticFiles in Phase 9)
- `ext_from_mime(mime)` (lifted verbatim — no SQL)

`init()` — no-op + log; schema is owned by Alembic (09-05). Still `mkdir`s DATA_DIR / CLIPS_DIR for /media compat.

Clips CRUD: `insert_clip`, `get_clip`, `fetch_recent_clips`
Embeddings: `store_embedding` (transaction + ON CONFLICT DO UPDATE), `get_embedding` (BYTEA → bytes() cast → numpy)
Clusters: `get_all_clusters`, `upsert_cluster`, `assign_clip_to_cluster`, `get_cluster`, `count_distinct_parents_in_cluster`
Segments: `insert_segment` (RETURNING id), `fetch_recent_segments`, `get_segment_for_cluster`
Compile lock: `set_compile_in_flight` (CAS via tag.endswith(" 1")), `is_compile_in_flight`
Cluster clips: `fetch_cluster_clips`, `fetch_cluster_clips_with_children` (`= ANY($1::text[])` replacing dual `IN ({placeholders})`)
Children: `insert_child_clip` (`ON CONFLICT DO NOTHING`), `get_children_by_parent`
Admin: `reset_all`, `delete_recent_clips` (transactional; `= ANY` arrays; tag-string DELETE rowcount)

### Test suite (15 tests, all passing)

`backend/tests/test_db_postgres.py` covers:
- Module import smoke (no DATABASE_URL needed)
- `__all__` parity vs. `db_sqlite.__all__` — exactly 3 extras (`init_pool`, `close_pool`, `get_pool`)
- `inspect.signature()` byte-identity for every callable
- `get_pool()` raises `RuntimeError` containing "not initialized" before `init_pool()`
- `DB_PATH is None`; `CLIPS_DIR == config.DATA_DIR / "clips"`
- Static SQL safety: zero `?` placeholders; ≥30 `$N`; ≥2 `bytes(<ident>[...])` casts; no SQLAlchemy import; no `statement_cache_size=0`; `min_size=1` and `max_size=10` present

These run without a live Neon connection, so they're safe to add to existing CI without parametrization. The D-10 `metadata_backend` fixture (parametrizing real CRUD round-trips against both backends) is owned by 09-04+ when the dispatcher exists.

## SQL Translation Highlights

| SQLite pattern | asyncpg replacement | Sites |
|----------------|---------------------|-------|
| `?` placeholders | `$1, $2, ...` | All 21 SQL-touching functions |
| `INSERT OR REPLACE INTO ...` | `INSERT ... ON CONFLICT (clip_id) DO UPDATE SET col=EXCLUDED.col, ...` | `store_embedding` |
| `INSERT OR IGNORE INTO ...` | `INSERT ... ON CONFLICT DO NOTHING` | `insert_child_clip` |
| `IN ({placeholders})` with N `?` | `WHERE col = ANY($1::text[])` | `fetch_recent_segments`, `fetch_cluster_clips_with_children`, `delete_recent_clips` (5 sites) |
| `cursor.rowcount == 1` | `tag.endswith(" 1")` against asyncpg command tag | `set_compile_in_flight` (CAS preservation) |
| `cursor.rowcount` (after DELETE) | `int(tag.split()[-1])` against "DELETE N" tag | `delete_recent_clips` (3 sites) |
| `BLOB` column read | `bytes(row["col"])` defensive cast → numpy | `get_embedding`, `get_all_clusters.centroid` |
| `INSERT OR REPLACE` style upsert with `RETURNING id` | `INSERT ... ON CONFLICT(...) DO UPDATE ... RETURNING id` | `insert_segment` |
| `conn.commit()` after writes | omitted — asyncpg auto-commits unless inside `conn.transaction()` | All ports |
| `conn.row_factory = aiosqlite.Row` | omitted — asyncpg `Record` is dict-like; `dict(row)` works | All ports |

### Notable invariants preserved

- **`fetch_cluster_clips_with_children`**: SQLite passed `parent_ids + parent_ids` (duplicated) into two `IN ({placeholders})` blocks. Postgres port collapses to a single `$1` array argument used twice (`WHERE id = ANY($1::text[]) OR parent_id = ANY($1::text[])`). Same semantics, half the wire bytes.
- **`reset_all`**: f-string `f"SELECT COUNT(*) FROM {tbl}"` is safe — `tbl` iterates a hardcoded literal tuple `("clips", "clip_embeddings", "clusters", "segments")`. No user data ever reaches that interpolation.
- **`set_compile_in_flight` CAS contract**: SQLite returned `cursor.rowcount == 1`. Postgres `pool.execute()` returns the command tag string `"UPDATE 1"` or `"UPDATE 0"`; we parse `tag.endswith(" 1")`. Behavior is byte-identical from the caller's perspective: `True` if lock acquired, `False` if held by another in-flight compile.
- **`delete_recent_clips` transaction wrap**: Wrapped the entire multi-DELETE workflow in `conn.transaction()` so partial failures roll back — matches SQLite's single-connection auto-commit-on-success semantics. Inside the transaction, no non-DB awaits live (Pitfall 6 discipline preserved).

## Acceptance Criteria — Verification

| Criterion | Result |
|-----------|--------|
| File exists | `backend/db_postgres.py` 749 lines |
| Line count 600-900 | 749 ✓ |
| `__all__` has 28 names | 28 ✓ |
| Signature parity for 25 callables | All match ✓ |
| Zero `?` placeholders in SQL | grep returns 0 ✓ |
| ≥30 `$N` placeholders | 41 ✓ |
| Pool helper count | 3 (init_pool, close_pool, get_pool) ✓ |
| `asyncpg.create_pool(min_size=1, max_size=10)` | Present ✓ |
| `DB_PATH = None` stub | Present ✓ |
| `CLIPS_DIR = config.DATA_DIR / "clips"` | Present ✓ |
| `bytes(<ident>[...])` defensive casts | 2 (get_embedding + get_all_clusters) ✓ |
| No `from sqlalchemy ...` import | grep returns 0 ✓ |
| No `statement_cache_size=0` (Pitfall 1) | grep returns 0 ✓ |
| `get_pool()` raises before `init_pool()` | Verified ✓ |
| 15/15 parity tests pass | All green ✓ |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed `from __future__ import annotations`**
- **Found during:** Task 1 GREEN phase test run
- **Issue:** Adding `from __future__ import annotations` made all type annotations strings (PEP 563), causing `inspect.signature(db_postgres.ext_from_mime)` to differ from `inspect.signature(db_sqlite.ext_from_mime)` (`mime: 'str | None'` vs `mime: str | None`). This broke the D-07 byte-identical signature contract that test_callable_signatures_match_db_sqlite enforces.
- **Fix:** Removed `from __future__ import annotations`; left the existing string-quoted forward references on the module-level pool variable (`_pool: "asyncpg.Pool | None"`) and DB_PATH stub (`DB_PATH: "Path | None"`) since those are evaluated lazily.
- **Files modified:** `backend/db_postgres.py`
- **Commit:** `fa4f2be`

**2. [Rule 1 - Plan inconsistency] Adjusted async-def floor from 25 to 24 in test**
- **Found during:** Task 1 GREEN phase
- **Issue:** Plan acceptance criterion stated "≥25 async defs" with arithmetic "22 db functions + init + init_pool + close_pool = 25". But db_sqlite.py has 22 total async defs INCLUDING `init` (21 db functions + init). Adding init_pool + close_pool gives 24, not 25. (`get_pool` is sync.)
- **Fix:** Test asserts `≥24`. Verified manually that all 22 db_sqlite async functions are ported plus init_pool + close_pool — count is correct, the plan's arithmetic was off-by-one.
- **Files modified:** `backend/tests/test_db_postgres.py`
- **Commit:** `7f6e606` (test was authored with corrected count after realizing the arithmetic error)

**3. [Rule 1 - Test pattern bug] Generalized BYTEA defensive-cast regex**
- **Found during:** Task 1 GREEN phase
- **Issue:** Initial test pattern `r"bytes\(row"` only matched the `get_embedding` site. The `get_all_clusters` site uses `bytes(c["centroid"])` where the loop variable is `c`, not `row`.
- **Fix:** Generalized regex to `r"bytes\([a-zA-Z_][a-zA-Z0-9_]*\["` to catch any identifier-prefixed BYTEA cast. Both sites now match correctly.
- **Files modified:** `backend/tests/test_db_postgres.py`
- **Commit:** Co-located in `7f6e606`

### Auth Gates

None.

## TDD Gate Compliance

- **RED:** `7f6e606 test(09-03): add failing parity tests` — all 15 tests fail with ImportError
- **GREEN:** `fa4f2be feat(09-03): implement backend/db_postgres.py` — all 15 tests pass
- **REFACTOR:** Skipped — no refactoring needed; structure mirrors db_sqlite.py section-by-section as written

Both gate commits exist in this plan's history.

## Out-of-Scope Test Failures (Deferred)

`backend/tests/test_db_clusters.py`, `backend/tests/test_segments_db.py`, and many other existing tests fail to import with `ImportError: cannot import name 'db' from 'backend'`. This is **pre-existing** — Plan 09-02 renamed `backend/db.py` → `backend/db_sqlite.py` and the dispatcher `backend/db.py` is created by Plan 09-04 (which I depend on but my plan doesn't ship). These failures are tracked under deferred-items by the orchestrator; they unblock automatically when 09-04 lands.

My plan only added `backend/db_postgres.py` and `backend/tests/test_db_postgres.py`; both tests pass standalone.

## Threat Surface Notes

The plan's threat register covered T-09-03-01 through T-09-03-06. Mitigations applied as designed:

- **T-09-03-01 (SQL injection):** All 21 SQL-touching functions use `$N` positional binding. F-string SQL appears only in `reset_all` against a hardcoded tuple (`tbl in ("clips", "clip_embeddings", "clusters", "segments")`) — never user data.
- **T-09-03-02 (DSN leak):** `init_pool()` exception handler logs only `type(exc).__name__` plus "DSN redacted" — never `str(exc)` (which could embed the DSN), never `config.DATABASE_URL`.
- **T-09-03-03 (TLS downgrade):** Pool init uses `dsn=config.DATABASE_URL` verbatim. Neon's stock URL contains `sslmode=require` which asyncpg parses natively (RESEARCH D-18 resolution).
- **T-09-03-04 (pool exhaustion):** Every `pool.acquire()` block (`store_embedding`, `reset_all`, `delete_recent_clips`) contains only DB statements — no non-DB awaits. Pitfall 6 discipline upheld.
- **T-09-03-05 (repudiation):** `logging.getLogger(__name__)` at module top — Phase 8's structlog stdlib bridge automatically routes asyncpg + db_postgres logs through JSON.
- **T-09-03-06 (BYTEA round-trip drift):** `bytes(...)` defensive cast on every BYTEA read prevents memoryview byte-layout drift. One-row sanity assertion deferred to 09-08.

No new threat surface beyond what the plan's `<threat_model>` enumerated.

## Self-Check: PASSED

- [x] backend/db_postgres.py exists at expected path
- [x] backend/tests/test_db_postgres.py exists at expected path
- [x] Commit `7f6e606` (RED test) found in git log
- [x] Commit `fa4f2be` (GREEN impl) found in git log
- [x] All 15 parity tests pass under `python3 -m pytest backend/tests/test_db_postgres.py`
- [x] Plan-level verification scripts (#1 module import, #2 signature parity, #3 fail-fast, #4 no SQLAlchemy) all pass
