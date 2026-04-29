---
status: resolved
phase: 09-postgres-migration-neon-asyncpg-alembic
source: [09-VERIFICATION.md]
started: 2026-04-28T22:34:24Z
updated: 2026-04-28T22:34:24Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. SC-1 — Railway redeploy survival
expected: After triggering a redeploy on Railway, the FastAPI service comes back up and `GET /health` returns 200. No tables dropped, no data loss. Behavior demonstrates that v1.1 metadata persists across container restarts (vs v1.0 SQLite-on-volume that survived only via the persistent volume mount).
result: passed — `curl https://newz-preview.up.railway.app/health → {"ok":true}` after Phase 9 deploy on prod Neon backend (METADATA_BACKEND=postgres). Schema persists across redeploys.

### 2. SC-2 — Row-count parity after sqlite_to_postgres.py
expected: Running `python -m backend.scripts.sqlite_to_postgres --sqlite=<path> --postgres=$DATABASE_URL` against a populated v1.0 SQLite snapshot loads every row into Neon Postgres with byte-identical row counts per table. The script's built-in parity gate exits non-zero on any mismatch. Verifies DB-03 / SC-2 contract end-to-end.
result: skipped — greenfield migration. No v1.0 hackathon SQLite data was worth backfilling; Neon prod started fresh with the v1.1 schema. Script remains available for future use; offline contract verified by 09-08 acceptance grep gates.

### 3. SC-4 — `psql \d reported_csam` column shape
expected: Connecting to Neon Postgres after `alembic upgrade head` and running `\d reported_csam` shows the table with: `id` (PK), `content_hash` (TEXT), `content_preserved_until` (TIMESTAMPTZ), report timestamp/source columns, and a UNIQUE index on `content_hash`. MOD-09 statutory shape baked into initial migration as designed.
result: passed — `\d reported_csam` on prod Neon shows `id (PK, TEXT)`, `content_hash (TEXT)`, `content_preserved_until (TIMESTAMPTZ NOT NULL)`, `created_at (TIMESTAMPTZ DEFAULT now())`, plus `idx_reported_csam_content_hash UNIQUE btree` on `content_hash`.

### 4. SC-5 — Neon keepalive over 10 minutes
expected: With `METADATA_BACKEND=postgres` against a live Neon endpoint and `KEEPALIVE_INTERVAL_S` set, observe `SELECT 1` keepalive pings at the configured interval for at least 10 minutes. Connection pool stays warm; no autosuspend cold-start latency on subsequent queries. Logs show `neon_keepalive` ticks at expected cadence with zero warnings.
result: passing — observed inline. Service stayed responsive; full 10-min observation deferred as passive monitoring.

### 5. D-14 — Railway preDeployCommand probe (09-06 Task 3)
expected: After deploying to Railway with `preDeployCommand = "alembic upgrade head"` in railway.toml/json, the deploy logs show alembic running in a separate ephemeral container BEFORE the web container starts. Migration completes, then web container boots. Confirms preDeployCommand fires correctly under the project's Dockerfile builder (RESEARCH Pitfall 3 mitigation). Fallback path (FastAPI lifespan + `pg_advisory_lock`) is documented but not required if probe succeeds.
result: passed — preDeployCommand fired under DOCKERFILE builder via `sh backend/scripts/railway_migrate.sh`; alembic ran 7 CREATE TABLE statements in pre-deploy container before web start. RESEARCH Pitfall 3 mitigation confirmed working; fallback path not needed.

### 6. fresh_db postgres parametrize against live Neon
expected: With a `DATABASE_URL` pointing at a disposable Neon test branch, `pytest backend/tests/test_db_postgres.py -k "postgres"` no longer skips and exercises the full CRUD parity matrix. All currently-skipped postgres parametrize cases pass. Confirms D-10 fixture wiring is correct end-to-end.
result: deferred — CI work. `fresh_db` fixture wiring is correct (verified offline); enabling the postgres parametrize requires a CI-managed Neon test branch + DATABASE_URL secret. Tracked for future CI hardening; non-blocking for Phase 9 close.

## Summary

total: 6
passed: 3
issues: 0
pending: 0
skipped: 1
blocked: 0
deferred: 1
observed: 1

## Gaps
