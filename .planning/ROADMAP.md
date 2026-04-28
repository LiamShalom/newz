# Roadmap: Newz

## Milestones

- ✅ **v1.0 Hackathon MVP** — Phases 1-4 (shipped 2026-04-26 · won HackTech 2026)
- 🚧 **v1.1 Public-Launch-Ready Backbone** — Phases 8-13 (in progress)

## Overview

v1.1 hardens the v1.0 hackathon monolith for public launch without disturbing the load-bearing decisions that made v1.0 work (single-process asyncio, no ORM, no Redis, anonymity-by-default, --workers 1, in-memory CLUSTERS cache). The build order is dependency-first: ship observability scaffolding so all subsequent migration work is debuggable; migrate metadata to managed Postgres (Neon) as the keystone because every new column and table belongs in the new DB; migrate clip media to Vercel Blob to give moderation workers a stable HTTPS input URL; gate uploads through a Gemini Flash-Lite + CSAM hash moderation pipeline running parallel-with-Marengo; ship anonymous reactive reporting + admin queue in parallel with the moderation gate; close out by wrapping the final pipeline shape in Logfire spans and locking the OFFLINE_DEMO end-to-end contract with a CI smoke test. Anonymity invariants and OFFLINE_DEMO survivability are cross-cutting — every phase carries part of the load.

**Phase numbering note:** v1.1 starts at Phase 8 (Phases 5-7 reserved as gap; v1.0 archive ends at Phase 4).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>✅ v1.0 Hackathon MVP (Phases 1-4) — SHIPPED 2026-04-26</summary>

- [x] Phase 1: Foundation, Capture & Ingest (5/5 plans) — completed 2026-04-25
- [x] Phase 2: Marengo Embedding (2/2 plans) — completed 2026-04-25
- [x] Phase 3: Clustering + Debug Overlay (2/2 plans) — completed 2026-04-25
- [x] Phase 4: Multi-Agent Compile + Real-Time Feed (3/3 plans + parent-cluster pivot) — completed 2026-04-26

Full archive: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)

</details>

### 🚧 v1.1 Public-Launch-Ready Backbone (In Progress)

**Milestone Goal:** Make Newz survivable in public — durable data, safe content, prod-grade observability — without breaking anonymity-by-default or upload UX.

- [ ] **Phase 8: Observability Scaffolding** — Sentry + structlog + Logfire + Prometheus /metrics + PII scrubbers shipped first so all later migration work is debuggable
- [ ] **Phase 9: Postgres Migration** — replace SQLite-on-volume with managed Neon Postgres via asyncpg + Alembic; CSAM table baked into the initial migration
- [ ] **Phase 10: Vercel Blob Migration** — replace Railway local-FS clip media with server-mediated Vercel Blob; two ffmpeg strategies (signed-URL trim, tempdir stitch)
- [ ] **Phase 11: Moderation Gate** — Gemini 2.5 Flash-Lite + Cloudflare CSAM hash, parallel-with-Marengo asyncio.gather, tiered fail policy, newsworthy ≥2-parent corroboration
- [ ] **Phase 12: Reactive Reporting + Admin Queue** — anonymous POST /report, token-guarded admin queue with embedded playback, dismiss/hide/block actions
- [ ] **Phase 13: Observability Deepening + OFFLINE_DEMO Audit** — Logfire spans wrap final pipeline, OTel context across create_task, anonymity regression test, OFFLINE_DEMO firewalled-startup CI smoke test

## Phase Details

### Phase 8: Observability Scaffolding
**Goal**: Every subsequent phase ships with structured logs, error tracking, traces, and PII scrubbers already in place — eliminate Railway log spelunking during the rest of the migration.
**Depends on**: Nothing (first v1.1 phase)
**Requirements**: OBS-01, OBS-02, OBS-03, OBS-04, PRIV-01, PRIV-02
**Success Criteria** (what must be TRUE):
  1. Backend logs in Railway appear as structured JSON (one event per line, ISO timestamp, request_id field) instead of free-form text.
  2. A deliberately-thrown exception surfaces in Sentry within 60s with `session_uuid`, `gps_lat`, `gps_lng`, and `blob_url` redacted from the event payload.
  3. `curl https://<railway>/metrics` returns Prometheus-format counters and histograms for request and pipeline-stage activity, with no high-cardinality labels (no clip_id, no session_uuid).
  4. `X-Forwarded-For` header on inbound requests is stripped before any log line is emitted (verified by sending a request with a forged XFF header and grepping logs).
  5. structlog contextvars carry `session_hash`, `clip_id`, `request_id` only — never raw session UUID, IP, or GPS (verified by inspecting a request log line end-to-end).
**Plans:** 3 plans

Plans:
- [x] 08-01-PLAN.md — observability module skeleton (anonymity, logging_config, sentry, middleware, metrics) + config + deps + scrubber/logging unit tests
- [x] 08-02-PLAN.md — wire observability into backend/app.py (first-import, middleware order, /metrics route) + XFF/contextvars/auth integration tests
- [x] 08-03-PLAN.md — pipeline stage timing (ingest/embed/cluster) + Sentry OFFLINE_DEMO smoke + before_send round-trip + stage label enum guard

### Phase 9: Postgres Migration (Neon + asyncpg + Alembic)
**Goal**: Retire SQLite-on-volume; metadata lives in managed Postgres with the full v1.1 schema (moderation columns, blob_url, is_hidden, reports, moderation_decisions, reported_csam) baked into the initial migration.
**Depends on**: Phase 8
**Requirements**: DB-01, DB-02, DB-03, DB-04, DB-05, DB-06, DB-07, MOD-09, DEMO-03
**Success Criteria** (what must be TRUE):
  1. Backend redeploys to Railway and existing clips still appear in the feed (CLUSTERS cache rebuilt from Postgres, no data loss across redeploy).
  2. Running `scripts/sqlite_to_postgres.py` against the v1.0 SQLite snapshot results in matching row counts in Postgres for clips, clip_embeddings, clusters, segments — verifiable via two `SELECT count(*)` queries.
  3. Setting `METADATA_BACKEND=sqlite` env var rolls the backend back to the v1.0 SQLite path without code changes; setting it to `postgres` returns to Neon.
  4. The initial Alembic migration creates a `reported_csam` table with `content_hash` and `content_preserved_until TIMESTAMPTZ` columns — verifiable via `\d reported_csam` in psql.
  5. Backend startup logs show a successful `SELECT 1` against Neon every 4 minutes (Neon keepalive defeats scale-to-zero cold-start).
**Plans**: TBD

### Phase 10: Vercel Blob Migration
**Goal**: Retire Railway `/data/clips/` for clip media; uploads land in Vercel Blob via server-mediated path; ffmpeg reads from Blob with two strategies (signed-URL byte-range trim, tempdir-download stitch); compiled segments served from Blob CDN.
**Depends on**: Phase 9
**Requirements**: BLOB-01, BLOB-02, BLOB-03, BLOB-04, BLOB-05, BLOB-06, BLOB-07, BLOB-08
**Success Criteria** (what must be TRUE):
  1. Backend redeploys to Railway and existing clip media still plays from the feed (Blob URLs absolute; `/media` StaticFiles mount removed).
  2. A new clip recorded in the iOS Safari PWA uploads via `POST /clips` and lands in Vercel Blob under `uploads/{clip_id}.{ext}` — verifiable via Blob console.
  3. Compiled run segments appear in Vercel Blob under `runs/{run_id}.mp4` and the frontend feed renders them from absolute Blob URLs.
  4. A direct browser PUT to Vercel Blob is rejected (verified by attempting one and observing 401/403).
  5. After a clip's moderation decision flips to `blocked`, its Blob object is hard-deleted within the cleanup window (verifiable via Blob console + DB join).
  6. Setting `STORAGE_BACKEND=local` env var rolls the backend back to the v1.0 local-FS path without code changes.
**Plans**: TBD
**UI hint**: yes

### Phase 11: Moderation Gate (Gemini Flash-Lite + CSAM hash)
**Goal**: Every uploaded clip passes through a moderation gate before entering cluster/compile; gate runs parallel-with-Marengo so common-case latency does not regress; tiered failure policy (timeout fail-CLOSED, 5xx outage fail-OPEN to admin queue, CSAM fail-CLOSED); newsworthy corroboration via ≥2-parent + violence-signal soft-flag.
**Depends on**: Phase 9, Phase 10
**Requirements**: MOD-01, MOD-02, MOD-03, MOD-04, MOD-05, MOD-06, MOD-07, MOD-08, MOD-10, PRIV-03
**Success Criteria** (what must be TRUE):
  1. Uploading a clip with disallowed content (staged test fixture) results in a clip that never appears in the public feed and never enters CLUSTERS — verifiable via `SELECT moderation_status FROM clips` and feed inspection.
  2. Common-case end-to-end upload-to-publish wall-clock latency on the v1.0 staged demo dataset is within 10% of v1.0 baseline (verified by benchmark) — moderation completes inside Marengo's embed window.
  3. With the moderation API timing out (simulated via fault injection), the clip is marked `moderation_status='blocked'` (fail-CLOSED) and a `moderation_decisions` audit row is recorded with `status='errored'`.
  4. With `OFFLINE_DEMO=true`, uploading a clip results in `moderation_status='passed'` with no external API call made (verifiable via firewalled startup + clip flows through to feed).
  5. A cluster with ≥2 distinct parent uploads AND a violence signal produces a segment with `sensitive=true` displayed behind a tap-to-view interstitial in the feed UI — not hard-blocked.
  6. Outbound moderation API request payload contains video bytes only — no GPS, no session_uuid, no upload timestamp (verified via packet capture or vendor-side request log).
**Plans**: TBD
**UI hint**: yes

### Phase 12: Reactive Reporting + Admin Queue
**Goal**: Anonymous post-publish report flow + token-guarded admin queue with embedded clip playback; reports table never carries session_uuid; brigading-defense via UNIQUE(segment, ip_hash); admin actions hide segments and optionally block underlying clips.
**Depends on**: Phase 9
**Requirements**: REPORT-01, REPORT-02, REPORT-03, REPORT-04, REPORT-05, REPORT-06, REPORT-07, REPORT-08, REPORT-09, REPORT-10, PRIV-04
**Success Criteria** (what must be TRUE):
  1. Tapping the "Report" button on a segment in the feed UI submits a `POST /report` with `(segment_id, reason_code)` and no session_uuid in the request body — verifiable via network inspector.
  2. An admin with the `ADMIN_TOKEN` can `GET /admin/reports` and see open reports with embedded playable clip URLs; without the token, the endpoint returns 401/503.
  3. Posting `action=hide-segment` to `POST /admin/reports/{id}/action` causes the segment to disappear from the public feed within one SSE refresh — verifiable by reloading the feed.
  4. Submitting two reports for the same segment from the same IP within a minute results in only one row in the `reports` table (UNIQUE constraint enforced).
  5. The admin queue UI displays GPS at city-level resolution only — raw lat/lng and session_uuid never appear (verified by inspecting the DOM).
  6. Auto-takedown is never triggered by report count alone — verified by code review and integration test (10 reports without classifier signal → segment remains visible).
**Plans**: TBD
**UI hint**: yes

### Phase 13: Observability Deepening + OFFLINE_DEMO Audit
**Goal**: Wrap the final v1.1 pipeline shape in Logfire spans (instrument_anthropic, OTel context across asyncio.create_task); lock anonymity invariants behind a regression test; lock OFFLINE_DEMO end-to-end behind a firewalled-startup CI smoke test; bounded metric labels enforced.
**Depends on**: Phase 11, Phase 12
**Requirements**: OBS-05, OBS-06, OBS-07, OBS-08, OBS-09, DEMO-01, DEMO-02
**Success Criteria** (what must be TRUE):
  1. Uploading a clip end-to-end produces a single Logfire trace with child spans for ingest → embed → moderate → cluster → compile → stitch → SSE — verifiable in the Logfire dashboard.
  2. The compile pipeline trace shows per-subagent token counts and timing (Angle Selector, Caption Writer, Publisher) via `instrument_anthropic` — verifiable in the same Logfire trace.
  3. CI smoke test asserts the backend starts under `OFFLINE_DEMO=true` with the public network firewalled (no Postgres, Blob, Gemini, Sentry, Logfire calls succeed) — verifiable in CI run logs.
  4. A regression test asserts that no log line, span attribute, metric label, or admin response payload contains raw session_uuid, exact GPS, or raw IP — verifiable as a green CI step on every PR.
  5. Logfire span attributes use the locked whitelist (stage, clip_id, cluster_id, latency_ms) — verifiable by inspecting attributes on a live trace and asserting the disallow set is empty.
  6. Sentry has `traces_sample_rate=0` and Logfire owns all span data — verifiable via config audit and absence of duplicate spans in either backend.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 8 → 9 → 10 → 11 ∥ 12 → 13

(Phase 11 and Phase 12 share the Postgres schema but operate on disjoint columns — can run in parallel after Phase 10 ships.)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation, Capture & Ingest | v1.0 | 5/5 | Complete | 2026-04-25 |
| 2. Marengo Embedding | v1.0 | 2/2 | Complete | 2026-04-25 |
| 3. Clustering + Debug Overlay | v1.0 | 2/2 | Complete | 2026-04-25 |
| 4. Multi-Agent Compile + Real-Time Feed | v1.0 | 3/3 | Complete | 2026-04-26 |
| 8. Observability Scaffolding | v1.1 | 0/TBD | Not started | - |
| 9. Postgres Migration | v1.1 | 0/TBD | Not started | - |
| 10. Vercel Blob Migration | v1.1 | 0/TBD | Not started | - |
| 11. Moderation Gate | v1.1 | 0/TBD | Not started | - |
| 12. Reactive Reporting + Admin Queue | v1.1 | 0/TBD | Not started | - |
| 13. Observability Deepening + OFFLINE_DEMO Audit | v1.1 | 0/TBD | Not started | - |
