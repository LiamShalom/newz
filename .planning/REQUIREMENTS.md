# Newz v1.1 — Public-Launch-Ready Backbone — Requirements

**Milestone:** v1.1
**Status:** Locked (roadmap approved 2026-04-27)
**Last updated:** 2026-04-27

---

## v1.1 Requirements

### Persistence — Postgres Migration

- [ ] **DB-01:** Backend reads and writes all metadata against managed Postgres (Neon), not SQLite-on-volume.
- [ ] **DB-02:** Schema migrations are versioned and idempotent via Alembic async (no SQLAlchemy ORM at runtime).
- [ ] **DB-03:** One-shot dump-and-load utility migrates v1.0 SQLite metadata into Postgres without data loss.
- [ ] **DB-04:** `CLUSTERS` in-memory cache rebuilds correctly from Postgres on backend startup.
- [ ] **DB-05:** Backend survives Railway redeploy without losing prior clip metadata.
- [ ] **DB-06:** `METADATA_BACKEND` feature flag allows rollback to SQLite during the migration window.
- [ ] **DB-07:** Postgres connection pool sized for `--workers 1` (max_size=10); Procfile pins single-worker.

### Object Storage — Vercel Blob Migration

- [ ] **BLOB-01:** New uploads via `POST /clips` land in Vercel Blob through a server-mediated path (browser → FastAPI → Blob); direct browser PUT is explicitly rejected.
- [ ] **BLOB-02:** Compiled segment outputs land in Vercel Blob under a `runs/` prefix.
- [ ] **BLOB-03:** ffmpeg `_sync_trim` reads source clips directly from Blob signed URLs via `-c copy` byte-range; no full-file download.
- [ ] **BLOB-04:** ffmpeg `_sync_stitch` (re-encode/normalize-and-concat) pre-downloads source clips into `tempfile.TemporaryDirectory()` before invoking the filter graph.
- [ ] **BLOB-05:** Frontend feed renders clips and segments from absolute Blob URLs; the `/media` `StaticFiles` mount is removed.
- [ ] **BLOB-06:** `STORAGE_BACKEND` feature flag allows rollback to local-FS during the migration window.
- [ ] **BLOB-07:** Clip media survives Railway redeploy; backend never reads from `/data/clips/` after migration.
- [ ] **BLOB-08:** Blob-cleanup hook hard-deletes media for clips whose moderation decision is `blocked`.

### Pre-Publish Moderation Gate

- [ ] **MOD-01:** Every uploaded clip runs through the moderation gate before entering cluster or compile.
- [ ] **MOD-02:** Moderation classifier (Gemini 2.5 Flash-Lite) runs in parallel with Marengo embed via `asyncio.gather(..., return_exceptions=True)` + `asyncio.wait_for` per task.
- [ ] **MOD-03:** Common-case end-to-end upload-to-publish latency does not regress against v1.0 (classifier completes inside Marengo's embed window).
- [ ] **MOD-04:** CSAM hash check via Cloudflare CSAM Scanning Tool runs on every clip; fail-closed on any error.
- [ ] **MOD-05:** Tiered failure-mode policy: classifier timeout → fail-CLOSED (block); classifier 5xx outage → fail-OPEN with `moderation_status=unknown`, surfaced in admin queue.
- [ ] **MOD-06:** Every moderation decision (pass / block / unknown) is recorded in a `moderation_decisions` audit table with full decision context.
- [ ] **MOD-07:** Newsworthy corroboration: when a cluster has ≥2 distinct parent uploads AND a violence signal, the segment is soft-flagged (interstitial), not hard-blocked.
- [ ] **MOD-08:** Feed UI displays a tap-to-view interstitial on sensitive segments before autoplay.
- [ ] **MOD-09:** A `reported_csam` table preserves content_hash and metadata for 90 days per 18 U.S.C. § 2258A.
- [ ] **MOD-10:** `OFFLINE_DEMO=true` bypasses every external moderation API; classifier returns a passthrough decision; CSAM hash check is skipped.

### Reactive Reporting + Admin Queue

- [ ] **REPORT-01:** Anonymous `POST /report` accepts `(segment_id, reason_code, optional freetext)`; no auth header required.
- [ ] **REPORT-02:** The `reports` table never carries `session_uuid` — only `(segment_id, reason_code, freetext, reporter_ip_hash, server_timestamp)`.
- [ ] **REPORT-03:** Reporter IP is hashed with a daily-rotated HMAC key and used only for dedup/rate-limit; never stored long-term.
- [ ] **REPORT-04:** A per-segment-per-reporter UNIQUE constraint prevents brigading from inflating report counts.
- [ ] **REPORT-05:** Per-IP rate limit on `POST /report` (e.g., 10/min/IP) caps mass-report attacks.
- [ ] **REPORT-06:** Token-guarded `GET /admin/reports` lists open reports with embedded clip playback so reviewers cannot act on a report without watching the content.
- [ ] **REPORT-07:** Token-guarded `POST /admin/reports/{id}/action` accepts `dismiss`, `hide-segment`, or `hide-and-block-clips`.
- [ ] **REPORT-08:** Hidden segments are filtered out of the public feed (`WHERE NOT is_hidden`).
- [ ] **REPORT-09:** Admin auth uses the existing single-shared `ADMIN_TOKEN` env var; no per-admin login system in v1.1.
- [ ] **REPORT-10:** Auto-takedown never fires on report count alone — must be corroborated by a classifier signal.

### Observability

- [ ] **OBS-01:** All application logs are emitted as structured JSON (`structlog` + JSONRenderer in prod, ConsoleRenderer in dev).
- [ ] **OBS-02:** Sentry captures errors with `send_default_pii=False` and `max_request_body_size="never"`.
- [ ] **OBS-03:** A Sentry `before_send` hook scrubs `session_uuid`, `gps_lat`, `gps_lng`, and `blob_url` from every event.
- [ ] **OBS-04:** Prometheus `/metrics` endpoint exposes request and pipeline-stage counters/histograms with **bounded labels only** (stage, status, route) — never `clip_id` or `session_uuid`.
- [ ] **OBS-05:** Logfire span tracing covers the full pipeline: ingest → embed → moderate → cluster → compile → stitch → SSE.
- [ ] **OBS-06:** `instrument_anthropic()` surfaces per-subagent token counts and timing across the multi-agent compile.
- [ ] **OBS-07:** OTel context is captured before every `asyncio.create_task` and re-attached inside the spawned coroutine, so embed/cluster/compile spans are not orphaned roots.
- [ ] **OBS-08:** Sentry tracing is disabled (`traces_sample_rate=0`) and Logfire owns all span data; no double-instrumented spans.
- [ ] **OBS-09:** Logfire span attributes use a whitelist (stage, clip_id, cluster_id, latency_ms); session_uuid, IP, and exact GPS never appear as span attributes.

### Anonymity Invariants (cross-cutting)

- [ ] **PRIV-01:** `X-Forwarded-For` is stripped in FastAPI middleware before any logging or context binding.
- [ ] **PRIV-02:** `structlog.bind_contextvars` only carries `session_hash` (sha256 of session UUID), `clip_id`, and `request_id` — never raw session UUID, IP, or GPS.
- [ ] **PRIV-03:** Moderation API requests strip GPS, session_uuid, and timestamp before sending video bytes to the classifier provider.
- [ ] **PRIV-04:** Admin queue UI redacts GPS to city-level resolution; never displays raw lat/lng or session UUID to reviewers.

### OFFLINE_DEMO + Operational Hardening

- [ ] **DEMO-01:** `OFFLINE_DEMO=true` continues to work end-to-end with all v1.1 dependencies stubbed (Postgres → in-memory SQLite, Blob → local FS, moderation → passthrough, Sentry/Logfire → no-op).
- [ ] **DEMO-02:** A CI smoke test asserts the backend starts under `OFFLINE_DEMO=true` with the public network firewalled.
- [ ] **DEMO-03:** Pre-warm cycle on startup pings Neon (`SELECT 1`) every 4 minutes to defeat scale-to-zero cold-start, alongside the existing Marengo pre-warm.

---

## Future Requirements (deferred to v1.2+)

- Per-session and per-IP rate limits beyond report endpoint (general abuse controls)
- Adversarial-probing defenses (classifier-mapping detection)
- Auto-takedown threshold tuning against real launch traffic
- Langfuse multi-agent LLM tracing (Logfire `instrument_anthropic()` is sufficient for v1.1)
- Stitched-segment caching layer
- Shadow ban / reputation scoring (rejected as anti-feature, but if anonymity model evolves)
- pgvector / Pinecone / Qdrant (NumPy in-memory cosine sufficient at <1000 vectors)
- Per-admin login system / per-admin audit trail (deferred until team grows past 2 reviewers)
- PgBouncer (deferred until horizontal scale makes single-worker insufficient)
- Horizontal scale (multi-worker Uvicorn / SSE pub-sub) — explicitly out of scope; `--workers 1` is locked

## Out of Scope (explicit exclusions)

- **User accounts / login / profiles** — anonymity-by-default is load-bearing; admin auth is the only login system in v1.1.
- **Live streaming** — carried forward from v1.0 out-of-scope.
- **Native iOS app** — PWA remains sufficient.
- **Likes / comments / per-segment engagement** — anonymity friction.
- **User-authored captions** — defeats AI editorial moat.
- **National / regional feed** — hyperlocal IS the differentiator.
- **Map view** — distance overlay continues to suffice.
- **SQLAlchemy ORM** — explicitly rejected; `db.py` is 710 lines of hand-written SQL and ORM doubles diff for zero benefit during this migration.
- **pgvector** — would change clustering math and invalidate v1.0 calibrated thresholds.
- **Direct browser → Blob upload** — skips moderation gate; permanently rejected.
- **Cloudflare R2 (this milestone)** — Vercel Blob chosen per PROJECT.md lock-in; R2 cost-at-scale advantage flagged for re-evaluation if egress becomes material.
- **Shadow-banning / per-user reputation / appeals** — require persistent identity; incompatible with anonymity-by-default.

---

## Traceability

Each REQ-ID maps to exactly one phase. 51 of 51 v1.1 requirements mapped. No orphans.

| Requirement | Phase | Status |
|-------------|-------|--------|
| OBS-01 | Phase 8 | Pending |
| OBS-02 | Phase 8 | Pending |
| OBS-03 | Phase 8 | Pending |
| OBS-04 | Phase 8 | Pending |
| PRIV-01 | Phase 8 | Pending |
| PRIV-02 | Phase 8 | Pending |
| DB-01 | Phase 9 | Pending |
| DB-02 | Phase 9 | Pending |
| DB-03 | Phase 9 | Pending |
| DB-04 | Phase 9 | Pending |
| DB-05 | Phase 9 | Pending |
| DB-06 | Phase 9 | Pending |
| DB-07 | Phase 9 | Pending |
| MOD-09 | Phase 9 | Pending |
| DEMO-03 | Phase 9 | Pending |
| BLOB-01 | Phase 10 | Pending |
| BLOB-02 | Phase 10 | Pending |
| BLOB-03 | Phase 10 | Pending |
| BLOB-04 | Phase 10 | Pending |
| BLOB-05 | Phase 10 | Pending |
| BLOB-06 | Phase 10 | Pending |
| BLOB-07 | Phase 10 | Pending |
| BLOB-08 | Phase 10 | Pending |
| MOD-01 | Phase 11 | Pending |
| MOD-02 | Phase 11 | Pending |
| MOD-03 | Phase 11 | Pending |
| MOD-04 | Phase 11 | Pending |
| MOD-05 | Phase 11 | Pending |
| MOD-06 | Phase 11 | Pending |
| MOD-07 | Phase 11 | Pending |
| MOD-08 | Phase 11 | Pending |
| MOD-10 | Phase 11 | Pending |
| PRIV-03 | Phase 11 | Pending |
| REPORT-01 | Phase 12 | Pending |
| REPORT-02 | Phase 12 | Pending |
| REPORT-03 | Phase 12 | Pending |
| REPORT-04 | Phase 12 | Pending |
| REPORT-05 | Phase 12 | Pending |
| REPORT-06 | Phase 12 | Pending |
| REPORT-07 | Phase 12 | Pending |
| REPORT-08 | Phase 12 | Pending |
| REPORT-09 | Phase 12 | Pending |
| REPORT-10 | Phase 12 | Pending |
| PRIV-04 | Phase 12 | Pending |
| OBS-05 | Phase 13 | Pending |
| OBS-06 | Phase 13 | Pending |
| OBS-07 | Phase 13 | Pending |
| OBS-08 | Phase 13 | Pending |
| OBS-09 | Phase 13 | Pending |
| DEMO-01 | Phase 13 | Pending |
| DEMO-02 | Phase 13 | Pending |

**Coverage by phase:**

| Phase | REQ count | REQ-IDs |
|-------|-----------|---------|
| Phase 8: Observability Scaffolding | 6 | OBS-01..04, PRIV-01..02 |
| Phase 9: Postgres Migration | 9 | DB-01..07, MOD-09, DEMO-03 |
| Phase 10: Vercel Blob Migration | 8 | BLOB-01..08 |
| Phase 11: Moderation Gate | 10 | MOD-01..08, MOD-10, PRIV-03 |
| Phase 12: Reactive Reporting + Admin Queue | 11 | REPORT-01..10, PRIV-04 |
| Phase 13: Observability Deepening + OFFLINE_DEMO Audit | 7 | OBS-05..09, DEMO-01..02 |
| **Total** | **51** | (no orphans, no duplicates) |
