# Phase 9 Discussion Log

**Date:** 2026-04-28
**Mode:** Standard (no flags)
**Outcome:** CONTEXT.md written; ready for `/gsd-plan-phase 9`.

## Areas Selected for Discussion

User selected (multiSelect): **Schema bake-in scope, METADATA_BACKEND structure, Alembic upgrade timing**.
Skipped: Cutover strategy (implicitly settled by SC-2 wording — `scripts/sqlite_to_postgres.py`).

## Area 1: Schema bake-in scope

**Q1.** What goes into the initial Alembic migration?
Options presented:
- Full v1.1 schema, columns nullable
- Phase-9-active tables only, owners add later
- Hybrid — tables now, columns later
**Selected:** Hybrid — tables now, columns later
**Note:** Soft deviation from phase goal text ("full v1.1 schema baked in"). Captured in D-05.

**Q2.** Which tables exist in the initial migration?
Options presented:
- All 7 v1.1 tables (Recommended)
- 5 tables — Phase 9 + reported_csam (statutory)
- 4 tables — strict Phase 9 only
**Selected:** All 7 v1.1 tables
**Captured:** D-04 (FK graph stable from day one; Phases 10-12 do `ALTER ADD COLUMN` only).

## Area 2: METADATA_BACKEND structure

**Q1.** Where does the dispatcher live?
Options presented:
- Module split: db_sqlite.py + db_postgres.py (Recommended)
- Per-function branching inside db.py
- Postgres-only db.py, rollback = redeploy v1.0 commit
**Selected:** Module split (Recommended)
**Captured:** D-07 (thin selector in `db.py`, identical function signatures across `db_sqlite.py` and `db_postgres.py`).

**Q2.** How do OFFLINE_DEMO and METADATA_BACKEND interact?
Options presented:
- OFFLINE_DEMO=true hard-overrides to sqlite (Recommended)
- OFFLINE_DEMO=true + METADATA_BACKEND=postgres errors at startup
- Independent flags — user is responsible
**Selected:** Hard-override to sqlite (Recommended)
**Captured:** D-11 (mirrors Phase 8 D-16 graceful-degrade pattern).

## Area 3: Alembic upgrade timing

**Q1.** When does `alembic upgrade head` execute?
Options presented:
- Procfile pre-command, single attempt (Recommended)
- Lifespan startup hook with PG advisory lock
- Manual `railway run alembic upgrade head`
**Selected:** Procfile pre-command (Recommended)
**Captured:** D-13. Planner-action: D-14 verifies Railway honors the `release:` phase before locking the Procfile change.

## Claude's Discretion (recorded without asking)

- **D-19:** Alembic env.py async config — standard `async_engine_from_config` + `connection.run_sync(do_run_migrations)` pattern. Implementation detail.
- **D-20:** Dump-and-load script uses `asyncpg.copy_records_to_table` for bulk speed; centroid bytes copied verbatim.
- **D-21:** `CLUSTERS` cache rebuild on startup — port existing logic with identical signature; fetch-all is fine at hackathon scale.
- **D-22:** Migration version naming — standard Alembic timestamp prefix; planner picks specifics.

## Deferred Ideas

(See CONTEXT.md `<deferred>` section.) Notable: pgvector, dual-write cutover, read-replica routing, db_sqlite.py deletion — all v1.2+ or explicitly rejected.

## Pending Pre-Planning Verifications

1. **D-14:** Confirm Railway honors Procfile `release:` phase. If not, fallback to lifespan + `pg_advisory_lock`.
2. **D-18:** Confirm asyncpg + Neon TLS interaction (`ssl='require'` vs libpq `sslmode=require`). Run a one-line connection probe before locking the connection-string format. (Pre-existing pending todo from STATE.md.)

---

*Phase: 09-postgres-migration-neon-asyncpg-alembic*
*Discussion logged: 2026-04-28*
