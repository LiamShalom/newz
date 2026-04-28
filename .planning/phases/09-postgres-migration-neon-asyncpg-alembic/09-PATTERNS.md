# Phase 9: Postgres Migration (Neon + asyncpg + Alembic) - Pattern Map

**Mapped:** 2026-04-28
**Files analyzed:** 14 (3 NEW + 7 NEW directories/files + 4 MODIFIED + observability inheritance)
**Analogs found:** 13 / 14 (sqlite_to_postgres.py has only the partial smoke_gemini.py analog; Alembic env.py is greenfield — RESEARCH.md template is the canonical pattern)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/db_sqlite.py` (NEW; lift-and-shift) | data-access layer | CRUD | `backend/db.py` (entire file, 710 lines) | **exact — byte-for-byte rename** |
| `backend/db_postgres.py` (NEW) | data-access layer | CRUD | `backend/db.py` (signature parity per D-07) | **exact role + flow, different driver** |
| `backend/db.py` (REPLACED — 8-line dispatcher) | router/dispatcher | module-import branch | `backend/observability/__init__.py` (import-time side-effect dispatcher) + `backend/observability/sentry.py` (empty-env-var graceful skip) | role-match (dispatcher) |
| `backend/config.py` (MODIFIED) | config loader | env-var read | `backend/config.py` lines 35-40 (Phase 8 added LOG_FORMAT/SENTRY_DSN/SENTRY_ENVIRONMENT) | **exact — same file extends itself** |
| `backend/app.py` lifespan (MODIFIED) | lifecycle hook | event-driven (startup/shutdown) | `backend/app.py:67-78` (existing lifespan with `db.init` + `rebuild_cache` + `_pre_warm_*` create_task) | **exact — same function gets one more init step** |
| `backend/migrations/env.py` (NEW) | migration runner | batch (one-shot) | None in repo — RESEARCH.md §Pattern 2 canonical template | **no analog (greenfield)** |
| `backend/migrations/versions/<rev>_initial_v1_1_schema.py` (NEW) | migration script | DDL batch | `backend/db.py` lines 18-63 (SCHEMA_SQL string) + lines 73-119 (PRAGMA migration logic) | **exact — same DDL, different driver/dialect** |
| `backend/scripts/sqlite_to_postgres.py` (NEW) | one-shot utility | batch transform (SQLite → Postgres) | `backend/scripts/smoke_gemini.py` (CLI entry, dotenv loading, `__main__` skeleton) — partial | **role-match (CLI script), not data-flow match** |
| `backend/Procfile` (no longer modified per D-13) | deploy config | — | unchanged | n/a |
| `backend/railway.toml` (MODIFIED) | deploy config | declarative | `backend/railway.toml` lines 5-9 (existing `[deploy]` block) | **exact — same file extends itself** |
| `backend/railway.json` (MODIFIED) | deploy config | declarative | `backend/railway.json` lines 7-12 (existing `deploy` object) | **exact — same file extends itself** |
| `backend/requirements.txt` (MODIFIED) | dependency manifest | — | `backend/requirements.txt` line 6 (`aiosqlite==0.20.0`) + line 18 (`structlog==25.5.0`) | **exact — append two lines** |
| `backend/.env.example` (MODIFIED) | env-var documentation | — | (file is in denied path; mirror via `config.py` additions) | role-match |
| `backend/tests/conftest.py` (NEW) | test fixture | parametrize | `backend/tests/test_db_clusters.py` lines 24-33 (`tmp_db` monkeypatch fixture) + `backend/tests/test_observability_logging.py` lines 14-23 (`json_capture` reload fixture) | **role-match (pytest fixture pattern)** |

---

## Pattern Assignments

### `backend/db_sqlite.py` (data-access layer, CRUD)

**Analog:** `backend/db.py` — **rename, do not modify behavior.**

**Action:** `git mv backend/db.py backend/db_sqlite.py` then add a top-of-file `__all__` list of all 23 public function names (D-07/D-08 require `from .db_sqlite import *` to re-export cleanly). Also re-export module-level `DB_PATH` and `CLIPS_DIR` constants because `backend/app.py:331` reads `db.DB_PATH` directly.

**Imports pattern** (`backend/db.py` lines 1-13 — preserve verbatim):
```python
import json
import logging
import time
import uuid
from pathlib import Path

import aiosqlite
import numpy as np
from fastapi import UploadFile

from . import config

log = logging.getLogger(__name__)

DB_PATH = config.DATA_DIR / "newz.db"
CLIPS_DIR = config.DATA_DIR / "clips"
```

**`__all__` list to add at top:**
```python
__all__ = [
    "DB_PATH", "CLIPS_DIR", "ext_from_mime",
    "init", "insert_clip", "get_clip", "fetch_recent_clips",
    "store_embedding", "get_embedding",
    "get_all_clusters", "upsert_cluster", "assign_clip_to_cluster",
    "insert_segment", "fetch_recent_segments", "get_segment_for_cluster",
    "set_compile_in_flight", "is_compile_in_flight",
    "fetch_cluster_clips", "fetch_cluster_clips_with_children",
    "get_cluster", "count_distinct_parents_in_cluster",
    "insert_child_clip",
    "reset_all", "delete_recent_clips", "get_children_by_parent",
]
```

---

### `backend/db_postgres.py` (data-access layer, CRUD)

**Analog:** `backend/db.py` — port every function with **byte-identical signature** (D-07 contract).

**Driver substitution table (apply per-function):**

| SQLite (db.py) | Postgres (db_postgres.py) |
|----------------|---------------------------|
| `import aiosqlite` | `import asyncpg` |
| `aiosqlite.connect(DB_PATH)` async ctx | `pool.acquire()` async ctx (pool is module-level) |
| `?` placeholders | `$1, $2, ...` placeholders |
| `conn.row_factory = aiosqlite.Row` | (omit — asyncpg `Record` is dict-like) |
| `dict(row)` | `dict(row)` (asyncpg Record supports it) |
| `await conn.execute(sql, tuple)` + `await conn.commit()` | `await conn.execute(sql, *args)` (auto-committed unless inside `conn.transaction()`) |
| `INSERT OR REPLACE INTO ...` | `INSERT ... ON CONFLICT (...) DO UPDATE SET ...` |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `BLOB` (auto bytes) | `BYTEA` (auto bytes; pass through `bytes(...)` defensively for memoryview) |

**Module-level pool pattern** (RESEARCH.md §Pattern 1, lines 207-246 — port verbatim):
```python
import asyncpg
from . import config

_pool: asyncpg.Pool | None = None

def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("asyncpg pool not initialized — lifespan startup must run init_pool() first")
    return _pool

async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=config.DATABASE_URL,    # contains sslmode=require natively (Neon-provided)
        min_size=1,
        max_size=10,                 # L-02 / DB-07
    )

async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

**Per-function port example — `get_clip` (db.py:157-162 → db_postgres.py):**
```python
# Before (db.py lines 157-162):
async def get_clip(clip_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None

# After (db_postgres.py):
async def get_clip(clip_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM clips WHERE id = $1", clip_id)
    return dict(row) if row else None
```

**Per-function port — `store_embedding` (db.py:188-201, multi-statement):**
```python
# Pattern: replace `INSERT OR REPLACE` with ON CONFLICT DO UPDATE; wrap in transaction.
# RESEARCH.md §Code Examples lines 569-594 has the canonical port.
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

**Compile lock CAS port — `set_compile_in_flight` (db.py:383-408):**
```python
# Original SQLite returns `cursor.rowcount == 1`; asyncpg.execute returns the
# command tag string ("UPDATE 1" / "UPDATE 0"). Parse it.
async def set_compile_in_flight(cluster_id: str, value: bool, ttl_seconds: float = 30.0) -> bool:
    now = time.time()
    pool = get_pool()
    async with pool.acquire() as conn:
        if value:
            tag = await conn.execute(
                """UPDATE clusters
                   SET compile_in_flight = 1, last_compile_at = $1
                   WHERE id = $2
                     AND (compile_in_flight = 0 OR last_compile_at < $3)""",
                now, cluster_id, now - ttl_seconds,
            )
            return tag.endswith(" 1")    # "UPDATE 1" -> True; "UPDATE 0" -> False
        else:
            await conn.execute(
                "UPDATE clusters SET compile_in_flight = 0 WHERE id = $1",
                cluster_id,
            )
            return True
```

**`init()` port (db.py:66-120) — must become a no-op for postgres:**
```python
# Postgres schema lives in Alembic migrations (run by Railway preDeployCommand).
# Phase 9 lifespan still calls `await db.init()` — keep the signature, no-op the body.
async def init() -> None:
    # No-op for postgres backend; schema is owned by Alembic migrations.
    log.info("db_postgres.init: noop (schema owned by alembic)")
```

**`reset_all()` port (db.py:571-587):**
```python
# Same DELETE statements; no aiosqlite-specific dependencies.
async def reset_all() -> dict:
    counts = {}
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for tbl in ("clips", "clip_embeddings", "clusters", "segments"):
                counts[tbl] = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
            await conn.execute("DELETE FROM segments")
            await conn.execute("DELETE FROM clip_embeddings")
            await conn.execute("DELETE FROM clips")
            await conn.execute("DELETE FROM clusters")
    return counts
```

**`__all__` list:** identical to `db_sqlite.py` (D-07 contract — every name re-exported).

**Pitfall avoidance** (RESEARCH §Pitfall 6): Audit every function with `pool.acquire()` block to ensure no non-DB `await` lives inside. Phase 9's port has none (every original `db.py` block is DB-only), but document the discipline for Phases 10-12.

---

### `backend/db.py` (router/dispatcher, module-import branch)

**Analog 1:** `backend/observability/__init__.py` (lines 1-17) — module-import-time dispatcher with side effects.
**Analog 2:** `backend/observability/sentry.py` lines 19-27 — empty-env-var graceful skip pattern (D-11 mirror).

**Imports pattern** (mirror observability/__init__.py shape):
```python
"""Phase 9 backend selector — module-import-time dispatch (D-08).

OFFLINE_DEMO=true hard-overrides to SQLite regardless of METADATA_BACKEND (D-11).
Mirrors backend/observability/sentry.py:25 graceful-skip pattern.
"""
import logging
from . import config

log = logging.getLogger(__name__)
```

**Core dispatcher pattern** (RESEARCH §Pattern 3 lines 305-326 — port verbatim):
```python
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

**Pitfall to avoid** (RESEARCH §Anti-Patterns line 434): no per-request branching. The `if` runs once at import time; downstream callers see one of two function tables.

**Note on `app.py:331` — `db.DB_PATH` direct access:**
The existing `/debug/dbstate` endpoint (`app.py:327-350`) reads `db.DB_PATH` directly. Since `db_sqlite.py` re-exports `DB_PATH` and `db_postgres.py` does NOT have a meaningful `DB_PATH`, the postgres branch must export a stub or the debug endpoint must be guarded behind `METADATA_BACKEND=sqlite`. **Planner decision owed:** either guard the endpoint or stub `DB_PATH = None` in `db_postgres.py` and update the endpoint to return 503 when `DB_PATH is None`.

---

### `backend/config.py` (config loader, env-var read)

**Analog:** `backend/config.py` lines 35-40 (Phase 8 additions — same pattern, append).

**Existing pattern** (lines 33-40, copy shape):
```python
# Admin: shared secret guarding /admin/* destructive endpoints.
# Empty value disables the endpoint (returns 503).
ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", "").strip()

# Phase 8: Observability
LOG_FORMAT: str = os.environ.get("LOG_FORMAT", "json").strip().lower()
SENTRY_DSN: str = os.environ.get("SENTRY_DSN", "").strip()
SENTRY_ENVIRONMENT: str = os.environ.get("SENTRY_ENVIRONMENT", "").strip() or "production"
```

**New additions to append** (D-11, D-16, D-17):
```python
# Phase 9: Postgres migration
DATABASE_URL: str = os.environ.get("DATABASE_URL", "").strip()
METADATA_BACKEND: str = os.environ.get("METADATA_BACKEND", "sqlite").strip().lower()
KEEPALIVE_INTERVAL_S: int = int(os.environ.get("KEEPALIVE_INTERVAL_S", "240"))

# OFFLINE_DEMO from Phase 8 (already added) — Phase 9 hard-overrides METADATA_BACKEND when true.
OFFLINE_DEMO: bool = os.environ.get("OFFLINE_DEMO", "false").strip().lower() == "true"
```

**Note:** Verify `OFFLINE_DEMO` was added in Phase 8 already; if not (this CONTEXT does not show it in current config.py), Phase 9 adds it. Check `git log -p backend/config.py` for the Phase 8 changeset.

**Validation pattern** (mirror Phase 8 ADMIN_TOKEN-empty-disables pattern at line 33-35, but **flip polarity** — Phase 9 D-11 "Empty-token-disables-endpoint" comment in CONTEXT.md says Phase 9 is **fail-loud** on missing DATABASE_URL when METADATA_BACKEND=postgres and OFFLINE_DEMO unset. Add a one-time validation at the bottom of config.py or inside `db.py` dispatcher).

---

### `backend/app.py` lifespan (lifecycle hook, event-driven)

**Analog:** `backend/app.py` lines 67-78 (existing lifespan).

**Existing lifespan** (lines 67-78 — **add to**, do not replace):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    # Phase 3: rebuild in-memory cluster cache from sqlite (CLU-10).
    # Must complete before pre-warm task is scheduled so the first clip ingest
    # sees a populated cache.
    from .pipeline import cluster as cluster_mod
    await cluster_mod.rebuild_cache()
    # Fire pre-warms in parallel (Marengo + Claude SDK) — fire-and-forget; never blocks startup
    asyncio.create_task(_pre_warm_marengo())
    asyncio.create_task(_pre_warm_sdk())
    yield
```

**Modified lifespan** (RESEARCH §Pitfall 7 ordering — pool BEFORE rebuild_cache BEFORE keepalive):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 9 (D-16, D-17): asyncpg pool init + Neon keepalive task.
    # Pool MUST init before rebuild_cache (rebuild queries the DB).
    # Skip postgres init when OFFLINE_DEMO=true (D-11) — same shape as Phase 8 sentry skip.
    keepalive_task: asyncio.Task | None = None
    if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO:
        from . import db_postgres
        await db_postgres.init_pool()

    await db.init()    # no-op for postgres; sqlite branch creates schema
    # Phase 3: rebuild in-memory cluster cache (CLU-10) — now reads from whichever backend is active.
    from .pipeline import cluster as cluster_mod
    await cluster_mod.rebuild_cache()

    # Phase 9 (D-17): start keepalive AFTER rebuild_cache so the rebuild gets a clean
    # connection slot first. Cancelled cleanly on shutdown.
    if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO:
        from . import db_postgres
        keepalive_task = asyncio.create_task(_neon_keepalive(db_postgres.get_pool()))

    # Existing pre-warms (unchanged).
    asyncio.create_task(_pre_warm_marengo())
    asyncio.create_task(_pre_warm_sdk())

    try:
        yield
    finally:
        if keepalive_task is not None:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass
        if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO:
            from . import db_postgres
            await db_postgres.close_pool()
```

**Keepalive coroutine** (RESEARCH §Pattern 5 lines 367-394 — port verbatim, place near `_pre_warm_marengo`):
```python
async def _neon_keepalive(pool) -> None:
    """DEMO-03: SELECT 1 every 240s to defeat Neon scale-to-zero (5-min idle threshold)."""
    log = logging.getLogger("backend.keepalive")
    while True:
        try:
            await pool.fetchval("SELECT 1")
            log.info("neon_keepalive ok")
        except Exception as exc:
            log.warning("neon_keepalive failed (non-fatal): %s", exc)
        await asyncio.sleep(config.KEEPALIVE_INTERVAL_S)
```

**Pitfall avoidance** (RESEARCH §Pitfall 7): order is **pool → rebuild_cache → keepalive task → pre-warm tasks → yield**. Do not reorder.

**Pitfall avoidance** (RESEARCH §Pitfall 8): structlog stdlib bridge from Phase 8 routes asyncpg/Alembic logs through JSON automatically — the existing `dictConfig` root handler in `observability/logging_config.py:100-107` covers all loggers via the empty-string root. No extra wiring needed.

---

### `backend/migrations/env.py` (migration runner, batch)

**Analog:** None in repo. Use RESEARCH.md §Pattern 2 lines 254-302 verbatim.

**Critical normalization** (RESEARCH §Pitfall 4 — port verbatim, prevents `NoSuchModuleError`):
```python
# Neon hands out postgres:// URLs; SQLAlchemy 2.x demands postgresql+asyncpg://
db_url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql+asyncpg://", 1)
db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1) if not db_url.startswith("postgresql+asyncpg://") else db_url
config.set_main_option("sqlalchemy.url", db_url)
```

**Required boilerplate** (RESEARCH lines 260-302 — copy verbatim):
- `target_metadata = None` (no ORM models; raw SQL via `op.execute()`)
- `async_engine_from_config(..., poolclass=pool.NullPool)` (one-shot; preDeployCommand container is short-lived — RESEARCH §Anti-Patterns line 440 warns about lingering connections)
- `await connectable.dispose()` after migration
- `if context.is_offline_mode(): raise RuntimeError(...)` — Phase 9 always runs against live Neon

---

### `backend/migrations/versions/<rev>_initial_v1_1_schema.py` (migration script, DDL batch)

**Analog:** `backend/db.py` lines 18-63 (`SCHEMA_SQL` string).

**Source DDL to translate** (db.py:18-63):
```sql
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL DEFAULT 'pending',
  embed_latency_ms INTEGER,
  cluster_id TEXT,
  session_id TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at);
-- + clip_embeddings, clusters, segments (lines 34-62)
```

**Plus the v1.0 ALTERs absorbed inline** (db.py lines 73-118) — `compile_in_flight`, `last_compile_at`, `parent_id`, `start_offset_sec`, `end_offset_sec`, `video_url`, `title`.

**Translation rules (SQLite → Postgres):**
| SQLite | Postgres |
|--------|----------|
| `REAL` | `DOUBLE PRECISION` |
| `INTEGER` (boolean-like, e.g., `compile_in_flight`) | keep `INTEGER NOT NULL DEFAULT 0` (A2 in RESEARCH assumptions log — semantics identical) |
| `BLOB` | `BYTEA` |
| `CREATE TABLE IF NOT EXISTS` | `CREATE TABLE` (Alembic migration is idempotent at the version-table level, not statement level) |
| `CREATE INDEX IF NOT EXISTS` | `CREATE INDEX` |

**Full migration body:** RESEARCH §Code Examples lines 700-815 has the entire `upgrade()` function ready to copy. Includes:
- 4 v1.0 tables (`clips`, `clip_embeddings`, `clusters`, `segments`) with v1.0 ALTERs absorbed inline
- 3 v1.1 tables (`moderation_decisions`, `reports`, `reported_csam`) with FK to existing tables
- `clips.blob_url TEXT` (nullable; D-05 — Phase 10 populates without re-ALTER)
- `clips.is_hidden BOOLEAN NOT NULL DEFAULT FALSE` (nullable; D-05 — Phase 11)
- `reported_csam.content_hash TEXT NOT NULL` + `content_preserved_until TIMESTAMPTZ NOT NULL` (D-06; statutory)
- All FK relations declared (D-04)
- All indexes including `UNIQUE INDEX idx_segments_cluster_id` (mirrors db.py:104-106)

**Downgrade:** `raise NotImplementedError("Phase 9 initial migration is one-way; rollback unsupported (D-15)")` per D-15 hackathon-grade.

**Pitfall avoidance** (RESEARCH §Pitfall 2): Do **NOT** comment "90 days" on `reported_csam.content_preserved_until`. Either omit the duration entirely (Phase 11 chooses) or comment "1 year per 18 U.S.C. § 2258A (post-2024 REPORT Act)". REQUIREMENTS.md is stale.

---

### `backend/scripts/sqlite_to_postgres.py` (one-shot utility, batch transform)

**Analog (partial):** `backend/scripts/smoke_gemini.py` — for CLI entry shape, dotenv loading, `if __name__ == "__main__":` block.

**Imports + dotenv pattern** (smoke_gemini.py lines 1-26 — adapt):
```python
"""One-shot v1.0 SQLite → Neon Postgres metadata migrator (DB-03 / SC-2).

Usage:
  DATABASE_URL=postgresql://... python -m backend.scripts.sqlite_to_postgres [--force]
"""
import argparse
import asyncio
import sys

import aiosqlite
import asyncpg

from .. import config
```

**Idempotency guard pattern** (smoke_gemini.py:30-32 fail-fast on missing key — mirror for missing DATABASE_URL + non-empty target):
```python
async def _check_target_empty(pg_conn, force: bool) -> None:
    for tbl in TABLES_IN_ORDER:
        n = await pg_conn.fetchval(f"SELECT count(*) FROM {tbl}")
        if n > 0 and not force:
            raise RuntimeError(f"target table {tbl} has {n} rows; pass --force to override")
```

**Core copy pattern** (RESEARCH §Pattern 4 lines 330-360 + §Code Examples lines 596-697 — full skeleton):
```python
TABLES_IN_ORDER = ["clips", "clip_embeddings", "clusters", "segments"]

COLUMNS = {
    "clips": ["id", "path", "lat", "lng", "ts", "duration_sec",
              "embedding_status", "embed_latency_ms", "cluster_id",
              "session_id", "created_at",
              "parent_id", "start_offset_sec", "end_offset_sec"],
    "clip_embeddings": ["clip_id", "vector", "latency_ms", "created_at"],
    "clusters": ["id", "centroid", "centroid_lat", "centroid_lng", "median_ts",
                 "member_count", "created_at", "updated_at",
                 "compile_in_flight", "last_compile_at"],
    "segments": ["id", "cluster_id", "ordered_clip_ids", "caption", "location",
                 "source_count", "created_at", "video_url", "title"],
}

async def _copy_table(sqlite_conn, pg_conn, tbl: str) -> tuple[int, int]:
    cols = COLUMNS[tbl]
    col_list = ", ".join(cols)
    cur = await sqlite_conn.execute(f"SELECT {col_list} FROM {tbl}")
    rows = await cur.fetchall()
    if not rows:
        return 0, 0
    records = [tuple(r) for r in rows]
    if tbl == "clips":
        # Self-FK on parent_id: parents first, children second.
        parents = [r for r in records if r[cols.index("parent_id")] is None]
        children = [r for r in records if r[cols.index("parent_id")] is not None]
        await pg_conn.copy_records_to_table(tbl, records=parents, columns=cols)
        await pg_conn.copy_records_to_table(tbl, records=children, columns=cols)
    else:
        await pg_conn.copy_records_to_table(tbl, records=records, columns=cols)
    n_pg = await pg_conn.fetchval(f"SELECT count(*) FROM {tbl}")
    return len(records), n_pg
```

**Pitfall avoidance** (RESEARCH §Pitfall 5): For `clip_embeddings.vector` and `clusters.centroid` columns, pass the SQLite BLOB straight through as `bytes` — do NOT reconstruct via numpy. Defensive: `bytes(r['vector'])` to handle memoryview from aiosqlite. Add a one-row `np.array_equal` assertion as an SC-2 verification gate.

**SC-2 success gate** (RESEARCH lines 685-689):
```python
if n_src != n_dst:
    raise RuntimeError(f"row-count mismatch on {tbl}: src={n_src}, dst={n_dst}")
```

**`__main__` block** (smoke_gemini.py:108-109 pattern):
```python
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.force)))
```

---

### `backend/railway.toml` + `backend/railway.json` (deploy config)

**Analog:** `backend/railway.toml` lines 5-9 (existing `[deploy]` block) + `backend/railway.json` lines 7-12 (existing `deploy` object).

**Existing railway.toml `[deploy]` block** (lines 5-9 — extend in place):
```toml
[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
```

**Add per D-13 (CORRECTED — preDeployCommand, NOT Procfile release:):**
```toml
[deploy]
preDeployCommand = ["alembic", "upgrade", "head"]
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
```

**Mirror in railway.json** (RESEARCH §Code Examples lines 818-836):
```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "preDeployCommand": ["alembic upgrade head"],
    "healthcheckPath": "/health",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 5
  }
}
```

**Pre-planning smoke owed** (D-14 / RESEARCH §A6): Plan must include a wave-0 task to push `preDeployCommand: ["echo PHASE9-PREDEPLOY-PROBE"]` and verify Railway logs show the line in a separate pre-deploy container before committing to the real `alembic upgrade head` call. ~5-min task.

**Procfile** (D-13 correction): Per RESEARCH line 838, recommendation is to **leave `Procfile` as-is (web: only)** — the railway.json/toml startCommand is the documented source of truth. **Do not** add a `release:` line.

---

### `backend/requirements.txt` (dependency manifest)

**Analog:** `backend/requirements.txt` line 6 (`aiosqlite==0.20.0`) — exact-pinned async DB driver line. Mirror the format.

**Existing pinning style:**
```
aiosqlite==0.20.0
structlog==25.5.0
sentry-sdk[fastapi]==2.53.0
prometheus-client==0.25.0
```

**Append (D-19, RESEARCH §Standard Stack):**
```
asyncpg==0.31.0
alembic==1.18.4
```

**Verification command** (RESEARCH lines 126-129 — run before locking versions in PLAN.md):
```bash
pip3 index versions asyncpg | head -3
pip3 index versions alembic | head -3
```

---

### `backend/.env.example` (env-var documentation)

**Analog:** `backend/config.py` lines 7-40 (env var names defined here are the contract; .env.example mirrors them).

**New entries to add** (mirror config.py additions above):
```
# Phase 9: Postgres migration
DATABASE_URL=
METADATA_BACKEND=sqlite
KEEPALIVE_INTERVAL_S=240

# Phase 8 (Phase 9 hard-overrides METADATA_BACKEND when true):
OFFLINE_DEMO=false
```

**Note:** This file is in a denied path; its current contents could not be read. Planner must use existing `config.py` defaults (line 38: `LOG_FORMAT="json"`, line 39: `SENTRY_DSN=""`, line 40: `SENTRY_ENVIRONMENT="production"`) as the precedent for variable-format style and grouping comments.

---

### `backend/tests/conftest.py` (test fixture, parametrize)

**Analog 1:** `backend/tests/test_db_clusters.py` lines 24-33 — `tmp_db` monkeypatch fixture for DB_PATH/DATA_DIR.
**Analog 2:** `backend/tests/test_observability_logging.py` lines 14-23 — `json_capture` monkeypatch + reload fixture.
**Analog 3:** `backend/tests/test_observability_sentry.py` lines 26-32 — monkeypatch + module re-import pattern.

**Existing tmp_db pattern** (test_db_clusters.py lines 24-33 — copy shape):
```python
@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH and DATA_DIR at a temporary directory; init the schema."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    new_db_path = tmp_path / "newz.db"
    monkeypatch.setattr(db, "DB_PATH", new_db_path)
    monkeypatch.setattr(db, "CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    await db.init()
    return tmp_path
```

**New METADATA_BACKEND parametrize fixture** (RESEARCH §Pattern 6 lines 396-430 — port verbatim into new conftest.py):
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
    # Force re-import of backend.db so the dispatcher re-evaluates (mirrors
    # test_observability_sentry.py module-reimport pattern).
    import importlib
    import backend.config
    import backend.db
    importlib.reload(backend.config)
    importlib.reload(backend.db)
    yield backend


@pytest_asyncio.fixture
async def fresh_db(metadata_backend):
    """Wipe + re-init for each (test, backend) pair."""
    from backend import db
    if hasattr(db, "init"):
        await db.init()
    if hasattr(db, "reset_all"):
        await db.reset_all()
    yield db
```

**Risk to plan for** (RESEARCH §Pattern 6 caveat): The existing `tmp_db` fixture in `test_db_clusters.py` and others uses `monkeypatch.setattr(db, "DB_PATH", ...)` — this only works for the SQLite branch. Tests that use `tmp_db` directly (not the new `metadata_backend`) must be left as-is (SQLite-only). Tests intended to validate parity should use the new `fresh_db` fixture, requiring the planner to enumerate which existing tests opt-in.

---

## Shared Patterns

### Pattern A: Module-import-time graceful skip on empty env var
**Source:** `backend/observability/sentry.py:25-26`
**Apply to:** `backend/db.py` dispatcher (D-11 OFFLINE_DEMO override)
```python
if not config.SENTRY_DSN:
    logging.getLogger(__name__).info("sentry skipped: SENTRY_DSN unset")
    return
```
This is the pattern Phase 9 D-11 mirrors verbatim — empty/false env var → no-op + log line, never raise.

### Pattern B: Module-level singleton with lifespan init/teardown
**Source:** `backend/app.py:32-46` (`_pre_warm_marengo`) — module-level coroutine fired by lifespan via `asyncio.create_task`; `try/except` wraps fail-soft behavior.
**Apply to:** `db_postgres.py` `_pool` global + `init_pool()`/`close_pool()` (RESEARCH §Pattern 1).
**Note:** `_pool` is **fail-loud** on bad DATABASE_URL — Phase 9 does not graceful-degrade postgres connection failures (RESEARCH §User Constraints — "fail-loud on missing DATABASE_URL").

### Pattern C: structlog stdlib bridge auto-routes new logger names
**Source:** `backend/observability/logging_config.py:100-107` — `dictConfig` empty-string root logger captures all stdlib loggers (`asyncpg`, `alembic.runtime.migration`, `backend.keepalive`).
**Apply to:** All new code in Phase 9 — use `logging.getLogger(__name__)` and JSON output is automatic. No structlog-specific imports needed.
**Risk** (RESEARCH §Pitfall 8): if asyncpg log lines do not appear in JSON output during smoke tests, verify the `disable_existing_loggers: False` setting at line 70 wasn't inadvertently changed.

### Pattern D: Constant-time admin token + 503-on-empty
**Source:** `backend/app.py:392-397` (`/admin/reset` auth) + `backend/observability/metrics.py:131-140` (`/metrics` auth).
**Apply to:** N/A in Phase 9 (no new admin endpoints), but **document the invariant** for Phase 12's `/admin/reports` endpoint (REPORT-04 from forward-looking spec).

### Pattern E: `from . import config` at module top
**Source:** Every backend module — `backend/db.py:11`, `backend/app.py:23`, `backend/observability/sentry.py:16`, `backend/pipeline/embed.py:27`.
**Apply to:** `backend/db_sqlite.py`, `backend/db_postgres.py`, `backend/scripts/sqlite_to_postgres.py`, `backend/migrations/env.py`.

### Pattern F: `monkeypatch.setattr(config, ...)` in fixtures
**Source:** `backend/tests/test_db_clusters.py:27`, `backend/tests/test_observability_sentry.py:28`, `backend/tests/test_observability_logging.py:16`.
**Apply to:** `backend/tests/conftest.py` `metadata_backend` fixture — but use `monkeypatch.setenv(...)` instead of `setattr(config, ...)` because `METADATA_BACKEND` is read at module import (`config.METADATA_BACKEND` is a module-level constant, not a runtime lookup), so the test must set the env var **then re-import** `config` and `db` modules. RESEARCH §Pattern 6 captures this; `test_observability_sentry.py:30` is the closest in-repo precedent for the re-import idiom.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/migrations/env.py` | migration runner | batch | Greenfield — no Alembic in v1.0. RESEARCH §Pattern 2 lines 254-302 is the canonical async template; Pitfall 4 normalization is mandatory. |

(All other files have at least one role-match analog in-repo.)

---

## Metadata

**Analog search scope:** `backend/`, `backend/observability/`, `backend/scripts/`, `backend/tests/`, `backend/pipeline/cluster.py` (rebuild_cache reference).
**Files scanned:** 18 source files + 5 config/deploy files.
**Pattern extraction date:** 2026-04-28.
**Key cross-cutting reference:** RESEARCH.md §"Code Examples" (lines 553-836) contains canonical full-file templates for the 4 greenfield files (env.py, initial migration, sqlite_to_postgres.py, modified railway.json) — planner should treat those as authoritative when analogs are insufficient.
