# Phase 9: Postgres Migration (Neon + asyncpg + Alembic) - Research

**Researched:** 2026-04-28
**Domain:** managed Postgres migration; asyncpg + Alembic-async + Neon; metadata cutover from SQLite-on-volume
**Confidence:** HIGH on D-14/D-18 resolutions and core stack; MEDIUM on Neon pooler/keepalive interaction; LOW on pool-exhaustion sizing without load test.

## Summary

Phase 9 swaps SQLite-on-volume for Neon Postgres. Stack is locked: asyncpg + Alembic-async, no SQLAlchemy ORM at runtime, BYTEA centroids round-tripped verbatim from v1.0 BLOB, `METADATA_BACKEND` flag for rollback, `OFFLINE_DEMO=true` hard-overrides to SQLite. Two pre-planning unknowns flagged in CONTEXT.md (D-14 Railway `release:` Procfile support, D-18 asyncpg+Neon TLS) are now resolved: Railway does **not** document Procfile `release:` phase support (their docs say "Only a single process is supported for now") but provides a first-class `preDeployCommand` field in `railway.json`/`railway.toml` that runs in a separate pre-deploy container and blocks the start command on success — this is the correct vehicle for `alembic upgrade head`. asyncpg natively understands `sslmode=require` as a URL query parameter (also accepts `ssl='require'` kwarg), so Neon's stock DATABASE_URL works as-is.

The biggest non-obvious finding: **MOD-09 statutory retention is 1 year (post-2024 REPORT Act), not 90 days** as written in REQUIREMENTS.md/CONTEXT.md. The `content_preserved_until TIMESTAMPTZ` column is fine — only the comment/cleanup-job logic in Phase 11 has to use the right number. Flagging here so Phase 9's column comments don't bake in stale 90 days.

The other landmine: **Neon's `-pooler` (PgBouncer) endpoint breaks asyncpg's prepared-statement cache** unless `statement_cache_size=0`. For our `--workers 1` + `max_size=10` + single-pod profile, the **direct (unpooled) Neon endpoint is the correct choice** — we already pool client-side via asyncpg, and the pooler only helps when you have many short-lived connections (serverless functions). Use the direct endpoint, keep statement caching on, get faster queries.

**Primary recommendation:** Use Railway `preDeployCommand` (not Procfile `release:`) for `alembic upgrade head`; connect to Neon's **direct** endpoint with `sslmode=require` baked into DATABASE_URL; init asyncpg pool in `lifespan()` with `min_size=1, max_size=10`; keep `statement_cache_size` at default; spawn keepalive task with `asyncio.create_task` ticking 240 s; lift-and-shift `db.py` to `db_sqlite.py` and write `db_postgres.py` with byte-identical signatures; Hybrid schema bake-in (all 7 tables, only Phase 9 columns populated); `OFFLINE_DEMO=true` short-circuits to SQLite before any Neon dial.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Inherited (do NOT re-litigate):**
- **L-01:** Neon Postgres provider, asyncpg driver, Alembic async migrations, no SQLAlchemy ORM at runtime.
- **L-02:** Connection pool `max_size=10`, `--workers 1` Procfile pin.
- **L-03:** Centroid storage = BYTEA, identical bytes round-trip from v1.0 BLOB. **No pgvector** in v1.1.
- **L-04:** structlog JSON via stdlib bridge from Phase 8 D-01.
- **L-05:** session_hash = constant sha256 (Phase 8 D-06).

**Phase-9-specific:**
- **D-01:** One-shot dump-and-load script at `backend/scripts/sqlite_to_postgres.py`.
- **D-02:** No dual-write window; one-shot migration only.
- **D-03/D-04/D-05:** Hybrid bake-in — all 7 v1.1 tables in initial migration with FK relations; only Phase 9 columns populated; future-feature columns ride with their owning phases via `ALTER ADD COLUMN`. Initial migration must include `clips.blob_url` (nullable) and `clips.is_hidden` (nullable) so Phases 10/11 don't ALTER existing rows.
- **D-06:** `reported_csam` table created in Phase 9 with `content_hash TEXT NOT NULL` + `content_preserved_until TIMESTAMPTZ NOT NULL` columns. Phase 11 wires writes.
- **D-07:** Module split — `db_sqlite.py` (lift-and-shift) + `db_postgres.py` (asyncpg) + thin `db.py` selector.
- **D-08:** Selection at module import time, not per-request.
- **D-09:** `db_sqlite.py` retained through v1.1 for OFFLINE_DEMO fallback.
- **D-10:** Test fixture parametrizes `METADATA_BACKEND` so existing tests run against both backends in CI.
- **D-11:** `OFFLINE_DEMO=true` hard-overrides to SQLite regardless of `METADATA_BACKEND`.
- **D-13:** Procfile (or Railway equivalent) runs `alembic upgrade head` once per deploy before web start.
- **D-14:** PRE-PLANNING VERIFICATION OWED — confirm Railway honors `release:` Procfile phase. **RESOLVED in this research → use `preDeployCommand` instead.**
- **D-15:** No automatic rollback on migration failure.
- **D-16:** asyncpg pool initialized in FastAPI `lifespan()`, `max_size=10`.
- **D-17:** Neon keepalive `SELECT 1` every 240 s via `asyncio.create_task` in lifespan.
- **D-18:** PRE-PLANNING VERIFICATION OWED — asyncpg uses `ssl='require'`, NOT libpq `sslmode=require`. **RESOLVED in this research → asyncpg accepts BOTH; native URL parsing works.**
- **D-19:** Alembic env.py async config — implementation detail.
- **D-20:** Bulk migration via `asyncpg.copy_records_to_table`, BLOB → BYTEA verbatim.
- **D-21:** Port `rebuild_cache_from_db()` to `db_postgres.py` with identical signature.
- **D-22:** Standard Alembic timestamp prefix for migration filenames.

### Claude's Discretion

- Alembic env.py exact code (D-19) — research recommends the canonical async template pattern below.
- SQLite→Postgres script idempotency guard (D-20) — research recommends an empty-target check (`SELECT count(*) FROM clips` must be 0) plus a `--force` flag override.
- Migration filename style (D-22) — Alembic default `<rev>_<slug>.py` is fine; the rev hash is generated automatically.

### Deferred Ideas (OUT OF SCOPE)

- **pgvector centroid storage** — v1.2+. BYTEA round-trip locked for v1.1 (L-03).
- **Connection pool dynamic sizing** — v1.2+. `max_size=10` is a fixed lock (L-02).
- **Per-pod migration locking** — Out of scope. `--workers 1` Procfile pin holds.
- **Read-replica routing** — v1.2+. Single Neon endpoint at v1.1.
- **Postgres-side full-text search** — Out of scope.
- **`db_sqlite.py` deletion** — v1.2+ scope.
- **Dual-write window cutover** — Explicitly rejected (D-02).
- **Automatic migration rollback on failure** — Out of scope (D-15).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DB-01 | Backend reads/writes all metadata against Neon Postgres | asyncpg pool in `lifespan()`; `db_postgres.py` mirrors `db.py` signatures (Standard Stack §asyncpg, Code Examples §lifespan) |
| DB-02 | Schema migrations versioned + idempotent via Alembic async (no SQLAlchemy ORM at runtime) | Alembic async template (`alembic init -t async`) + `op.execute()` raw SQL pattern keeps ORM out of runtime (Code Examples §Alembic env.py) |
| DB-03 | One-shot SQLite→Postgres dump-and-load utility, no data loss | `aiosqlite.execute("SELECT *")` reader + `asyncpg.copy_records_to_table()` writer; SC-2 row-count gate (Code Examples §migration script) |
| DB-04 | `CLUSTERS` cache rebuilds from Postgres on startup | Port `rebuild_cache()` to `db_postgres.py.get_all_clusters()`; same SQL semantics, asyncpg driver (Code Examples §rebuild_cache port) |
| DB-05 | Backend survives Railway redeploy without losing prior clip metadata | Postgres lives outside Railway's compute container — redeploy wipes only the local volume which Phase 9 stops using for metadata. Verified by Neon's external-managed-DB architecture. |
| DB-06 | `METADATA_BACKEND` flag allows rollback to SQLite | Module-import-time dispatch via `if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO: from .db_postgres import *` (Code Examples §dispatcher) |
| DB-07 | Pool sized for `--workers 1`, `max_size=10`; Procfile pins single-worker | `asyncpg.create_pool(min_size=1, max_size=10)` in lifespan; Procfile already has `--workers 1` implicit (uvicorn default) — Phase 9 makes it explicit |
| MOD-09 | `reported_csam` table created in Phase 9 (writes Phase 11) | Initial Alembic migration creates table with `content_hash TEXT NOT NULL`, `content_preserved_until TIMESTAMPTZ NOT NULL`. **WARNING: REQUIREMENTS.md "90 days" is stale; statute is 1 year post-2024 REPORT Act** (Pitfall §statutory retention) |
| DEMO-03 | Pre-warm `SELECT 1` every 4 minutes vs. Neon scale-to-zero | `asyncio.create_task` in lifespan ticking 240 s; cancelled cleanly on shutdown (Code Examples §keepalive) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Metadata persistence (clips, embeddings, clusters, segments) | Database (Neon Postgres) | Backend driver layer (asyncpg pool) | Neon owns durability + concurrency; backend pool only multiplexes |
| Schema migration | Build/deploy (Railway preDeployCommand) | Database (Alembic versioning) | Migrations must run before web container starts; Alembic owns version table |
| Connection pooling | Backend (asyncpg pool, in-process) | — | `--workers 1` makes process-singleton pool sufficient; no pooler tier needed (Neon's PgBouncer harms us, see Pitfalls) |
| Backend selection (sqlite vs postgres) | Backend module-import time | Config (env var) | Selected once at process boot; per-request branching is forbidden (D-08) |
| OFFLINE_DEMO override | Backend (config + import-time gate) | — | Same fail-soft pattern as Phase 8 D-16 (`SENTRY_DSN=""` → no Sentry init) |
| Cluster cache (in-memory CLUSTERS dict) | Backend (process memory) | Database (rebuild source) | NumPy-cosine search path; Postgres only the persistence layer |
| Centroid storage | Database (BYTEA column) | Backend (`np.float32.tobytes()` round-trip) | No pgvector; numpy owns search; BYTEA is just byte storage |
| Keepalive against scale-to-zero | Backend (lifespan task) | — | Outside any request scope; runs on `asyncio.create_task` loop |
| TLS termination | Driver (asyncpg `ssl='require'` or URL `sslmode=require`) | Neon endpoint (always TLS) | Neon enforces TLS server-side; asyncpg negotiates client-side |
| Statutory CSAM hash retention | Database (`reported_csam` table) | Backend (Phase 11 writer; cleanup job v1.2+) | Phase 9 creates the schema only; writes + retention enforcement are Phase 11 / future |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | 0.31.0 | Async Postgres driver | Industry-standard async driver for Postgres; binary protocol, faster than psycopg2 (`[VERIFIED: pip3 index versions asyncpg → 0.31.0 latest]`). Native `sslmode` URL parsing, BYTEA↔bytes auto-conversion. |
| alembic | 1.18.4 | Schema migrations | The migration tool for Postgres in Python; built-in async template (`alembic init -t async`); supports raw SQL via `op.execute()` so ORM stays out of runtime (`[VERIFIED: pip3 index versions alembic → 1.18.4 latest]`). |
| SQLAlchemy | 2.0.x (Alembic transitive) | Required by Alembic for migration definition only | Alembic depends on SQLAlchemy Core — but only at migration-write/run time, NOT at runtime app code. Confirmed by Alembic docs. `[VERIFIED: alembic transitive dep]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiosqlite | 0.20.0 | Async SQLite driver | Already in `requirements.txt`; needed both for `db_sqlite.py` (OFFLINE_DEMO + rollback) and the one-shot dump script that reads v1.0 SQLite. |
| python-dotenv | 1.0.1 | Loads `.env` for `DATABASE_URL` etc. | Already in stack via `config.py`. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncpg | psycopg3 (async mode) | psycopg3 is the modern psycopg2 successor with async support. Slower than asyncpg's binary protocol; larger API surface. asyncpg wins on perf and is canonical in FastAPI examples. |
| Alembic | yoyo-migrations / sqitch | Both work without SQLAlchemy entirely. Alembic is the dominant choice for Python+Postgres projects, and the async template is upstream-supported. yoyo would mean fighting tutorials forever. |
| Neon direct endpoint | Neon `-pooler` (PgBouncer) | Pooler would interact badly with asyncpg's prepared-statement cache (would need `statement_cache_size=0`). With `--workers 1` and one process-singleton pool, we don't need PgBouncer multiplexing. **Direct endpoint wins.** |

**Installation:**
```bash
pip install asyncpg==0.31.0 alembic==1.18.4
```

**Version verification (run by planner before locking in PLAN.md):**
```bash
pip3 index versions asyncpg | head -3
pip3 index versions alembic | head -3
```
`[VERIFIED 2026-04-28: asyncpg 0.31.0, alembic 1.18.4 are current latest on PyPI]`

## Architecture Patterns

### System Architecture Diagram

```
                                     ┌─────────────────────────────────┐
                                     │   Railway preDeployCommand      │
                                     │   (separate ephemeral container)│
                                     │   $ alembic upgrade head        │
                                     │   exits 0 → web container starts│
                                     └────────────────┬────────────────┘
                                                      │ blocks on success
                                                      ▼
   POST /clips ──┐                          ┌──────────────────────────┐
                 │                          │  Web container (Uvicorn) │
   GET /feed  ───┼───► FastAPI app ─────►   │  --workers 1 (locked)    │
                 │     middleware           │  lifespan() startup:     │
   POST /report ─┘                          │   1. observability       │
                                            │   2. db.init() ────►     │   import-time:
                                            │   3. asyncpg.create_pool │   if METADATA_BACKEND=postgres
                                            │      (max_size=10)       │     and not OFFLINE_DEMO:
                                            │   4. cluster.rebuild()   │       from .db_postgres import *
                                            │   5. asyncio.create_task │     else:
                                            │      → keepalive 240s    │       from .db_sqlite import *
                                            │   6. pre_warm tasks      │
                                            └──┬───────────────────────┘
                                               │
                                               │ async with pool.acquire():
                                               ▼
                                          ┌────────────────┐    sslmode=require   ┌──────────────────┐
                                          │  asyncpg pool  │  ────────TLS────────►│  Neon direct     │
                                          │  size 1..10    │                       │  endpoint (no    │
                                          │  process-wide  │                       │  -pooler suffix) │
                                          └────────────────┘                       └──────────────────┘
                                                  │
                                                  │ (parallel branch when OFFLINE_DEMO=true)
                                                  ▼
                                          ┌────────────────┐
                                          │  aiosqlite     │
                                          │  /data/newz.db │
                                          └────────────────┘
```

Data flow:
1. Railway build → preDeployCommand container runs `alembic upgrade head` against Neon → exits 0 → web container starts.
2. Web container `lifespan()` boots: configure logging, init pool (eager, fail-loud on bad DATABASE_URL), rebuild CLUSTERS cache from Postgres, spawn keepalive + pre-warm tasks.
3. Each request acquires from pool, runs query, releases. No per-request branching on `METADATA_BACKEND` — the dispatcher made that choice once at import time.
4. `OFFLINE_DEMO=true` short-circuits the postgres branch entirely; no Neon DNS lookup ever fires.

### Recommended Project Structure

```
backend/
├── db.py                       # NEW: 8-line dispatcher (D-08)
├── db_sqlite.py                # RENAMED FROM db.py (lift-and-shift, D-07)
├── db_postgres.py              # NEW: asyncpg implementation, signatures match db_sqlite.py
├── config.py                   # MODIFIED: add DATABASE_URL, METADATA_BACKEND, KEEPALIVE_INTERVAL_S, OFFLINE_DEMO
├── app.py                      # MODIFIED: lifespan adds pool init + keepalive task
├── Procfile                    # MODIFIED: keep web: only (preDeployCommand goes in railway.json)
├── railway.json                # MODIFIED: add deploy.preDeployCommand = "alembic upgrade head"
├── alembic.ini                 # NEW: config file from `alembic init -t async migrations`
├── migrations/
│   ├── env.py                  # NEW: async template, target_metadata=None (raw-SQL workflow)
│   ├── script.py.mako          # NEW: Alembic-generated, leave default
│   └── versions/
│       └── <rev>_initial_v1_1_schema.py   # NEW: all 7 tables + FK + indexes (D-04)
├── scripts/
│   ├── __init__.py             # already exists
│   └── sqlite_to_postgres.py   # NEW: one-shot dump-and-load (D-01, D-20)
└── tests/
    ├── conftest.py             # MODIFIED: add metadata_backend parametrize fixture (D-10)
    └── test_db_postgres.py     # NEW: parity tests for asyncpg path
```

### Pattern 1: FastAPI lifespan + asyncpg pool

**What:** Single process-wide asyncpg pool initialized in `lifespan()` startup, closed in shutdown. Pool stored on `app.state` (or module-level — see tradeoff note).
**When to use:** Any FastAPI app with async Postgres on `--workers 1`.

**Example:**
```python
# Source: https://github.com/fastapi/fastapi/discussions/9520 (canonical FastAPI pattern)
# Source: https://magicstack.github.io/asyncpg/current/api/index.html (create_pool signature)
# Source: https://www.sheshbabu.com/posts/fastapi-without-orm-getting-started-with-asyncpg/

import asyncpg
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Module-level pool (chosen over app.state.pool because db_postgres.py functions
# need pool access without an app reference — same shape as v1.0 db.py module-level
# DB_PATH constant). Set inside lifespan, read by db_postgres functions.
_pool: asyncpg.Pool | None = None

def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("asyncpg pool not initialized — call inside request scope after lifespan")
    return _pool

async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=config.DATABASE_URL,    # contains sslmode=require natively (Neon-provided)
        min_size=1,                 # don't hold connections idle when scale-to-zero is fine
        max_size=10,                # L-02 / DB-07
        # statement_cache_size=100  # default; do NOT set 0 unless using -pooler endpoint
        # ssl='require',            # redundant if URL has sslmode=require; either works
    )

async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

### Pattern 2: Alembic async env.py (no SQLAlchemy ORM at runtime)

**What:** Alembic async template that uses asyncpg's connection-create flow but runs migrations in a sync context via `connection.run_sync(do_run_migrations)`. `target_metadata=None` because we hand-write migrations with `op.execute()` raw SQL — no autogenerate.

**When to use:** Locked by L-01 — every Phase 9 / 10 / 11 / 12 migration.

**Example:**
```python
# Source: https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py
# Source: https://alembic.sqlalchemy.org/en/latest/cookbook.html
# Modified to read DATABASE_URL from env (not alembic.ini) and to set target_metadata=None.

import asyncio
import os
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with runtime env (Neon DATABASE_URL).
# Note: alembic + asyncpg requires the URL prefix be postgresql+asyncpg://, not postgresql://
db_url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql+asyncpg://", 1)
db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1) if not db_url.startswith("postgresql+asyncpg://") else db_url
config.set_main_option("sqlalchemy.url", db_url)

# No ORM models -> no autogenerate. Hand-write migrations with op.execute().
target_metadata = None

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # one-shot migration; no pooling
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    raise RuntimeError("Offline mode disabled — Phase 9 always runs against live Neon during preDeployCommand")
else:
    run_migrations_online()
```

### Pattern 3: Module-import-time backend dispatcher

**What:** `db.py` becomes ~8 lines that pick which implementation file to re-export from.

**Example:**
```python
# backend/db.py — entire file
from . import config
import logging

log = logging.getLogger(__name__)

if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO:
    from .db_postgres import *  # noqa: F401, F403
    log.info("metadata_backend=postgres")
elif config.OFFLINE_DEMO and config.METADATA_BACKEND == "postgres":
    from .db_sqlite import *  # noqa: F401, F403
    log.info("metadata_backend=sqlite (forced by OFFLINE_DEMO=true; D-11)")
else:
    from .db_sqlite import *  # noqa: F401, F403
    log.info("metadata_backend=sqlite")
```

**Trade-off note re-export pattern:** `from .db_x import *` requires both `db_sqlite.py` and `db_postgres.py` to declare `__all__` listing the 23 public functions exactly. Alternative — `import backend.db_sqlite as _impl; insert_clip = _impl.insert_clip; ...` — is more explicit and lets editors find references but adds 23 hand-maintained re-export lines per branch and breaks if a function is renamed in only one branch. **Recommendation: use `from .x import *` with explicit `__all__` in both files.** D-10's parametrized test fixture is the safety net that catches signature drift.

### Pattern 4: asyncpg.copy_records_to_table for bulk migration

**What:** Stream-style bulk insert. Tuple field order must match table column order exactly.
**When to use:** The one-shot `sqlite_to_postgres.py` script per table (D-20).

**Example:**
```python
# Source: https://schinckel.net/2019/12/13/asyncpg-and-upserting-bulk-data/
# Source: https://magicstack.github.io/asyncpg/current/api/index.html (copy_records_to_table)

async def _copy_clips(sqlite_conn, pg_conn) -> int:
    cur = await sqlite_conn.execute(
        "SELECT id, path, lat, lng, ts, duration_sec, embedding_status, "
        "embed_latency_ms, cluster_id, session_id, created_at, "
        "parent_id, start_offset_sec, end_offset_sec "
        "FROM clips"
    )
    rows = await cur.fetchall()
    # Tuple order MUST match the columns= argument below; asyncpg writes raw tuples.
    records = [tuple(r) for r in rows]
    await pg_conn.copy_records_to_table(
        "clips",
        records=records,
        columns=[
            "id", "path", "lat", "lng", "ts", "duration_sec",
            "embedding_status", "embed_latency_ms", "cluster_id",
            "session_id", "created_at",
            "parent_id", "start_offset_sec", "end_offset_sec",
        ],
    )
    return len(records)
```

For `clip_embeddings`, the BLOB→BYTEA round-trip is byte-identical: SQLite returns Python `bytes`, asyncpg sends Python `bytes` to BYTEA. Verified by asyncpg docs ("PostgreSQL's bytea type automatically converts to/from Python bytes"). The cluster centroid round-trip path through `np.frombuffer(row["centroid"], dtype=np.float32)` will match v1.0 byte-for-byte.

### Pattern 5: Keepalive task in lifespan (DEMO-03)

**Example:**
```python
# Source: stdlib asyncio + structlog patterns from Phase 8

KEEPALIVE_INTERVAL_S = 240  # 4 min, < Neon's 5-min scale-to-zero idle threshold

async def _neon_keepalive(pool: asyncpg.Pool) -> None:
    log = logging.getLogger("backend.keepalive")
    while True:
        try:
            await pool.fetchval("SELECT 1")
            log.info("neon_keepalive ok")  # info, not debug — we want this in JSON logs
        except Exception as exc:
            log.warning("neon_keepalive failed (non-fatal): %s", exc)
        await asyncio.sleep(KEEPALIVE_INTERVAL_S)

# inside lifespan(), AFTER pool is initialized:
keepalive_task = asyncio.create_task(_neon_keepalive(_pool))
try:
    yield
finally:
    keepalive_task.cancel()
    try:
        await keepalive_task
    except asyncio.CancelledError:
        pass
    await close_pool()
```

### Pattern 6: pytest fixture parametrizing METADATA_BACKEND (D-10)

**Example:**
```python
# backend/tests/conftest.py
import os
import pytest
import pytest_asyncio

@pytest.fixture(params=["sqlite", "postgres"], ids=["sqlite", "postgres"])
def metadata_backend(request, monkeypatch):
    """D-10: every db-touching test runs against both backends.
    
    Postgres test path requires DATABASE_URL pointing at a test database
    (CI: ephemeral Neon branch or local pg). Skip if not configured.
    """
    backend = request.param
    if backend == "postgres" and not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; postgres path skipped")
    monkeypatch.setenv("METADATA_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    # Force re-import of backend.db so the dispatcher re-evaluates
    import importlib
    import backend.db
    importlib.reload(backend.db)
    yield backend

@pytest_asyncio.fixture
async def fresh_db(metadata_backend):
    """Wipe + re-init for each (test, backend) pair."""
    from backend import db
    await db.init() if hasattr(db, "init") else None
    await db.reset_all()
    yield db
```

### Anti-Patterns to Avoid

- **Per-request `METADATA_BACKEND` branching.** D-08 forbids it. Branching once at import is the contract.
- **`from sqlalchemy.orm import ...` in any runtime path.** L-01 / DB-02 forbid ORM at runtime. SQLAlchemy is allowed only inside `migrations/env.py` and `migrations/versions/*.py`.
- **`autogenerate` for the initial migration.** No ORM models exist → `target_metadata=None` → autogenerate would emit empty migrations. Hand-write the 7 `CREATE TABLE` statements with `op.execute()` (or use `op.create_table` Core API — both are fine; both stay out of runtime).
- **Connecting to the Neon `-pooler` endpoint.** Triggers PgBouncer transaction-mode prepared-statement breakage with asyncpg. Use the direct endpoint (no `-pooler` suffix in hostname).
- **Setting `statement_cache_size=0` on the direct endpoint.** Throws away a real perf win for no benefit. Only needed against PgBouncer.
- **Holding a pool connection across an `await` that does I/O outside the DB.** Pool is `max_size=10` — connection starvation is real if request handlers `await` HTTP calls inside `async with pool.acquire()`. Acquire only around DB statements.
- **Forgetting to dispose the alembic engine.** The async template's `await connectable.dispose()` matters when `preDeployCommand` runs in a short-lived container — without it, the container can hang on lingering connections.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema versioning | Custom `_schema_version` table + bespoke migration runner | Alembic | Generates rev IDs, stamps version table, supports up/down, integrates with `op.execute()` for raw SQL |
| Bulk INSERT (1k+ rows from SQLite) | `await conn.execute(INSERT ...)` in a Python loop | `asyncpg.copy_records_to_table` | 10-100× faster than executemany; uses Postgres COPY protocol |
| Connection pooling | Per-request `asyncpg.connect()` | `asyncpg.create_pool` | Spawns one TCP+TLS handshake per request otherwise; pool handles lifecycle, sizing, leak detection |
| TLS with Neon | Custom `ssl.SSLContext` builder | `sslmode=require` URL param OR `ssl='require'` kwarg | asyncpg has built-in libpq-compatible mode; SSLContext only needed for cert pinning we don't do |
| Cold-start mitigation | "Run a query before every request" middleware | 240s `asyncio.create_task` keepalive | Outside request hot path; one connection acquire per 4 min, log line per ping |
| Backend selection at runtime | `if/else` at every db function call site | Module-import-time `from .db_x import *` dispatcher | 23 functions × N call sites = madness; one import-time decision keeps call sites identical to v1.0 |

**Key insight:** Every line of hand-rolled DB infrastructure is a line that has to be debugged at 2am during a public-launch incident. Alembic + asyncpg + Neon is the boring choice on purpose.

## Runtime State Inventory

> Phase 9 is a backend-only metadata cutover. Migrate-once is fully owned by the `sqlite_to_postgres.py` script (D-01). Inventory below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | v1.0 SQLite database at `${DATA_DIR}/newz.db` (default `./data/newz.db` locally; `/data/newz.db` on Railway). 4 tables (clips, clip_embeddings, clusters, segments) + ALTER-added columns (compile_in_flight, last_compile_at, parent_id, start_offset_sec, end_offset_sec, video_url, title). Centroid stored as BLOB (np.float32 bytes). | Run `sqlite_to_postgres.py` once per environment (local dev, Railway prod) BEFORE switching `METADATA_BACKEND=postgres`. Script reads from `DATA_DIR/newz.db`; writes to `DATABASE_URL`. |
| Live service config | None — Neon is provisioned via Neon dashboard manually before this phase ships; DATABASE_URL is set as Railway env var. No live service has the connection string baked into a UI. | Manual one-time: provision Neon project (or branch) → copy direct-endpoint connection string → paste into Railway env var. |
| OS-registered state | None. Backend doesn't register with OS process managers (Railway runs the container). Local dev runs uvicorn directly. | None. |
| Secrets/env vars | New env vars to add: `DATABASE_URL` (sensitive), `METADATA_BACKEND` (default `sqlite`), `KEEPALIVE_INTERVAL_S` (default 240). Existing `OFFLINE_DEMO` from Phase 8 already in `config.py`. | Add to `backend/.env.example`. Add to Railway env vars manually. Confirm `DATABASE_URL` ends up in `requirements-dev.txt` test setup too. |
| Build artifacts / installed packages | None present today. Phase 9 introduces `backend/migrations/__pycache__` and `backend/scripts/__pycache__` after first run. | Add `migrations/__pycache__` and `scripts/__pycache__` to `.gitignore` if not already covered by global pattern. |

**Migration runbook order:** (1) provision Neon, (2) update Railway env vars (DATABASE_URL set, METADATA_BACKEND still `sqlite`), (3) deploy with `preDeployCommand` running `alembic upgrade head` against empty Neon DB, (4) run `sqlite_to_postgres.py` against the deployed Neon DB (one-shot), (5) flip `METADATA_BACKEND=postgres`, (6) redeploy. Step (3) succeeds even with `METADATA_BACKEND=sqlite` because Alembic is independent of the runtime dispatcher.

## Common Pitfalls

### Pitfall 1: Neon `-pooler` endpoint breaks asyncpg prepared statements

**What goes wrong:** If you connect to `ep-xxx-pooler.region.aws.neon.tech` instead of `ep-xxx.region.aws.neon.tech`, asyncpg's default `statement_cache_size=100` triggers `DuplicatePreparedStatementError` and timeouts under load. PgBouncer transaction-mode multiplexes connections and doesn't propagate session-level prepared statements correctly.
**Why it happens:** Two layers of pooling fighting each other (asyncpg's pool + PgBouncer's pool); PgBouncer cycles connections under our prepared statements.
**How to avoid:** Use Neon's **direct** endpoint URL (no `-pooler` suffix). With `--workers 1` and one process-singleton asyncpg pool, we don't need PgBouncer.
**Warning signs:** "prepared statement \"__asyncpg_stmt_xxx\" already exists" errors, intermittent 500s under burst load, asyncpg `InterfaceError`.
**Source:** `[VERIFIED: github.com/MagicStack/asyncpg/issues/1058, supabase/supabase#39227]`

### Pitfall 2: Statutory retention is 1 year, not 90 days (MOD-09 column comment)

**What goes wrong:** Phase 9 lands the `reported_csam.content_preserved_until TIMESTAMPTZ` column. If we comment "90 days per 18 U.S.C. § 2258A" (as REQUIREMENTS.md and CONTEXT.md D-06 currently state), Phase 11's writer will set the wrong retention date. The 2024 REPORT Act amended § 2258A to require **1 year** preservation.
**Why it happens:** REQUIREMENTS.md was drafted against pre-2024 statute language.
**How to avoid:** In the initial migration, write the column comment as `comment='per 18 U.S.C. § 2258A (post-2024 REPORT Act): 1 year preservation'` or omit the duration from the schema entirely (leave to Phase 11's writer + cleanup-job logic). Flag this discrepancy in the PR description so REQUIREMENTS.md/CONTEXT.md get reconciled.
**Warning signs:** None at ship time; this only bites at retention-cleanup time, which is Phase 11's problem. But baking the wrong number now propagates the bug.
**Source:** `[CITED: law.cornell.edu/uscode/text/18/2258A, en.wikipedia.org/wiki/REPORT_Act]`

### Pitfall 3: Railway Procfile `release:` phase is undocumented

**What goes wrong:** D-13's Procfile-with-release approach silently skips the migration on Railway (their migration-from-Heroku doc says "Only a single process is supported for now"). Web container starts against an un-migrated empty Neon DB → every query 500s.
**Why it happens:** Railway's Procfile parser only reads the `web:` line; `release:` is silently ignored.
**How to avoid:** **Use `preDeployCommand` in `railway.json` instead.** Railway's documented pre-deploy feature runs in a separate container, blocks deploy on failure, has access to env vars (DATABASE_URL).
**Warning signs:** Initial deploy looks fine; first request returns "relation does not exist".
**Source:** `[CITED: docs.railway.com/guides/pre-deploy-command, docs.railway.com/migration/migrate-from-heroku, docs.railway.com/reference/config-as-code]`
**Resolution to D-14:** Resolve by switching D-13 from "Procfile `release:`" to "railway.json `preDeployCommand`". Same effect, documented mechanism.

### Pitfall 4: asyncpg URL needs `postgresql://` (not `postgres://`) for SQLAlchemy/Alembic

**What goes wrong:** Neon hands out `postgres://...` URLs. asyncpg accepts both, but Alembic's SQLAlchemy engine config requires `postgresql+asyncpg://...` exactly. Migrations fail with "Could not parse SQLAlchemy URL".
**Why it happens:** SQLAlchemy 2.x removed implicit `postgres://` → `postgresql://` rewriting; explicit driver suffix is required.
**How to avoid:** In `migrations/env.py`, normalize: `db_url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql+asyncpg://", 1).replace("postgresql://", "postgresql+asyncpg://", 1)`. Runtime asyncpg can read `DATABASE_URL` as-is — no rewrite needed for `asyncpg.create_pool(dsn=DATABASE_URL)`.
**Warning signs:** First deploy fails in `preDeployCommand` with SQLAlchemy `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres`.
**Source:** `[VERIFIED: github.com/sqlalchemy/sqlalchemy/issues/6275]`

### Pitfall 5: `tobytes()` round-trip drift between SQLite BLOB and Postgres BYTEA

**What goes wrong:** v1.0 wrote `vec.astype(np.float32).tobytes()` to SQLite BLOB. Postgres BYTEA via asyncpg accepts Python `bytes` natively. **But:** if the migration script reconstructs the bytes via numpy (`np.frombuffer().tobytes()`), endianness or contiguous-array assumptions could change byte layout.
**Why it happens:** numpy arrays can be non-contiguous after slicing; `tobytes()` of a non-contiguous array produces different bytes than the original.
**How to avoid:** Don't reconstruct. Pass the SQLite BLOB column straight through as `bytes`: `pg_conn.copy_records_to_table('clip_embeddings', records=[(r['clip_id'], bytes(r['vector']), r['latency_ms'], r['created_at']) for r in sqlite_rows])`. The `bytes(r['vector'])` defensive cast handles the case where aiosqlite returns `memoryview`. **Verification:** add an assertion in the migration script that loads both sides and `np.array_equal(np.frombuffer(sqlite_blob, dtype=np.float32), np.frombuffer(pg_bytea, dtype=np.float32))` for one row before declaring success.
**Warning signs:** Cluster cosine search returns slightly different results post-migration; CLU-08 calibration test starts failing on previously-passing fixtures.
**Source:** `[VERIFIED: numpy docs on ndarray.tobytes(); asyncpg BYTEA mapping]`

### Pitfall 6: Pool exhaustion under sustained pipeline load (max_size=10)

**What goes wrong:** Pipeline stages (embed, cluster, compile, stitch) run on `asyncio.create_task` and each acquires its own pool connection. Under burst (5 concurrent ingests × ~3 stages each holding a connection while awaiting Marengo HTTP), pool fills, new requests block on `pool.acquire()`, request latency spikes.
**Why it happens:** Connection held across long `await` outside the DB.
**How to avoid:** Acquire only around the DB statement, not around the long-running external call. Pattern:
```python
# BAD — pool starvation:
async with pool.acquire() as conn:
    await conn.execute("UPDATE clips SET embedding_status='in_flight' WHERE id=$1", clip_id)
    vec = await marengo.embed(clip_id)   # 6-second HTTP call holding a connection
    await conn.execute("UPDATE clips SET embedding_status='done' WHERE id=$1", clip_id)
# GOOD — release in between:
async with pool.acquire() as c1:
    await c1.execute("UPDATE clips SET embedding_status='in_flight' WHERE id=$1", clip_id)
vec = await marengo.embed(clip_id)
async with pool.acquire() as c2:
    await c2.execute("UPDATE clips SET embedding_status='done' WHERE id=$1", clip_id)
```
**Warning signs:** `asyncio.TimeoutError` on `pool.acquire()`; request latency p99 spikes under demo load; `prometheus pipeline_stage_duration` histogram shows wide tail.
**How to flag during review:** every `async with pool.acquire()` block should contain only DB statements. Grep for `await ` lines inside `pool.acquire()` blocks; if any await calls a non-DB function, refactor.
**Note for planner:** For Phase 9 itself (which only ports v1.0 SQL with no new long-running awaits), `max_size=10` is plenty. The risk lives in Phase 10/11/12 which add new awaiting work; **document this discipline now** so later phases don't regress it.

### Pitfall 7: Lifespan ordering — pool before CLUSTERS rebuild before keepalive

**What goes wrong:** If `cluster.rebuild_cache()` runs before pool init, it tries to query a None pool and crashes startup. If keepalive task starts before rebuild, the rebuild competes with keepalive for the only-just-created pool's first connection slot.
**Why it happens:** `lifespan` is a coroutine — order matters; `asyncio.create_task` is fire-and-forget.
**How to avoid:** Strict order in `lifespan()`:
1. `await db.init()` (also a no-op for postgres branch — postgres init is the pool itself)
2. `await init_pool()` (postgres only; sqlite branch skips)
3. `await cluster_mod.rebuild_cache()` (now has pool to query)
4. `keepalive_task = asyncio.create_task(_neon_keepalive(_pool))` (postgres only)
5. `asyncio.create_task(_pre_warm_marengo())` and `_pre_warm_sdk()`
6. `yield`

### Pitfall 8: structlog stdlib bridge swallows asyncpg log lines

**What goes wrong:** Phase 8 D-01 routes stdlib logging through structlog's JSONRenderer. asyncpg uses stdlib `logging` (logger name `asyncpg`). If Phase 8's bridge isn't configured to include the `asyncpg` logger, asyncpg's connection-establish + statement-cache-evict messages disappear.
**Why it happens:** structlog ProcessorFormatter only captures loggers that pass through it.
**How to avoid:** Verify `backend/observability/__init__.py` configures the root logger (or explicitly the `asyncpg` and `alembic.runtime.migration` loggers) — Phase 8's setup likely already does this via `dictConfig` root handler. Add an `asyncpg` smoke log line to the parametrized test fixture that asserts JSON output appears in stdout when running against the postgres backend.
**Warning signs:** No "connection established" or "pool: acquired" lines in JSON logs even though queries run successfully.

## Code Examples

### Connecting from a request handler (after pool init)

```python
# backend/db_postgres.py — example function
import asyncpg
from . import config
from .db_postgres_pool import get_pool   # see Pattern 1

async def get_clip(clip_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM clips WHERE id = $1", clip_id)
    return dict(row) if row else None
```

### Multi-statement transaction (ports v1.0 store_embedding)

```python
# Source: https://magicstack.github.io/asyncpg/current/api/index.html
async def store_embedding(clip_id: str, vec: np.ndarray, latency_ms: int) -> None:
    blob = vec.astype(np.float32).tobytes()
    now = time.time()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO clip_embeddings (clip_id, vector, latency_ms, created_at) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (clip_id) DO UPDATE SET "
                "  vector = EXCLUDED.vector, "
                "  latency_ms = EXCLUDED.latency_ms, "
                "  created_at = EXCLUDED.created_at",
                clip_id, blob, latency_ms, now,
            )
            await conn.execute(
                "UPDATE clips SET embedding_status='done', embed_latency_ms=$1 WHERE id=$2",
                latency_ms, clip_id,
            )
```

Note: SQLite `INSERT OR REPLACE` becomes Postgres `INSERT ... ON CONFLICT ... DO UPDATE`. Behavior is equivalent for the `(clip_id)` PK.

### One-shot dump-and-load script skeleton

```python
# backend/scripts/sqlite_to_postgres.py
"""One-shot v1.0 SQLite → Neon Postgres metadata migrator (DB-03 / SC-2).

Usage:
  DATABASE_URL=postgresql://... python -m backend.scripts.sqlite_to_postgres [--force]

Idempotency guard: refuses to run if target Postgres has any rows in clips/embeddings/clusters/segments,
unless --force is passed. SC-2 row-count parity is asserted at the end.
"""
import argparse
import asyncio
import sys
import aiosqlite
import asyncpg

from .. import config

# Tables to copy in FK-safe order. clips before clip_embeddings/clusters; clusters before segments.
# (clips.parent_id self-FK is handled by sorting INSERT batch with parents first.)
TABLES_IN_ORDER = ["clips", "clip_embeddings", "clusters", "segments"]

# Column lists (must match BOTH SQLite schema today AND new Postgres schema; nullable Phase-9-bake-in
# columns are excluded from the copy and left NULL in Postgres).
COLUMNS = {
    "clips": [
        "id", "path", "lat", "lng", "ts", "duration_sec", "embedding_status",
        "embed_latency_ms", "cluster_id", "session_id", "created_at",
        "parent_id", "start_offset_sec", "end_offset_sec",
    ],
    "clip_embeddings": ["clip_id", "vector", "latency_ms", "created_at"],
    "clusters": [
        "id", "centroid", "centroid_lat", "centroid_lng", "median_ts",
        "member_count", "created_at", "updated_at",
        "compile_in_flight", "last_compile_at",
    ],
    "segments": [
        "id", "cluster_id", "ordered_clip_ids", "caption", "location",
        "source_count", "created_at", "video_url", "title",
    ],
}

async def _check_target_empty(pg_conn, force: bool) -> None:
    for tbl in TABLES_IN_ORDER:
        n = await pg_conn.fetchval(f"SELECT count(*) FROM {tbl}")
        if n > 0 and not force:
            raise RuntimeError(
                f"target table {tbl} has {n} rows; pass --force to override"
            )

async def _copy_table(sqlite_conn, pg_conn, tbl: str) -> tuple[int, int]:
    cols = COLUMNS[tbl]
    col_list = ", ".join(cols)
    cur = await sqlite_conn.execute(f"SELECT {col_list} FROM {tbl}")
    rows = await cur.fetchall()
    if not rows:
        return 0, 0
    # Pass-through: aiosqlite Row → tuple; bytes columns (vector, centroid) come through as bytes.
    records = [tuple(r) for r in rows]
    if tbl == "clips":
        # Self-FK on parent_id: insert parents first (parent_id IS NULL), then children.
        parents = [r for r in records if r[cols.index("parent_id")] is None]
        children = [r for r in records if r[cols.index("parent_id")] is not None]
        await pg_conn.copy_records_to_table(tbl, records=parents, columns=cols)
        await pg_conn.copy_records_to_table(tbl, records=children, columns=cols)
    else:
        await pg_conn.copy_records_to_table(tbl, records=records, columns=cols)
    n_pg = await pg_conn.fetchval(f"SELECT count(*) FROM {tbl}")
    return len(records), n_pg

async def main(force: bool) -> int:
    sqlite_path = config.DATA_DIR / "newz.db"
    if not sqlite_path.exists():
        print(f"FATAL: {sqlite_path} not found", file=sys.stderr); return 2
    pg_dsn = config.DATABASE_URL
    if not pg_dsn:
        print("FATAL: DATABASE_URL not set", file=sys.stderr); return 2

    pg_conn = await asyncpg.connect(pg_dsn)
    try:
        await _check_target_empty(pg_conn, force)
        async with aiosqlite.connect(sqlite_path) as sqlite_conn:
            sqlite_conn.row_factory = aiosqlite.Row
            for tbl in TABLES_IN_ORDER:
                n_src, n_dst = await _copy_table(sqlite_conn, pg_conn, tbl)
                print(f"{tbl}: copied {n_src} rows; target now has {n_dst}")
                # SC-2: row-count parity gate
                if n_src != n_dst:
                    raise RuntimeError(f"row-count mismatch on {tbl}: src={n_src}, dst={n_dst}")
    finally:
        await pg_conn.close()
    print("OK: migration complete; SC-2 row-count parity verified")
    return 0

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.force)))
```

### Initial Alembic migration (raw-SQL form, all 7 tables)

```python
# migrations/versions/<rev>_initial_v1_1_schema.py
"""initial v1.1 schema — all 7 tables with FK relations (D-04, Hybrid bake-in)."""
from alembic import op

revision = "<rev>"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # ---- v1.0 tables (lift from db.py SCHEMA_SQL) ----
    op.execute("""
        CREATE TABLE clips (
          id TEXT PRIMARY KEY,
          path TEXT NOT NULL,
          lat DOUBLE PRECISION NOT NULL,
          lng DOUBLE PRECISION NOT NULL,
          ts DOUBLE PRECISION NOT NULL,
          duration_sec DOUBLE PRECISION,
          embedding_status TEXT NOT NULL DEFAULT 'pending',
          embed_latency_ms INTEGER,
          cluster_id TEXT,
          session_id TEXT,
          created_at DOUBLE PRECISION NOT NULL,
          -- v1.0 ALTERs absorbed inline:
          parent_id TEXT REFERENCES clips(id),
          start_offset_sec DOUBLE PRECISION DEFAULT 0,
          end_offset_sec DOUBLE PRECISION,
          -- D-05: nullable feature columns Phase 9 doesn't write but Phase 10/11 will populate without re-ALTERing existing rows:
          blob_url TEXT,
          is_hidden BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX idx_clips_created_at ON clips(created_at)")
    op.execute("CREATE INDEX idx_clips_parent_id ON clips(parent_id)")

    op.execute("""
        CREATE TABLE clip_embeddings (
          clip_id TEXT PRIMARY KEY REFERENCES clips(id),
          vector BYTEA NOT NULL,
          latency_ms DOUBLE PRECISION,
          created_at DOUBLE PRECISION
        )
    """)

    op.execute("""
        CREATE TABLE clusters (
          id TEXT PRIMARY KEY,
          centroid BYTEA,
          centroid_lat DOUBLE PRECISION,
          centroid_lng DOUBLE PRECISION,
          median_ts DOUBLE PRECISION,
          member_count INTEGER NOT NULL DEFAULT 0,
          created_at DOUBLE PRECISION NOT NULL,
          updated_at DOUBLE PRECISION NOT NULL,
          -- v1.0 ALTERs absorbed inline:
          compile_in_flight INTEGER NOT NULL DEFAULT 0,
          last_compile_at DOUBLE PRECISION
        )
    """)

    op.execute("""
        CREATE TABLE segments (
          id TEXT PRIMARY KEY,
          cluster_id TEXT NOT NULL REFERENCES clusters(id),
          ordered_clip_ids TEXT NOT NULL,
          caption TEXT,
          location TEXT,
          source_count INTEGER NOT NULL,
          created_at DOUBLE PRECISION NOT NULL,
          -- v1.0 ALTERs absorbed inline:
          video_url TEXT,
          title TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX idx_segments_cluster_id ON segments(cluster_id)")

    # ---- v1.1 tables (Phase 9 creates, owners populate) ----
    op.execute("""
        CREATE TABLE moderation_decisions (
          -- Phase 11 owns the column shape. Phase 9 lands the table + FK only.
          id TEXT PRIMARY KEY,
          clip_id TEXT NOT NULL REFERENCES clips(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_moderation_decisions_clip_id ON moderation_decisions(clip_id)")

    op.execute("""
        CREATE TABLE reports (
          -- Phase 12 owns the column shape. Phase 9 lands the table + FK only.
          id TEXT PRIMARY KEY,
          segment_id TEXT NOT NULL REFERENCES segments(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_reports_segment_id ON reports(segment_id)")

    op.execute("""
        CREATE TABLE reported_csam (
          -- MOD-09 / 18 U.S.C. § 2258A (post-2024 REPORT Act): 1-year preservation.
          -- WARNING: REQUIREMENTS.md says 90 days; that predates the 2024 amendment.
          -- See research Pitfall 2; reconcile in Phase 11 writer.
          id TEXT PRIMARY KEY,
          content_hash TEXT NOT NULL,
          content_preserved_until TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE UNIQUE INDEX idx_reported_csam_content_hash ON reported_csam(content_hash)")

def downgrade() -> None:
    # Hackathon-grade: no rollback support (D-15). Failed deploy = manual investigation.
    raise NotImplementedError("Phase 9 initial migration is one-way; rollback unsupported (D-15)")
```

### Modified railway.json (D-13 → preDeployCommand)

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "preDeployCommand": ["alembic upgrade head"],
    "startCommand": "uvicorn backend.app:app --host 0.0.0.0 --port $PORT --app-dir .. --workers 1",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 5
  }
}
```

`Procfile` stays as-is (web: only) since `railway.json` startCommand wins; or remove the Procfile entirely to avoid drift between two configs of the same thing. Recommendation: **delete Procfile, source-of-truth in railway.json/railway.toml.**

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| psycopg2 (sync, threadpool-bridged) | asyncpg (native async, binary protocol) | ~2018 (asyncpg matured) | Native async pool, faster binary protocol, idiomatic FastAPI |
| Manual schema versioning (SCHEMA_SQL string + PRAGMA-table_info checks like v1.0 db.py:75-118) | Alembic versioned migrations | Standard since ~2014 | Reversible, one-version-per-PR, no inline ALTER drift |
| Heroku-style Procfile `release:` phase | Railway `preDeployCommand` (railway.json) | Railway diverged from Procfile spec | Documented and supported on Railway; no silent skip |
| pgvector for similarity search | NumPy in-memory cosine over BYTEA | v1.1 explicit deferral (L-03) | Out-of-scope until v1.2+; v1.0 calibration thresholds preserved |
| Per-request `asyncpg.connect()` | Pool initialized once in `lifespan()` | FastAPI 0.93+ lifespan API | One TCP+TLS handshake per process instead of per request |
| Old preservation period (90 days) | 1 year preservation under § 2258A | 2024 REPORT Act amendment | MOD-09 column comments need to track post-2024 statute |

**Deprecated/outdated:**
- **Procfile `release:` phase on Railway** — never supported in the first place; their migration-from-Heroku doc admits "Only a single process is supported."
- **`postgres://` URL scheme in SQLAlchemy 2.x** — must be `postgresql+asyncpg://` for Alembic; runtime asyncpg handles either.
- **Pre-Phase-8 plain-text logging** — replaced by structlog JSON in Phase 8; asyncpg/Alembic logs flow through automatically (Pitfall 8).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Phase 9 will not introduce long-running awaits inside `pool.acquire()` blocks (the v1.0 patterns it ports don't have any) | Pitfall 6 | Pool exhaustion under demo load; fixable post-detection. |
| A2 | The `clusters.compile_in_flight` column shape (INTEGER NOT NULL DEFAULT 0) is the right Postgres analog of the SQLite version | Code Examples §initial migration | Pipeline gate logic in `db.set_compile_in_flight` would behave differently if Postgres treats `INTEGER` arithmetic differently — risk is LOW; semantics identical. |
| A3 | `--workers 1` will hold through v1.1 (no horizontal scale this milestone) | Standard Stack, pool sizing | If multi-worker is ever turned on inside v1.1, 10 connections × N workers could exceed Neon's free-tier connection limit. Locked by L-02; deferred ideas explicitly forbid horizontal scale. |
| A4 | Neon's free-tier scale-to-zero idle threshold remains 5 minutes (DEMO-03 keepalive interval = 240s = 4 min, well under threshold) | Pattern 5 | If Neon shortens idle threshold, keepalive interval needs re-tuning. Verified 2026-04-28 in Neon docs. |
| A5 | The 7 v1.1 tables list (clips, clip_embeddings, clusters, segments, reports, moderation_decisions, reported_csam) is complete; no Phase 10/11/12 surfaces a 8th table | CONTEXT.md D-04 | If Phase 10 (BLOB) needs e.g. a `blob_uploads` audit table, Phase 9's "no CREATE TABLE in 10-12" rule breaks. Verified against REQUIREMENTS.md: BLOB-01..08 all attach to existing clips; MOD-01..10 use moderation_decisions + reported_csam; REPORT-01..10 use reports. No 8th table appears in requirements. |
| A6 | Railway's `preDeployCommand` works with the Dockerfile builder (not just Nixpacks) | Pitfall 3 | If Dockerfile builder skips preDeployCommand, fallback is FastAPI lifespan + `pg_advisory_lock`. **VERIFICATION ACTION FOR PLANNER:** smoke-test by deploying a no-op preDeployCommand (`echo migrate-stub`) before Phase 9 ships and observing build logs show the pre-deploy line. |
| A7 | `aiosqlite.Row['vector']` returns `bytes` (not `memoryview`) on the v1.0 SQLite database | Code Examples §migration script | If memoryview, the `bytes(r['vector'])` defensive cast in `_copy_table` covers it; verified by aiosqlite docs that BLOB cols come back as `bytes`. |

**Resolution status:**
- ✅ D-14 (Procfile release:) — RESOLVED via preDeployCommand path with HIGH confidence; A6 captures one residual risk (Dockerfile-builder compatibility) the planner can confirm in 5 min via test deploy.
- ✅ D-18 (asyncpg + Neon TLS) — RESOLVED with HIGH confidence; both `sslmode=require` URL param and `ssl='require'` kwarg work.

## Open Questions

1. **Does Railway's `preDeployCommand` work with the Dockerfile builder?**
   - What we know: Railway docs document the field but don't explicitly state Dockerfile compatibility. The field exists in railway.json schema universally.
   - What's unclear: Whether the pre-deploy container reuses our Dockerfile or runs in a separate Nixpacks-like environment.
   - Recommendation: Planner adds a wave-0 verification step — push a branch with `preDeployCommand: ["echo PHASE9-PREDEPLOY-PROBE"]` and confirm the line appears in Railway build logs separately from the start command output. ~5 minute task.

2. **Should we explicitly downgrade aiosqlite or pin its version?**
   - What we know: aiosqlite 0.20.0 is in `requirements.txt`; D-09 keeps it indefinitely.
   - What's unclear: Whether running both aiosqlite + asyncpg in the same image triggers any dep conflict.
   - Recommendation: No action; both libraries have minimal transitive deps and don't conflict. Verify via `pip install -r requirements.txt` after adding asyncpg.

3. **What's the right backend selection log line in the dispatcher?**
   - Phase 8 D-12 mandates structlog contextvars are request-scoped. The dispatcher logs at module import — before any request — so it has no contextvars. Keep it as a regular `log.info` with no contextvars binding.
   - Recommendation: log line shape `metadata_backend=postgres` (or `sqlite`) — that's it. Don't bind contextvars at module-import time.

4. **REQUIREMENTS.md / CONTEXT.md says "90 days" for MOD-09 retention — the 2024 REPORT Act amended § 2258A to 1 year.**
   - What we know: HIGH confidence the statute is now 1 year per Cornell LII / REPORT Act Wikipedia.
   - What's unclear: Whether the project deliberately wants 90-day retention as policy (shorter than statutory minimum is **not legal** — must keep AT LEAST 1 year) or whether REQUIREMENTS.md is just stale.
   - Recommendation: Land Phase 9 with the table and column but NO duration encoded in the schema. Phase 11 writer chooses 1 year (or longer). PR description flags the REQUIREMENTS.md update needed. Confirm with user before Phase 11 ships.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | Backend runtime (Dockerfile pin) | ✓ | 3.14.3 locally; Dockerfile uses 3.11 | — |
| asyncpg | DB-01, DB-04, DB-07 | ✗ (not installed) | — (latest 0.31.0 on PyPI) | Add to requirements.txt; install via Dockerfile build |
| alembic | DB-02 | ✗ (not installed) | — (latest 1.18.4 on PyPI) | Add to requirements.txt; install via Dockerfile build |
| aiosqlite | OFFLINE_DEMO + dump-and-load script | ✓ (in requirements.txt 0.20.0) | 0.20.0 | — |
| Neon Postgres project | DB-01, DB-05 | UNKNOWN — needs manual provisioning | — | Provision Neon free-tier project; copy direct-endpoint connection string |
| Railway preDeployCommand support with Docker builder | D-13/D-14 | UNKNOWN — needs verification (A6) | — | If unsupported, fallback is FastAPI-lifespan migration with `pg_advisory_lock` |
| ffmpeg | (carry-forward, not Phase 9) | ✓ | system | — |

**Missing dependencies with no fallback:**
- Neon project provisioning is a manual step the planner must surface as a wave-0 task. Cannot be automated; requires a human to log into neon.tech.

**Missing dependencies with fallback:**
- asyncpg + alembic: trivial pip install, will land in `requirements.txt` change as part of Phase 9.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ (already in `requirements.txt`) |
| Config file | `backend/tests/conftest.py` (exists) — extend with metadata_backend fixture |
| Quick run command | `pytest backend/tests/test_db_postgres.py -x` |
| Full suite command | `pytest backend/tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DB-01 | All metadata reads/writes succeed against Postgres | unit | `pytest backend/tests/test_db_postgres.py -x -k "test_basic_crud"` | ❌ Wave 0 |
| DB-02 | `alembic upgrade head` from empty DB lands all 7 tables | integration | `pytest backend/tests/test_db_migrations.py -x` | ❌ Wave 0 |
| DB-03 | `sqlite_to_postgres.py` row-count parity | integration | `pytest backend/tests/test_sqlite_to_postgres.py -x` | ❌ Wave 0 |
| DB-04 | CLUSTERS rebuilds from Postgres on lifespan startup | integration | `pytest backend/tests/test_cluster_rebuild_postgres.py -x` | ❌ Wave 0 |
| DB-05 | Backend metadata survives "redeploy" (test = restart with same DATABASE_URL) | manual | n/a (deploy-time check) | manual-only |
| DB-06 | Toggling METADATA_BACKEND between sqlite/postgres works in CI | unit | `pytest backend/tests/test_db_dispatcher.py -x` | ❌ Wave 0 |
| DB-07 | Pool max_size=10; saturation degrades gracefully | unit | `pytest backend/tests/test_pool_sizing.py -x` | ❌ Wave 0 |
| MOD-09 | `reported_csam` table exists with correct columns + indexes | integration | `pytest backend/tests/test_db_migrations.py::test_reported_csam_schema -x` | ❌ Wave 0 |
| DEMO-03 | Keepalive task sends `SELECT 1` every 240 s | unit (with mocked sleep) | `pytest backend/tests/test_neon_keepalive.py -x` | ❌ Wave 0 |
| ALL existing v1.0 tests | Pass against both METADATA_BACKEND values (D-10 parametrize) | unit | `pytest backend/tests/test_db_clusters.py backend/tests/test_segments_db.py -x` (run twice via param) | ✅ exist; ❌ parametrize fixture |

### Sampling Rate

- **Per task commit:** `pytest backend/tests/test_db_postgres.py -x` + the parametrized fixture against `test_db_clusters.py` (fast — under 30s with sqlite path; postgres path skips locally without DATABASE_URL).
- **Per wave merge:** Full `pytest backend/tests/ -x` against both backends.
- **Phase gate:** Full suite green against postgres backend (CI runs with DATABASE_URL pointing at ephemeral Neon branch or local Postgres) before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `backend/tests/test_db_postgres.py` — basic CRUD parity tests (DB-01)
- [ ] `backend/tests/test_db_migrations.py` — `alembic upgrade head` from empty + assert 7 tables exist (DB-02, MOD-09)
- [ ] `backend/tests/test_sqlite_to_postgres.py` — load fixture SQLite, run script, assert row counts (DB-03)
- [ ] `backend/tests/test_cluster_rebuild_postgres.py` — populate clusters in Postgres, assert `cluster.rebuild_cache()` repopulates `CLUSTERS` (DB-04)
- [ ] `backend/tests/test_db_dispatcher.py` — flip `METADATA_BACKEND` env, importlib.reload, assert correct module (DB-06, D-11)
- [ ] `backend/tests/test_pool_sizing.py` — saturate 10 connections, assert 11th waits (DB-07)
- [ ] `backend/tests/test_neon_keepalive.py` — mocked event loop ticking, assert `SELECT 1` fires (DEMO-03)
- [ ] `backend/tests/conftest.py` — add `metadata_backend` parametrized fixture + `fresh_db` (D-10)
- [ ] Framework install: `pip install asyncpg==0.31.0 alembic==1.18.4` — add to requirements.txt

## Security Domain

> Phase 9 is a backend metadata-layer cutover; threat surface is narrow but not empty. The MOD-09 `reported_csam` table is the highest-stakes new artifact (statutory).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (deploy-time only) | DATABASE_URL is the only secret; injected via Railway env var; never committed |
| V3 Session Management | no | Anonymity-by-default; no sessions; backend-only phase |
| V4 Access Control | yes | `reported_csam` table is statutory PII — reads and writes restricted to backend (Phase 11). No public endpoint reads from it. |
| V5 Input Validation | yes | All asyncpg parameters use `$1, $2, ...` positional binding — never f-string interpolation. SQL injection is structurally impossible if parameters are correctly bound. |
| V6 Cryptography | yes (TLS in transit) | TLS to Neon is mandatory — `sslmode=require` rejects non-TLS connection attempts. `content_hash` in reported_csam is by definition a hash (never raw content). |
| V8 Data Protection | yes | Centroid BYTEA is opaque to attacker; clip path/lat/lng remain backend-only (PRIV-02 already covers logs); no PII leaks at the schema level. |

### Known Threat Patterns for asyncpg + Neon + Alembic

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via dynamic query construction | Tampering | Always use `$1, $2, ...` positional placeholders with asyncpg; never f-string SQL. Code review checklist item. |
| TLS downgrade attack between backend and Neon | Spoofing | `sslmode=require` (rejects non-TLS); Neon enforces TLS server-side. |
| DATABASE_URL leak via error message / log | Info Disclosure | Never log `DATABASE_URL`. asyncpg connection error messages can include the DSN; catch + redact in `init_pool` exception handler. |
| Unauthorized migration execution | Tampering | Alembic migrations only run via Railway preDeployCommand (deploy pipeline). Local dev uses a separate development DATABASE_URL. |
| Connection-string injection via env var | Tampering | Railway-controlled env vars; not user-supplied. Trust boundary at Railway. |
| Statutory CSAM data exposure (reported_csam) | Info Disclosure | Phase 9 creates the empty table only; Phase 11 owns the writes and access controls. Phase 9 PR review must confirm no admin endpoint reads from `reported_csam`. |

**Phase-9-specific security action items for the planner:**
1. In `init_pool()`, catch `asyncpg.InvalidPasswordError` etc. and emit a sanitized error: `log.error("DB connect failed (DSN redacted)")` — never include the DSN in logs.
2. Confirm `.env.example` has `DATABASE_URL=` (placeholder) so it can't be committed accidentally with a real secret.
3. The migration script (`sqlite_to_postgres.py`) reads DATABASE_URL from env — never accept it as a CLI argument (avoids shell-history capture).
4. No new public endpoint in Phase 9 reads from `reported_csam`.

## Sources

### Primary (HIGH confidence)

- **asyncpg API reference** — https://magicstack.github.io/asyncpg/current/api/index.html — verified `ssl=` parameter accepts True/SSLContext/'require' string; native URL parsing of `sslmode`, `sslcert`, `sslkey`, `sslrootcert`, `sslcrl`; `statement_cache_size` default 100, settable to 0; `copy_records_to_table` API.
- **asyncpg usage docs** — https://magicstack.github.io/asyncpg/current/usage.html — pool, transactions, BYTEA↔bytes auto-conversion.
- **Alembic async env.py template** — https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py — canonical `async_engine_from_config` + `connection.run_sync(do_run_migrations)` pattern.
- **Alembic Cookbook** — https://alembic.sqlalchemy.org/en/latest/cookbook.html — `op.execute()` raw-SQL pattern; offline mode.
- **Railway Pre-Deploy Command** — https://docs.railway.com/guides/pre-deploy-command — separate ephemeral container; failure halts deploy; access to env vars.
- **Railway Config-as-Code reference** — https://docs.railway.com/reference/config-as-code — `preDeployCommand`, `startCommand`, `healthcheckPath`, full schema.
- **Neon Connect from Python** — https://neon.com/docs/guides/python — DATABASE_URL format with `sslmode=require&channel_binding=require`.
- **Neon Connection Pooling** — https://neon.com/docs/connect/connection-pooling — direct vs `-pooler` endpoint; PgBouncer transaction-mode caveats.
- **Neon Scale to Zero** — https://neon.com/docs/introduction/scale-to-zero — 5-minute idle threshold; 300-500ms wake-up.
- **18 U.S.C. § 2258A (current)** — https://www.law.cornell.edu/uscode/text/18/2258A — 1-year preservation post-2024 REPORT Act.
- **REPORT Act (S.474)** — https://www.congress.gov/bill/118th-congress/senate-bill/474/text/rs — strikes "90 days" inserts "1 year".
- **FastAPI Lifespan Discussions** — https://github.com/fastapi/fastapi/discussions/9520 — canonical asyncpg + lifespan pattern.

### Secondary (MEDIUM confidence)

- **asyncpg + pgbouncer issue #1058** — https://github.com/MagicStack/asyncpg/issues/1058 — DuplicatePreparedStatementError reproduction; verifies the Pitfall-1 claim against community evidence.
- **SQLAlchemy URL prefix issue** — https://github.com/sqlalchemy/sqlalchemy/issues/6275 — `postgresql+asyncpg://` requirement.
- **Alembic without ORM discussion** — https://github.com/sqlalchemy/alembic/discussions/1630 — `op.execute()` raw SQL workflow.
- **Bulk insert with asyncpg** — https://schinckel.net/2019/12/13/asyncpg-and-upserting-bulk-data/ — `copy_records_to_table` examples (older but mechanism unchanged).

### Tertiary (LOW confidence — flagged for validation if load-bearing)

- **REPORT Act 90-day → 1-year change Wikipedia** — https://en.wikipedia.org/wiki/REPORT_Act — corroborating the statutory change; LII is the primary source.
- **Neon Postgres review (Mar 2026 Medium)** — https://medium.com/@philmcc/neon-postgres-review-serverless-postgresql-that-actually-scales-to-zero-ee14d4e109ba — community confirmation of scale-to-zero behavior; Neon docs are primary.

## Metadata

**Confidence breakdown:**

- **Standard stack (asyncpg, alembic, aiosqlite):** HIGH — versions verified against PyPI 2026-04-28; APIs verified against magicstack/sqlalchemy docs.
- **Architecture (FastAPI lifespan + module-import dispatcher + Hybrid schema):** HIGH — patterns are canonical; dispatcher style is judgment-call but locked by D-07/D-08.
- **D-14 resolution (Railway preDeployCommand):** HIGH on the existence and shape of `preDeployCommand`; MEDIUM on Dockerfile-builder compatibility (A6 verification still recommended).
- **D-18 resolution (asyncpg TLS):** HIGH — `sslmode=require` URL parsing verified in primary docs.
- **Neon pooler vs direct:** HIGH — direct endpoint is correct for our profile; pooler caveats verified.
- **Pitfalls (statement-cache, URL prefix, BYTEA round-trip, pool exhaustion, lifespan order):** HIGH on each individually; LOW on completeness — there may be additional landmines we'd discover only at execution time.
- **Statutory retention period:** HIGH — § 2258A current text reads 1 year; REPORT Act 2024 verified.
- **Test parametrization fixture:** MEDIUM — pattern is standard but the exact `importlib.reload` dance for re-importing `backend.db` after env-var flip is fragile and may need adjustment per pytest-asyncio version.
- **Pool sizing under sustained load:** LOW — `max_size=10` is locked by L-02 / DB-07 but not load-tested; Pitfall 6 calls this out.

**Research date:** 2026-04-28
**Valid until:** 2026-05-28 (30 days for stable deps; statutory references valid until next REPORT Act amendment).
