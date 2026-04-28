# Phase 9: Postgres Migration (Neon + asyncpg + Alembic) - Context

**Gathered:** 2026-04-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace SQLite-on-volume with managed Postgres (Neon) for all backend metadata. Bake the v1.1 table graph (with FK relations) into the initial Alembic migration so Phases 10-12 only do `ALTER ADD COLUMN`. Gate the cutover behind `METADATA_BACKEND` for migration-window rollback. Ship a one-shot dump-and-load script for v1.0 SQLite → Neon migration.

**In scope (from REQUIREMENTS.md):**
- asyncpg + Alembic-async runtime against Neon (DB-01, DB-02)
- One-shot SQLite→Postgres dump-and-load utility (DB-03)
- `CLUSTERS` in-memory cache rebuild from Postgres on startup (DB-04)
- Railway redeploy survival (DB-05)
- `METADATA_BACKEND` runtime feature flag for SQLite rollback (DB-06)
- Connection pool sized for `--workers 1`, `max_size=10` (DB-07)
- `reported_csam` table with `content_hash` and `content_preserved_until TIMESTAMPTZ` columns (MOD-09 statutory; populated by Phase 11)
- Neon keepalive `SELECT 1` every 4 minutes (DEMO-03)

**Out of scope (deferred):**
- Vercel Blob migration — Phase 10 (clip media still served from local FS in Phase 9)
- Inline moderation classifier wiring + reported_csam writes — Phase 11
- Reports table writes / admin queue — Phase 12
- pgvector centroid storage — v1.2+ (BYTEA round-trip locked for v1.1)
- SQLAlchemy ORM at runtime — explicitly forbidden, Alembic uses SQLAlchemy core for migrations only
- Per-pod migration locking — single-pod Railway deploy is the assumption (`--workers 1` Procfile pin holds)

</domain>

<decisions>
## Implementation Decisions

### Inherited (locked elsewhere; do NOT re-litigate)
- **L-01:** Neon Postgres provider, asyncpg driver, Alembic async migrations, no SQLAlchemy ORM at runtime — STATE.md `Locked Decisions`.
- **L-02:** Connection pool `max_size=10`, `--workers 1` Procfile pin — STATE.md `Locked Decisions`, REQ-DB-07.
- **L-03:** Centroid storage = BYTEA, identical bytes round-trip from v1.0 BLOB. **No pgvector** in v1.1 — STATE.md `Locked Decisions`. NumPy in-memory cosine continues to be the search path.
- **L-04:** structlog JSON via stdlib bridge from Phase 8 D-01. New asyncpg/Alembic logging emits JSON with no per-call-site changes.
- **L-05:** session_hash = constant sha256 (Phase 8 D-06). Any DB lookup that joins on session identifier must compare against the same constant hash, NOT the daily-rotated REPORT-03 HMAC.

### Cutover strategy (implicit per SC-2)
- **D-01:** One-shot dump-and-load script at `backend/scripts/sqlite_to_postgres.py`. Run manually before deploy. SC-2 success = `SELECT count(*)` matches across `clips`, `clip_embeddings`, `clusters`, `segments` between source SQLite and target Postgres.
- **D-02:** No dual-write window. v1.0 demo data is migrated once; downstream phases don't dual-source.

### Schema bake-in scope (Hybrid)
- **D-03:** **Hybrid bake-in**: All 7 v1.1 tables exist in the initial Alembic migration with FK relations declared, but only the columns Phase 9 actually writes are populated initially. Future-feature columns get added by their owning phases via `ALTER ADD COLUMN`.
- **D-04:** **All 7 tables in initial migration:** `clips`, `clip_embeddings`, `clusters`, `segments`, `reports`, `moderation_decisions`, `reported_csam`. FK relations (e.g., `reports.clip_id → clips.id`, `moderation_decisions.clip_id → clips.id`) declared in initial migration. Phases 10-12 do `ALTER ADD COLUMN` only — never `CREATE TABLE`.
- **D-05:** **Soft deviation from phase goal language:** Phase goal text says "full v1.1 schema (moderation columns, blob_url, is_hidden, ...) baked into the initial migration." User chose Hybrid (tables now, feature-phase columns later). Reconciliation: tables ARE baked in (D-04), but the feature columns ride with their owner phases. Initial migration must include columns Phase 9 itself uses on `clips` (v1.0 columns + nullable `blob_url` + nullable `is_hidden` so Phase 10/11 don't need to ALTER existing rows).
- **D-06:** **`reported_csam` is statutory and lands in Phase 9** — `content_hash TEXT` + `content_preserved_until TIMESTAMPTZ` columns per MOD-09 / 18 U.S.C. § 2258A. Phase 9 creates the table and columns; Phase 11 wires the writes.

### METADATA_BACKEND dispatcher structure
- **D-07:** **Module split**: replace `backend/db.py` with a thin selector. `db_sqlite.py` is a lift-and-shift of the current code (23 functions, 710 lines). `db_postgres.py` is the asyncpg implementation with **identical function signatures**. Public-API contract: `from backend.db import insert_clip, get_clip, ...` continues to work — selector re-exports based on `config.METADATA_BACKEND`.
- **D-08:** Selection happens **once at module import**. No per-request branching. `backend/db.py` becomes:
  ```python
  if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO:
      from .db_postgres import *
  else:
      from .db_sqlite import *
  ```
- **D-09:** `db_sqlite.py` is **kept after migration window** for OFFLINE_DEMO fallback. It is NOT deleted at the end of v1.1. The deletion question lives in v1.2 scope.
- **D-10:** Test discipline: every existing `backend/tests/test_*` that exercises db functions runs **against both backends** in CI for the duration of v1.1. Implementation: parametrize `METADATA_BACKEND` env var via a fixture; tests run twice. Phase 9 ships this fixture.

### OFFLINE_DEMO + METADATA_BACKEND interaction (matches Phase 8 D-16)
- **D-11:** **`OFFLINE_DEMO=true` hard-overrides to SQLite** regardless of `METADATA_BACKEND` value. Logged once at startup: `metadata_backend: forcing sqlite (OFFLINE_DEMO=true)`. Matches Phase 8 D-16 graceful-degrade pattern (empty `SENTRY_DSN` → skip Sentry init regardless).
- **D-12:** Firewalled CI smoke test (DEMO-02, owned by Phase 13) sets `OFFLINE_DEMO=true` only — Phase 9 must guarantee that startup never opens a Neon connection under that flag.

### Alembic upgrade timing
- **D-13:** **Procfile `release:` phase** runs `alembic upgrade head` exactly once per deploy in a separate container before web start. Procfile becomes:
  ```
  release: alembic upgrade head
  web: uvicorn backend.app:app --host 0.0.0.0 --port $PORT --app-dir ..
  ```
- **D-14:** **Verify Railway honors the `release:` phase** — current `backend/Procfile` only declares `web:`. Planner must confirm `release:` phase fires on Railway (Heroku-compatible Procfile spec); if not supported, fallback is FastAPI lifespan with `pg_advisory_lock(deploy_lock_id)` (Option B from discuss). Document the verification step in PLAN.md as a pre-implementation check.
- **D-15:** No automatic rollback on migration failure — failed `alembic upgrade head` fails the deploy; web container never starts. Acceptable for hackathon-grade.

### Connection pool & Neon keepalive
- **D-16:** asyncpg pool initialized in FastAPI `lifespan()` startup hook (eager, fail-loud). Closed in `lifespan()` shutdown. Single module-level pool, `max_size=10` per L-02.
- **D-17:** Neon keepalive (DEMO-03 / SC-5): `asyncio.create_task` in `lifespan()` startup that loops `await pool.fetchval("SELECT 1")` every 240 seconds. Cancelled cleanly on shutdown. Logger emits one INFO line per ping (request_id absent — keepalive runs outside any request scope).
- **D-18:** TLS: asyncpg uses `ssl='require'` (not libpq-style `sslmode=require`). Connection string from `DATABASE_URL` env var (Neon-provided). **Pre-planning verification owed**: STATE.md "Pending Todos" → "Confirm asyncpg + Neon TLS / `sslmode=require` interaction before Phase 9 cutover." Planner should run a one-line connection probe before locking the connection-string format.

### Claude's Discretion (locked-in defaults the planner can act on)
- **D-19:** Alembic env.py async config is implementation detail (planner choice). Standard pattern: `async_engine_from_config` + `connection.run_sync(do_run_migrations)`. No need to discuss with user.
- **D-20:** SQLite→Postgres dump-and-load script reads SQLite via `aiosqlite` and writes Postgres via `asyncpg.copy_records_to_table` for bulk speed. Centroid bytes copied verbatim (BLOB → BYTEA). Idempotency: script is one-shot; running twice should error or be guarded by an empty-target check. Planner picks.
- **D-21:** `CLUSTERS` cache rebuild on startup (DB-04): port the existing `rebuild_cache_from_db()` logic from `db_sqlite.py` to `db_postgres.py` with identical signature. Fetch-all is fine at hackathon scale.
- **D-22:** Migration version naming: standard Alembic timestamp prefix. Phase 9's initial migration name: something like `xxx_initial_v1_1_schema.py`. Planner picks the prefix style.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and acceptance criteria
- `.planning/ROADMAP.md` §"Phase 9: Postgres Migration (Neon + asyncpg + Alembic)" — phase goal, depends-on (Phase 8), 5 success criteria
- `.planning/REQUIREMENTS.md` §"Database — Postgres Migration" (DB-01..07) — Neon, asyncpg, Alembic async, no SQLAlchemy ORM, dump-and-load, CLUSTERS rebuild, redeploy survival, feature flag, pool sizing
- `.planning/REQUIREMENTS.md` §"Moderation Gate" (MOD-09 only) — `reported_csam` table schema landing in Phase 9 per statutory requirement
- `.planning/REQUIREMENTS.md` §"OFFLINE_DEMO" (DEMO-03) — Neon `SELECT 1` keepalive every 4 minutes

### Project-level constraints (cross-phase)
- `.planning/PROJECT.md` §"Constraints" — anonymity is load-bearing, single Uvicorn worker, OFFLINE_DEMO must work end-to-end
- `.planning/STATE.md` §"Locked Decisions" — Neon over Supabase, asyncpg + Alembic no SQLAlchemy ORM, BYTEA centroids no pgvector, METADATA_BACKEND flag, max_size=10, --workers 1, OFFLINE_DEMO firewalled CI gate
- `.planning/STATE.md` §"Pending Todos" — "Confirm asyncpg + Neon TLS / sslmode=require interaction before Phase 9 cutover" (D-18)

### Phase 8 inheritance (must not regress)
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-01 — structlog stdlib bridge (asyncpg/Alembic logs route through structlog automatically)
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-06, D-07 — session_hash = constant sha256, NOT daily-rotated HMAC (explicit divergence from Phase 12's REPORT-03 IP hash)
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-12 — middleware order (XFFStrip → RequestID → CORS → routes); Phase 9 changes nothing here
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-16 — empty `SENTRY_DSN` skips Sentry init; Phase 9 D-11 mirrors this pattern for OFFLINE_DEMO+Postgres
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-17 — Prometheus label policy (no clip_id/session_uuid/raw GPS as labels). Phase 9 must not add Postgres-specific high-cardinality labels (e.g., `query_text`).

### v1.0 architecture being replaced (read for migration scope)
- `backend/db.py` — current SQLite layer, 710 lines, 23 async functions, all using `aiosqlite.connect(DB_PATH)` per call. **This file is the lift-and-shift target for `db_sqlite.py`** (D-07). Preserve every function signature exactly.
- `backend/config.py` — env-var loading via `python-dotenv`. New env vars (`DATABASE_URL`, `METADATA_BACKEND`) belong here. Phase 8 already added `LOG_FORMAT`/`SENTRY_DSN`/`OFFLINE_DEMO` here.
- `backend/app.py` — `lifespan()` startup hook is where the asyncpg pool init + Neon keepalive task launch (D-16, D-17).
- `backend/Procfile` — currently has only `web:`. Phase 9 adds `release:` line (D-13). Verify Railway honors it (D-14).
- `backend/railway.toml` and `backend/railway.json` — current Railway config; Procfile changes may need a config sync.

### Forward-looking (do NOT implement now, but plan for)
- Phase 10 (BLOB-01..08) ALTERs `clips` to populate `blob_url` and `is_hidden` columns Phase 9 created as nullable. Migration name pattern: keep stable so 10-12's migrations stack cleanly.
- Phase 11 (MOD-01..08, MOD-10, PRIV-03) writes to `reported_csam` (created in Phase 9 D-06), `moderation_decisions` (table created in Phase 9, columns added in Phase 11).
- Phase 12 (REPORT-01..10, PRIV-04) writes to `reports` (table created in Phase 9, columns added in Phase 12). REPORT-03 daily-rotated HMAC for `reporter_ip_hash` is **explicitly different** from session_hash (Phase 8 D-07).
- Phase 13 (DEMO-02) firewalled CI smoke test depends on Phase 9 D-11 OFFLINE_DEMO override working.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`backend/db.py`** (710 lines, 23 async functions): All using `aiosqlite.connect(DB_PATH)` + `conn.row_factory = aiosqlite.Row` pattern. Lift-and-shift to `db_sqlite.py` preserves function signatures. asyncpg port to `db_postgres.py` mirrors signatures with `pool.acquire()` + `record._mapping` (or `dict(record)`) for row access.
- **`backend/config.py`**: env-var loader via `python-dotenv`. Phase 9 adds `DATABASE_URL`, `METADATA_BACKEND` (default `sqlite`), keepalive interval constant.
- **`lifespan()` startup hook** (`backend/app.py:58-69` per Phase 8 CONTEXT): Where the asyncpg pool init and `SELECT 1` keepalive `asyncio.create_task` belong (D-16, D-17). Same pattern Phase 8 used for Sentry init.

### Established Patterns
- **Single-worker asyncio**: `--workers 1` is locked. Means asyncpg pool is process-singleton; no inter-process pool coordination needed. Migration concurrency safety is single-pod-only (D-13 `release:` phase reinforces this).
- **OFFLINE_DEMO graceful-degrade** (Phase 8 D-16): empty `SENTRY_DSN` → skip Sentry. Phase 9 mirrors: `OFFLINE_DEMO=true` → force `db_sqlite` regardless of `METADATA_BACKEND`.
- **Empty-token-disables-endpoint pattern** (Phase 8): consistent fail-soft posture. Phase 9 fail-loud on missing `DATABASE_URL` when `METADATA_BACKEND=postgres` and `OFFLINE_DEMO` is unset (no graceful degrade — bad config should fail the deploy).
- **structlog contextvars propagation across `asyncio.create_task`** (Phase 8 D-12): keepalive task runs without a request_id (correct — it's not request-scoped). Use a logger with no contextvars expected.

### Integration Points
- **`backend/db.py` → `db_sqlite.py` rename + new `db_postgres.py` + dispatcher** (D-07, D-08). 23-function signature parity is the contract.
- **`backend/app.py` lifespan startup**: pool init, keepalive task launch, CLUSTERS rebuild call (D-16, D-17, D-21). Order matters: pool ready → CLUSTERS rebuild → keepalive task → yield to web.
- **`backend/Procfile`**: add `release: alembic upgrade head` line (D-13).
- **`backend/migrations/`** (new directory): Alembic env.py + versions/. Async config (D-19).
- **`backend/scripts/sqlite_to_postgres.py`** (new file): one-shot dump-and-load (D-01, D-20).
- **CI test fixture**: parametrize `METADATA_BACKEND` so existing test suite runs against both backends (D-10).

</code_context>

<specifics>
## Specific Ideas

- **Hybrid schema is *softer* than the phase goal language but pragmatically right.** Baking 100% of v1.1 columns into the initial migration would mean Phase 9 commits to column shapes for moderation/reporting features it hasn't built. The Hybrid path keeps FK graph stable but lets Phase 11's planner choose Phase 11's columns.
- **Module split (D-07) keeps the SQLite branch testable and demo-able forever.** It also means D-09 explicitly does NOT delete `db_sqlite.py` at end of v1.1 — that question lives in v1.2.
- **Test fixture parametrizing METADATA_BACKEND (D-10) is the single most important regression guard.** Without it, Phase 9 ships and SQLite silently rots. With it, OFFLINE_DEMO=true CI run validates the SQLite path on every commit.
- **Procfile `release:` phase verification (D-14) is the only real risk in this plan.** If Railway doesn't honor it, fallback is FastAPI-lifespan with `pg_advisory_lock` — workable, just less clean. Planner runs the verification first.

</specifics>

<deferred>
## Deferred Ideas

- **pgvector centroid storage** — v1.2+. BYTEA round-trip locked for v1.1 (L-03).
- **Connection pool dynamic sizing** — v1.2+. `max_size=10` is a fixed lock for v1.1 (L-02).
- **Per-pod migration locking** — Out of scope. `--workers 1` Procfile pin holds; no horizontal scale at v1.1.
- **Read-replica routing** — v1.2+. Single Neon endpoint at v1.1.
- **Postgres-side full-text search on captions** — Out of scope. v1.1 keeps NumPy in-memory cosine for vector search (L-03 implies no pgvector; same posture extends to FTS).
- **`db_sqlite.py` deletion** — v1.2+ scope (D-09 keeps it indefinitely through v1.1).
- **Dual-write window cutover** — Explicitly rejected (D-02). One-shot script per SC-2 only.
- **Automatic migration rollback on failure** — Out of scope (D-15). Failed deploy = manual investigation.

</deferred>

---

*Phase: 09-postgres-migration-neon-asyncpg-alembic*
*Context gathered: 2026-04-28*
