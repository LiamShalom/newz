---
phase: 09-postgres-migration-neon-asyncpg-alembic
reviewed: 2026-04-28T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - backend/alembic.ini
  - backend/app.py
  - backend/config.py
  - backend/db.py
  - backend/db_postgres.py
  - backend/db_sqlite.py
  - backend/migrations/env.py
  - backend/migrations/script.py.mako
  - backend/migrations/versions/20260428_0001_initial_v1_1_schema.py
  - backend/migrations/versions/__init__.py
  - backend/railway.json
  - backend/railway.toml
  - backend/requirements.txt
  - backend/scripts/sqlite_to_postgres.py
  - backend/tests/conftest.py
  - backend/tests/test_db_dispatcher.py
  - backend/tests/test_db_postgres.py
  - backend/tests/test_neon_keepalive.py
findings:
  critical: 0
  warning: 5
  info: 7
  total: 12
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-04-28
**Depth:** standard
**Files Reviewed:** 17 (one file, `backend/.env.example`, was permission-blocked from read; not reviewed)
**Status:** issues_found

## Summary

Phase 9 ports v1.0 SQLite metadata to Neon Postgres via asyncpg + Alembic with a clean import-time dispatcher. The asyncpg port is **SQL-injection-clean** (every user-supplied value goes through `$N` placeholders; the only f-string interpolations are over hardcoded literal table-name tuples). Pool lifecycle is correctly bracketed by FastAPI lifespan, BYTEA round-trip uses the defensive `bytes()` cast (Pitfall 5), DSN is never logged on init failure, and the keepalive task handles `CancelledError` cleanly. RESEARCH Pitfalls 1, 2, 4, 5, 6, 7, 8 are all addressed in code or comments.

Five warnings worth fixing before v1.1 ships:

1. **`tests/conftest.py` `metadata_backend` fixture uses `importlib.reload` — exactly the bug `test_db_dispatcher.py` warns against.** Tests that flip from postgres → sqlite within a session leave `init_pool`/`close_pool`/`get_pool` stuck on the reloaded `backend.db` namespace; downstream `hasattr(db, "init_pool")` checks then misroute.
2. **Two competing Railway config files** (`railway.json` + `railway.toml`) define the same `preDeployCommand`. Currently consistent, but a future divergence would silently change which command runs.
3. **`scripts/sqlite_to_postgres.py` performs four COPY operations without an outer transaction** — a mid-script crash leaves the target half-populated and the row-count gate then blocks restart unless `--force` is passed.
4. **`db_postgres.set_compile_in_flight` parses asyncpg's command tag with `tag.endswith(" 1")`** — fragile string parsing of a documented-stable but not API-typed value.
5. **`backend/app.py:41` uses deprecated `asyncio.get_event_loop()`** inside an async function (pre-existing v1.0, not introduced by Phase 9, but still in the diff scope via the lifespan rewrite).

No critical issues. No SQL injection. No hardcoded secrets. No empty exception swallowing.

## Warnings

### WR-01: conftest `metadata_backend` fixture leaks postgres-only names into sqlite reload

**File:** `backend/tests/conftest.py:36-39`
**Issue:**
The `metadata_backend` fixture uses `importlib.reload(backend.db)` to re-evaluate the dispatcher after flipping `METADATA_BACKEND`. However, `backend/db.py` uses `from .db_postgres import *` / `from .db_sqlite import *` to populate its namespace. `importlib.reload` does **not** clear the existing module dict — it re-executes the module body in-place. Reloading from postgres to sqlite leaves `init_pool`, `close_pool`, and `get_pool` injected by the prior postgres `import *` still present in `backend.db.__dict__`, because `db_sqlite` does not export those names and therefore does not overwrite them.

This is the exact failure mode that `tests/test_db_dispatcher.py:18-23` calls out and works around with `sys.modules.pop("backend.db", None)`. The conftest fixture does not apply that workaround.

Concrete failure: any test using the `fresh_db` fixture that runs **after** a postgres-parametrized test in the same session has `hasattr(db, "init_pool") == True` even when the active branch is sqlite. The fixture (lines 55-57, 65-66) then calls `init_pool()`/`close_pool()` against the leftover postgres function objects, which still reference `db_postgres._pool` (now stale, possibly None or closed) — causing spurious errors or worse, silent misroutes.

In `pytest_asyncio.fixture` parametrize order (sqlite first, then postgres), the bug is masked. Reverse order or selective test runs expose it.

**Fix:**
```python
import importlib
import sys
import os

import pytest
import pytest_asyncio


@pytest.fixture(params=["sqlite", "postgres"], ids=["sqlite", "postgres"])
def metadata_backend(request, monkeypatch):
    backend = request.param
    if backend == "postgres" and not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; postgres path skipped")
    monkeypatch.setenv("METADATA_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    # Mirror test_db_dispatcher.py: pop from sys.modules so the next import
    # rebuilds backend.db.__dict__ from scratch. importlib.reload alone does
    # not evict names injected by `from X import *`.
    sys.modules.pop("backend.db", None)
    import backend.config
    importlib.reload(backend.config)
    import backend.db  # noqa: F401 — fresh import, dispatcher re-runs
    yield backend
```

---

### WR-02: Two Railway config files diverge silently

**File:** `backend/railway.json`, `backend/railway.toml`
**Issue:**
Both files exist and both define `preDeployCommand` for `alembic upgrade head` (json: `["alembic upgrade head"]` as a single string element; toml: `["alembic", "upgrade", "head"]` as exec-form argv). They are currently semantically equivalent only because Railway accepts both forms.

Railway's documented precedence is `railway.toml` > `railway.json` when both exist. A future edit to one file (different healthcheck path, different restart policy, different migration command) will produce a deploy that reads from the file the editor didn't update — and the discrepancy will be invisible until the next deploy fails or behaves unexpectedly.

This is the v1.0 → v1.1 cutover phase; deploy-config drift here is exactly the class of bug that breaks demos.

**Fix:** Pick one. Recommend deleting `backend/railway.json` and keeping `backend/railway.toml` (Railway's preferred format per their config-as-code docs). If both must stay for tooling reasons, add a comment in each pointing at the other and a CI check that diffs them.

---

### WR-03: `sqlite_to_postgres.py` migration is non-atomic across tables

**File:** `backend/scripts/sqlite_to_postgres.py:154-170`
**Issue:**
The migration script opens a single `pg_conn = await asyncpg.connect(pg_dsn)` and then issues four `copy_records_to_table` calls in sequence (one per table), each in its own implicit transaction. There is no outer `async with pg_conn.transaction():` wrapping the whole copy.

Failure modes:
- Network blip on the third table → first two tables populated, last two empty. Row-count gate raises on the failed table, but the partial state is committed.
- `--force` retry then sees non-empty `clips` / `clip_embeddings` and skips the empty-target check, but `copy_records_to_table` will fail with `UniqueViolationError` on the existing primary keys.
- Operator runs without `--force`, gets the empty-target error, then runs `--force` and gets a duplicate-key error. Recovery requires manual `TRUNCATE`.

`SC-2 row-count parity gate` only protects against silent-data-loss within a single table, not against partial multi-table state.

**Fix:**
```python
pg_conn = await asyncpg.connect(pg_dsn)
try:
    await _check_target_empty(pg_conn, force)
    async with aiosqlite.connect(sqlite_path) as sqlite_conn:
        sqlite_conn.row_factory = aiosqlite.Row
        async with pg_conn.transaction():
            for tbl in TABLES_IN_ORDER:
                n_src, n_dst = await _copy_table(sqlite_conn, pg_conn, tbl)
                print(f"{tbl}: copied {n_src} rows; target now has {n_dst}")
                if n_src != n_dst:
                    raise RuntimeError(
                        f"row-count mismatch on {tbl}: src={n_src}, dst={n_dst}"
                    )
            await _verify_centroid_round_trip(sqlite_conn, pg_conn)
finally:
    await pg_conn.close()
```

A single outer transaction means any failure rolls back to a clean empty target — `--force` then becomes unnecessary for retries.

(Alternative if a single transaction is too long for the demo dataset: explicit `TRUNCATE TABLE clips, clip_embeddings, clusters, segments RESTART IDENTITY CASCADE` at the top of `--force` mode.)

---

### WR-04: `set_compile_in_flight` parses asyncpg command tag via brittle string match

**File:** `backend/db_postgres.py:415-431`
**Issue:**
```python
tag = await pool.execute(
    """UPDATE clusters
       SET compile_in_flight = 1, last_compile_at = $1
       WHERE id = $2
         AND (compile_in_flight = 0 OR last_compile_at < $3)""",
    now, cluster_id, now - ttl_seconds,
)
return tag.endswith(" 1")
```

`tag.endswith(" 1")` works for the documented "UPDATE 1" / "UPDATE 0" responses but breaks if asyncpg ever changes the tag format (the format is stable per PostgreSQL wire protocol but the code has no version pin or test that asserts it). It also accepts hypothetical "UPDATE 1" with trailing-newline variants ungracefully.

The CAS test at `test_db_postgres.py:292-317` verifies the True/False boundary but does not assert the exact tag string returned.

**Fix:** Parse the count instead of suffix-matching:
```python
tag = await pool.execute(...)
# asyncpg returns command tags like "UPDATE 1" / "UPDATE 0".
# Parse the trailing integer for explicit semantics.
parts = tag.split()
n = int(parts[-1]) if parts and parts[0] == "UPDATE" else 0
return n == 1
```

This pattern is already used (correctly) in `delete_recent_clips:702`:
```python
counts["embeddings"] = int(tag.split()[-1]) if tag and tag.startswith("DELETE") else 0
```

Apply the same defensive parsing here for consistency.

---

### WR-05: `asyncio.get_event_loop()` deprecated in async context

**File:** `backend/app.py:41`
**Issue:**
```python
async def _pre_warm_marengo() -> None:
    ...
    loop = asyncio.get_event_loop()
    _, _, latency_ms = await loop.run_in_executor(None, _sync_embed, pre_warm_path, "__prewarm__")
```

Inside a coroutine, `asyncio.get_event_loop()` is deprecated as of Python 3.10 and emits `DeprecationWarning`. In Python 3.12+ it raises when there's no running loop, and Python 3.14+ removes the implicit fallback.

Since `_pre_warm_marengo` is always entered from a running loop (it's an `asyncio.create_task` from `lifespan`), the correct API is `asyncio.get_running_loop()`.

This pre-dates Phase 9 (v1.0 code) but lives in the file the phase rewrites, so flagging.

**Fix:**
```python
loop = asyncio.get_running_loop()
```

Or simpler, use `asyncio.to_thread` (Python 3.9+):
```python
_, _, latency_ms = await asyncio.to_thread(_sync_embed, pre_warm_path, "__prewarm__")
```

## Info

### IN-01: `db_postgres.init()` is documented as a no-op but creates directories

**File:** `backend/db_postgres.py:141-151`
**Issue:** The docstring says `init()` is a no-op, then the body does `config.DATA_DIR.mkdir(...)` and `CLIPS_DIR.mkdir(...)`. Lifespan also runs the same mkdirs at lines 149-150 of `app.py`. Idempotent so harmless, but the doc/code mismatch will mislead a future reader. Either fix the docstring to "creates DATA_DIR and CLIPS_DIR; schema is owned by Alembic" or remove the redundant mkdirs.

---

### IN-02: `script.py.mako` template imports `sqlalchemy as sa` despite L-01

**File:** `backend/migrations/script.py.mako:9`
**Issue:** The default Alembic template injects `import sqlalchemy as sa` into every generated migration file. L-01 forbids SQLAlchemy at runtime; Phase 9 hand-writes migrations with `op.execute()` raw SQL, so `sa` is dead-imported in any new migration generated from this template. Not a bug — just a dead import the linter will flag. Strip `import sqlalchemy as sa` from the template (and `${imports if imports else ""}`) to keep generated migrations consistent with the no-ORM rule.

---

### IN-03: `init_pool` second-call warning is silent past the log line

**File:** `backend/db_postgres.py:94-97`
**Issue:** If `init_pool()` is called twice, the second call logs a warning and returns without creating a new pool. That's correct behavior, but a caller that *expected* a new pool (e.g., after a manual `close_pool` followed by `init_pool` in a test) gets a stale `_pool` reference. Consider raising on double-init when `_pool is not None and not _pool._closed`, or document explicitly that `close_pool` must be called between init calls.

---

### IN-04: `reset_all` postgres table-name iteration uses f-string

**File:** `backend/db_postgres.py:621-622`
**Issue:** `for tbl in ("clips", ...)` followed by `f"SELECT COUNT(*) FROM {tbl}"`. The values are hardcoded literals — no SQL injection. The inline comment at lines 615-617 acknowledges this. Flagging only because a static-analysis pass (e.g., `bandit`, `semgrep` `python.lang.security.audit.formatted-sql-query`) will trip on this and a `# nosec` / `# noqa` marker would silence it without weakening the rule globally.

---

### IN-05: Migration script uses `print()` instead of structured logging

**File:** `backend/scripts/sqlite_to_postgres.py:147,151,161,171`
**Issue:** The script imports `logging` and grabs a logger but emits status via `print()`. Phase 8's structlog stdlib bridge would auto-format logger output as JSON for downstream parsing (Pitfall 8); `print()` to stdout bypasses it. Not a bug for an operator-run one-shot, but a missed consistency. Convert to `log.info(...)` for the four progress lines and the success summary.

---

### IN-06: `delete_recent_clips` postgres returns from inside `pool.acquire()` block

**File:** `backend/db_postgres.py:671-672`
**Issue:** Early `return {"counts": counts, "paths_to_delete": paths_to_delete}` is nested inside `async with pool.acquire() as conn: async with conn.transaction():`. asyncpg's context managers handle this correctly (transaction commits empty, connection released). Functionally fine. Flagging because it's a mild readability hazard — moving the early-return outside the transaction (after `parents` is fetched but before the rest of the work) would make the control flow more obvious. Same pattern exists in db_sqlite, so leaving as-is is consistent.

---

### IN-07: `db_postgres.fetch_recent_segments` parses JSON inside lib calls but no error handling

**File:** `backend/db_postgres.py:361, 693`
**Issue:** `json.loads(r["ordered_clip_ids"])` in two places. If a row's `ordered_clip_ids` somehow contains malformed JSON (data corruption, manual SQL edit, partial migration), `json.loads` raises `json.JSONDecodeError` and bubbles up to the caller. v1.0 sqlite has the same behavior. The Phase 9 port preserves the existing semantics — flagging only because the migration window is exactly when malformed data is most likely to appear (e.g., one-shot script crash mid-segment-copy). Consider a defensive `try: parsed = json.loads(...); except json.JSONDecodeError: log.warning(...); continue` in `fetch_recent_segments` so a single bad row doesn't kill the feed.

---

_Reviewed: 2026-04-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
