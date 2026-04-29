# Project Research Summary

**Project:** Newz v1.1 — Public-Launch-Ready Backbone
**Domain:** Anonymous crowdsourced UGC video platform — production hardening (managed DB, object storage, AI moderation, reactive reporting, observability)
**Researched:** 2026-04-27
**Confidence:** HIGH

## Executive Summary

Newz v1.1 is a production-hardening milestone on top of a won-hackathon FastAPI monolith. The codebase is a single-process asyncio pipeline: browser -> POST /clips (202) -> asyncio.create_task -> embed (Marengo 3.0) -> cluster (NumPy cosine + GPS + timestamp) -> compile (Claude Agent SDK + Gemini 2.5 Flash) -> ffmpeg stitch -> SSE broadcast. The entire v1.1 build must preserve this single-process contract — the design decisions that made v1.0 work (no Redis, no Celery, no ORM, one Uvicorn worker, fire-and-forget pipeline) are load-bearing and must not be disturbed during migration. The recommended upgrade path swaps storage drivers mechanically (aiosqlite -> asyncpg, local FS -> Vercel Blob HTTP API) without introducing SQLAlchemy ORM, pgvector, or horizontal workers.

The recommended six-phase build order is: (1) observability scaffolding first so all subsequent work is debuggable, (2) Postgres migration as the keystone because every new schema column — moderation status, blob URL, hidden flag, reports table — should land in Postgres rather than the retiring SQLite volume, (3) Vercel Blob migration to give moderation workers a stable HTTPS URL for input, (4) moderation gate in parallel with embed via asyncio.gather(return_exceptions=True), (5) reactive report flow which depends only on Postgres schema, (6) observability deepening once the final pipeline shape is locked. Phases 4 and 5 can be built in parallel.

The two biggest execution risks are legal and structural. On the legal side: 18 U.S.C. 2258A requires any US-jurisdiction platform to report CSAM within 24 hours of becoming aware of it; a reported_csam table with content_preserved_until TIMESTAMPTZ and a CSAM hash check (Cloudflare CSAM Scanning Tool) must land in the initial Postgres migration or v1.1 cannot legally launch. On the structural side: the asyncio.gather(embed, moderate) parallel gate must use return_exceptions=True plus asyncio.wait_for per task — the default return_exceptions=False will cancel the Marengo embed on any moderation API hiccup, silently breaking the pipeline for safe content. Both risks are well-understood and preventable with explicit plan-checks.

## Key Findings

### Recommended Stack

The v1.1 stack adds five layers to the existing FastAPI + Marengo + Claude + Gemini + ffmpeg core. All new dependencies are async-native and require zero new infrastructure processes. Key constraint: --workers 1 is mandatory on Railway; four workers would multiply the asyncpg pool to 60 connections and exhaust Neon free tier.

**Core technologies:**
- **Neon Postgres** (serverless, free tier): replaces SQLite-on-volume — Vercel partner integration, branching for staging/prod, scale-to-zero fits bursty demo traffic. Prefer over Supabase because Supabase Auth creates institutional pressure to break anonymity-by-default.
- **asyncpg 0.30.x**: async Postgres driver, binary protocol, no ORM — db.py is 710 lines of hand-written SQL; SQLAlchemy ORM would double the diff for zero benefit at this codebase size. Use Alembic 1.18.4 async template for migrations only.
- **Vercel Blob + vercel Python SDK 0.5.8** (AsyncBlobClient): replaces Railway volume for clip media; fronted by Vercel CDN. Server-mediated upload only (browser -> FastAPI -> Blob) — direct browser PUT skips the moderation gate and must not be used.
- **Gemini 2.5 Flash-Lite** (gemini-2.5-flash-lite): inline moderation classifier, ~$0.0003/clip, 1.5-3 s p50 on a 10 s clip — fits inside Marengo's 5-15 s embed window so parallel asyncio.gather adds zero user-visible latency. Same google-genai SDK already in stack.
- **structlog 25.5.0**: bound context loggers; carries clip_id, cluster_id, request_id across async hops — python-json-logger cannot do this.
- **sentry-sdk 2.58.0** with AsyncioIntegration(): error tracking; send_default_pii=False; max_request_body_size="never".
- **Pydantic Logfire** (OTel-native): tracing + metrics dashboard; instrument_anthropic() shows per-subagent token counts. Init Logfire first, then Sentry with instrumenter="otel" to avoid double-instrumented spans.

**OFFLINE_DEMO=true contract for new deps:** Postgres -> SQLite/JSON fallback; Blob -> local FS; Gemini moderation -> passthrough; Sentry/Logfire -> no-op. Every new module must have an OFFLINE_DEMO branch or the demo dies on a firewalled machine.

### Expected Features

The five v1.1 feature areas, ordered by dependency graph criticality:

**Must have (table stakes / legal):**
- Managed Postgres (Neon) with Alembic migrations — durable metadata; keystone that blocks everything else
- CSAM hash check via Cloudflare CSAM Scanning Tool — 18 U.S.C. 2258A statutory requirement; reported_csam table with 90-day preservation must land in initial migration
- Vercel Blob for clip media — durable media, signed URL serving, lifecycle support
- Pre-publish AI moderation gate (Gemini 2.5 Flash-Lite, parallel with embed, fail-closed on timeout/5xx) — clips must never enter cluster/compile before passing moderation
- Sensitive-content interstitial (segments.sensitive flag) — newsworthy violence behind tap-to-view, not hard-blocked
- Anonymous report button + admin review queue — post-publish second-line defense; admin queue must embed clip playback so reviewers do not take down content without watching it
- Sentry + structlog structured JSON logs — error visibility for fire-and-forget pipeline exceptions that currently disappear silently

**Should have (differentiators):**
- Newsworthy corroboration gate: if cluster.distinct_parent_count >= 2 AND violence signal present -> interstitial path, not hard block — reuses existing Marengo cluster signal, prevents false positives on news footage
- Span-level tracing across multi-agent compile (Logfire instrument_anthropic()) — the multi-agent narrative was load-bearing in the v1.0 pitch; surface it in tracing
- Per-pipeline-stage metrics with bounded labels — stage/status/route only; never clip_id or session_uuid as labels (cardinality bomb)
- Failure-mode policy documented: fail-closed on CSAM hash, fail-closed on moderation timeout, fail-open on moderation 5xx with quarantine queue

**Defer to v1.2+:**
- Per-session rate limits / abuse controls — explicitly deferred in PROJECT.md
- Langfuse multi-agent LLM tracing — nice-to-have; Logfire instrument_anthropic() covers v1.1
- Stitched-segment caching — only matters once replay traffic is non-trivial
- Auto-takedown threshold tuning — needs real report data
- Vector DB (Pinecone/Qdrant) — NumPy in-memory cosine sufficient at <1000 vectors

**Anti-features (explicitly rejected):**
- Shadow-banning, per-user reputation, appeals process — require persistent identity; incompatible with anonymity-by-default
- Direct browser -> Blob upload — skips moderation gate; never for v1.1
- SQLAlchemy ORM during Postgres migration — doubles diff and risk for zero benefit
- pgvector during Postgres migration — changes clustering math, invalidates calibrated thresholds

### Architecture Approach

All v1.1 changes are contained inside the existing single-process FastAPI monolith. The hot path shape does not change — asyncio.create_task fire-and-forget pipeline, asyncio.Lock-guarded CLUSTERS dict, in-memory NumPy cosine. The two new parallel tasks (embed + moderate via asyncio.gather) extend the existing parallel-gather pattern from compile.py. The critical architectural constraint is that moderation must gate BEFORE cluster — once a clip enters the CLUSTERS dict, removal requires Welford-reverse centroid math that is error-prone; blocked clips should be no-ops in all downstream stages.

**Major components added in v1.1:**
1. **backend/db.py** (modified heavily): aiosqlite -> asyncpg pool; BLOB -> BYTEA for centroid round-trip; INSERT OR REPLACE -> INSERT ... ON CONFLICT; new columns (moderation_status, blob_url, is_hidden); new tables (moderation_decisions, reports, reported_csam).
2. **backend/blob.py** (new): thin AsyncBlobClient wrapper for put/delete/head; used in ingest_clip upload and stitch output upload.
3. **backend/pipeline/moderate.py** (new): moderate_clip(clip_id) -> ModerationDecision; called in asyncio.gather with embed_worker; fail-closed on timeout/5xx.
4. **backend/log.py** (new): structlog config with contextvars merge, ISO timestamp, JSONRenderer in prod; ConsoleRenderer in dev.
5. **backend/metrics.py** (new): prometheus_client Counter/Histogram/Gauge; mounted at /metrics; bounded labels only.
6. **backend/app.py** (modified): add POST /report, GET /admin/reports, POST /admin/reports/{id}/action; remove StaticFiles("/media"); install Sentry + Logfire in lifespan.

**Two ffmpeg call sites with different Blob strategies:**
- _sync_trim (per-run output): ffmpeg reads signed Blob URL directly via HTTP — ffmpeg HTTP protocol handler, -c copy trim, no full-file download needed.
- _sync_stitch (caption composite): pre-download all source clips to tempfile.TemporaryDirectory(), run ffmpeg, cleanup on exit — avoids 2-3x re-fetch latency from ffmpeg probing remote URLs through normalize-and-concat filter graph.

### Critical Pitfalls

1. **asyncio.gather cancel semantics** (P0) — default return_exceptions=False cancels embed task when moderation times out. Use return_exceptions=True + asyncio.wait_for(mod_task, timeout=10) on every parallel gather. This is the most common async gather footgun and will not be caught by tests under low load.

2. **Sync psycopg2 on the async path** (P0) — most FastAPI+Postgres tutorials pull in sync psycopg2. Any copy-paste blocks the event loop, destroying SSE concurrency and pipeline throughput. Use postgresql+asyncpg:// URL and create_async_engine — verify with CI smoke test asserting driver == "asyncpg".

3. **ffmpeg re-fetching Blob URLs 2-3x** (P0) — ffmpeg's concat/filter graph re-fetches remote HTTPS URLs on probe + decode passes; also needs -protocol_whitelist file,http,https,tcp,tls,crypto and -safe 0 flags or errors out. Always download to tempfile.TemporaryDirectory() scratch dir for any stitch that re-encodes. Only safe to stream directly for -c copy trim.

4. **OTel context lost across asyncio.create_task** (P1) — span context closes with the 202 response before the fire-and-forget task executes. Capture otel_context.get_current() before create_task; attach inside the new task. Without this, embed/cluster/compile spans appear as orphaned root traces.

5. **Anonymity linkability via session_uuid on reports** (P0) — the reports table must never carry session_uuid; a row is (segment_id, reason_code, optional_freetext, server_timestamp). IP rate-limiting is done and dropped at the middleware layer, not stored. X-Forwarded-For must be stripped before log emission.

6. **CSAM statutory requirement** (P0) — 18 U.S.C. 2258A. The reported_csam table with content_preserved_until TIMESTAMPTZ must land in the first Postgres migration. Cloudflare CSAM Scanning Tool is the fastest onboarding path. This is not optional and cannot be deferred.

7. **OFFLINE_DEMO broken by new deps** (P1) — OFFLINE_DEMO=true was designed against two external deps (Twelve Labs, Anthropic). v1.1 adds Postgres, Blob, Gemini moderation, Sentry, Logfire. Each new module must have an OFFLINE_DEMO fallback or demo dies on a firewalled machine. Add a CI test: OFFLINE_DEMO=true startup with network firewalled.

## Implications for Roadmap

### Phase 1: Observability Scaffolding
**Rationale:** Ship Sentry + structlog + /metrics in week 1 so all subsequent migration and integration work is debuggable. A half-day investment that makes every other phase faster to debug. FEATURES.md explicitly flags this: "Observability should ship FIRST, not last."
**Delivers:** Sentry error tracking with AsyncioIntegration; structured JSON logs with contextvars bound context; Prometheus /metrics endpoint; request-id middleware.
**Stack:** sentry-sdk 2.58.0, structlog 25.5.0, prometheus-client, Pydantic Logfire (init order: Logfire first, then Sentry with instrumenter="otel").
**Files:** backend/log.py (new), backend/metrics.py (new), backend/app.py (Sentry + Logfire install, request-context middleware).
**Pitfalls to avoid:** max_request_body_size="never" in Sentry init (P1-12); OTel context propagation pattern established now so it is not bolted on later (P1-13); metrics label allowlist locked — stage/status/route only, never clip_id (P1-14).
**OFFLINE_DEMO gate:** Sentry -> no-op when SENTRY_DSN empty; Logfire -> no-op when LOGFIRE_TOKEN absent; structlog ConsoleRenderer in dev/offline, JSONRenderer in prod.
**Research flag:** Standard patterns — skip phase research.

### Phase 2: Postgres Migration
**Rationale:** Postgres is the keystone. Every new schema column (moderation_status, blob_url, is_hidden) and every new table (moderation_decisions, reports, reported_csam) should land in Postgres, not in the retiring SQLite volume. Doing this before Blob and moderation avoids wasted schema work on a storage layer about to be discarded.
**Delivers:** asyncpg pool in db.py; Alembic async migrations; full v1.0 demo flow running on Neon Postgres; sqlite_to_postgres.py one-shot dump+load utility; reported_csam table (CSAM legal requirement) in first migration.
**Stack:** asyncpg 0.30.x, Alembic 1.18.4 async template. No SQLAlchemy ORM. BYTEA for centroid storage (identical bytes round-trip as BLOB). Neon free tier.
**Files:** backend/db.py (heavy modification), backend/config.py (DATABASE_URL), backend/scripts/sqlite_to_postgres.py (new).
**Pitfalls to avoid:** sync psycopg2 (P0-1); pool sizing — max_size=10, --workers 1 (P0-2); WAL semantics / short-lived sessions per operation (P0-3); Alembic autogenerate read and validated before every commit, compare_type=True (P0-4); hard cutover with re-seed instead of dual-write (P0-5); feature flag METADATA_BACKEND=sqlite|postgres for rollback (P1-17).
**OFFLINE_DEMO gate:** OFFLINE_DEMO=true -> DB layer points at in-memory SQLite; Neon connection never attempted.
**Research flag:** Standard patterns for asyncpg + Alembic async. The CSAM reported_csam schema is Newz-specific — plan-check must verify it is present in migration before merge.

### Phase 3: Vercel Blob Migration
**Rationale:** Blob migration after Postgres so blob_url column exists in the schema. Blob migration before moderation gate because URL-accepting moderation vendors need a stable HTTPS URL as input — without Blob, the moderation worker must read from local disk, the path being retired.
**Delivers:** server-mediated upload (browser -> FastAPI -> Blob); ffmpeg signed-URL trim for _sync_trim; pre-download to tmpdir for _sync_stitch; stitch output uploaded to Blob runs/ prefix; StaticFiles(/media) removed; frontend api.ts updated to use absolute Blob URLs.
**Stack:** vercel Python SDK 0.5.8 (AsyncBlobClient). Public-read bucket with token-required write.
**Files:** backend/blob.py (new), backend/app.py (ingest_clip upload path), backend/pipeline/stitch.py (_sync_trim URL input, _sync_stitch tmpdir download), backend/pipeline/compile.py (_trim_one Blob upload), backend/pipeline/caption_pipeline.py (tmpdir download), frontend/src/api.ts (drop API_BASE prefix).
**Pitfalls to avoid:** never stream HTTPS URLs into ffmpeg concat — download to tempfile.TemporaryDirectory() for stitch (P0-6); server-mediated upload only, never direct browser PUT (P0-7); blob GC job — hard delete on moderation block (P1-18); feature flag STORAGE_BACKEND=local|blob for rollback (P1-17).
**OFFLINE_DEMO gate:** OFFLINE_DEMO=true -> blob.py routes to local FS (v1.0 path); Blob API never called.
**Research flag:** AsyncBlobClient (vercel 0.5.8) released April 22, 2026 — run a spike before planning to confirm API surface. Needs phase research.

### Phase 4: Moderation Gate (parallelizable with Phase 5)
**Rationale:** Depends on Postgres schema (moderation_status columns, moderation_decisions table) and Blob (HTTPS URL for vendor input). Core safety requirement: clips must never enter cluster/compile without passing moderation.
**Delivers:** moderate_clip(clip_id) -> ModerationDecision worker; asyncio.gather(embed_task, mod_task, return_exceptions=True) in run.py; fail-closed on timeout/5xx/429; OFFLINE_DEMO passthrough; newsworthy corroboration path (cluster.distinct_parent_count >= 2 + violence signal -> interstitial flag, not hard block); CSAM hash check via Cloudflare CSAM Scanning Tool.
**Stack:** Gemini 2.5 Flash-Lite via existing google-genai SDK; tenacity 9.x retry wrapper; asyncio.wait_for(mod_task, timeout=10).
**Files:** backend/pipeline/moderate.py (new), backend/pipeline/run.py (gather pattern), backend/db.py (mark_clip_blocked, insert_moderation_decision), backend/config.py (MODERATION_BYPASS, MODERATION_TIMEOUT_S).
**Pitfalls to avoid:** return_exceptions=True + wait_for timeout (P0-8); calibration set run against v1.0 staged demo dataset before enabling (P0-9); moderation provider TOS reviewed for data retention (P2-22); CSAM must be fail-closed (not fail-open); MODERATION_BYPASS=true for local dev.
**OFFLINE_DEMO gate:** moderate_clip returns ModerationDecision(passed=True, label="OFFLINE_DEMO_PASSTHROUGH") without any API call.
**Research flag:** Needs phase research. Cloudflare CSAM Scanning Tool onboarding requires NCMEC approval — check timeline before scheduling. Gemini Flash-Lite latency benchmark on actual demo dataset needed (current estimate extrapolated). Moderation vendor TOS data-retention review required.

### Phase 5: Reactive Report Flow (parallelizable with Phase 4)
**Rationale:** Depends only on Postgres schema (reports table, segments.is_hidden column). Independent of moderation gate. Can be built in parallel with Phase 4.
**Delivers:** POST /report endpoint (anonymous, no session_uuid on row); GET /admin/reports and POST /admin/reports/{id}/action (token-guarded JSON endpoints); hide-segment and hide-and-block-clips admin actions; admin queue with inline clip playback; report deduplication via UNIQUE(segment_id, reporter_ip_hash); rate limit 10 reports/min/IP (IP hashed, not stored).
**Files:** backend/app.py (report + admin endpoints), backend/db.py (insert_report, list_reports, hide_segment, fetch_recent_segments WHERE NOT is_hidden), backend/models.py (ReportRequest), frontend/src/components/SegmentCard.tsx (Report button), frontend/src/api.ts (postReport).
**Pitfalls to avoid:** reports table MUST NOT carry session_uuid (P0-10); IP hash with daily rotation key, not stored on row; X-Forwarded-For stripped in middleware; brigading defense in schema (UNIQUE constraint) before admin UI is built (P0-11); admin queue must embed clip playback (P1-20); auto-hide on report count alone is never triggered without corroborating classifier signal.
**OFFLINE_DEMO gate:** No OFFLINE_DEMO considerations — purely Postgres + in-process logic.
**Research flag:** Standard patterns. No external service integration.

### Phase 6: Observability Deepening
**Rationale:** Ship after Phases 2-5 so spans wrap the final pipeline shape, not throwaway code that gets rewritten. Phase 1 gave error visibility; Phase 6 gives trace flamegraphs and dashboards for the complete v1.1 pipeline.
**Delivers:** OTel context capture before asyncio.create_task and attach inside pipeline coroutine; Logfire instrument_anthropic() for per-subagent token spans; span-wrapping for embed, moderate, cluster, compile, stitch stages; Grafana Cloud dashboard; alert rules for error rate, moderation block rate, compile timeout rate.
**Stack:** Pydantic Logfire instrument_fastapi, instrument_sqlalchemy, instrument_anthropic; opentelemetry-instrumentation-asyncio for create_task context propagation.
**Pitfalls to avoid:** OTel context lost across create_task — implement otel_context.get_current() capture pattern (P1-13); OTel instrumentation overhead — BatchSpanProcessor, 10% sampling, benchmark p99 within 10% of Phase 1 baseline (P1-19).
**OFFLINE_DEMO gate:** Logfire -> no-op when LOGFIRE_TOKEN absent (set in Phase 1).
**Research flag:** Standard patterns. Logfire instrument_anthropic() is Context7-verified.

### Phase Ordering Rationale

- **Observability first** (not last): half-day cost, unblocks fast debugging of all subsequent phases. Every pipeline failure during Postgres/Blob migration is immediately visible in Sentry rather than requiring Railway log spelunking.
- **Postgres before Blob**: blob_url column must exist in the schema before the Blob upload path writes to it. Schema-on-retiring-storage is wasted work.
- **Postgres before Moderation**: moderation_status, moderation_decisions, and reported_csam tables belong in Postgres. The CSAM legal requirement means these must be in the first migration.
- **Blob before Moderation** (recommended, not hard): URL-accepting moderation vendors need a stable public HTTPS input. Without Blob, moderate_clip must read from local FS — the path being retired.
- **Phases 4 and 5 parallelizable**: moderation gate and reactive report flow share Postgres schema but operate on disjoint columns and code paths.
- **Observability deepening last**: wraps the final pipeline shape. Span instrumentation written before Phase 4/5 would wrap intermediate pipeline code that gets modified.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 3 (Vercel Blob):** AsyncBlobClient (vercel 0.5.8) released April 22, 2026 — bleeding edge. Run a spike before planning to confirm API surface matches ARCHITECTURE.md patterns.
- **Phase 4 (Moderation Gate):** Cloudflare CSAM Scanning Tool onboarding requires NCMEC approval — check timeline before scheduling. Gemini 2.5 Flash-Lite latency benchmark on actual demo dataset (current estimate extrapolated). Moderation vendor TOS data-retention review required.

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (Observability Scaffolding):** Sentry + structlog + prometheus-client are well-documented with multiple verified sources.
- **Phase 2 (Postgres Migration):** asyncpg + Alembic async template are canonical FastAPI patterns. The one Newz-specific item (reported_csam schema) is defined in full in PITFALLS.md.
- **Phase 5 (Reactive Report Flow):** Standard anonymous report endpoint + token-guarded admin JSON API. No external service integration.
- **Phase 6 (Observability Deepening):** Logfire instrument_anthropic() is Context7-verified. OTel context propagation pattern is documented in PITFALLS.md with exact code shape.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified on PyPI/Context7 within the week; pricing pulled from official pages dated Mar-Apr 2026. Two low-confidence items flagged: Gemini Flash-Lite empirical latency (extrapolated) and Hive per-clip pricing (back-of-envelope). |
| Features | MEDIUM-HIGH | HIGH on infra patterns; MEDIUM on moderation policy specifics — citizen-journalism is an awkward middle ground between social UGC and news platforms with little public playbook. CSAM statutory requirement is HIGH confidence (primary legal sources). |
| Architecture | HIGH | Read directly from live backend/ codebase. Every file path and line reference verified at time of research. Two vendor-specific items are MEDIUM: Vercel Blob AsyncBlobClient exact API surface (bleeding edge SDK), and moderation vendor URL-input capability. |
| Pitfalls | HIGH | P0 pitfalls cross-verified across Context7, official docs, and community post-mortems. asyncio.gather cancel semantics, psycopg2 event-loop blocking, OTel context across create_task, and ffmpeg HTTPS re-fetch are all documented multi-source. |

**Overall confidence:** HIGH

### Resolved Conflicts

| Conflict | Decision | Rationale |
|----------|----------|-----------|
| STACK.md recommends SQLAlchemy ORM; ARCHITECTURE.md recommends raw asyncpg | Use raw asyncpg + Alembic only | db.py is 710 lines of hand-written SQL with bespoke patterns. ORM doubles the diff for zero benefit. Alembic for migrations, asyncpg for runtime. |
| STACK.md and ARCHITECTURE.md disagree on Sentry-only vs Sentry+Logfire | Use Sentry + Logfire side-by-side | Logfire instrument_anthropic() shows per-subagent token counts that Sentry cannot. Init order: Logfire first, then Sentry with instrumenter="otel". |
| FEATURES.md recommends Hive; STACK.md recommends Gemini 2.5 Flash-Lite | Use Gemini 2.5 Flash-Lite as inline gate | Same google-genai SDK already in stack; 6x cheaper than Hive; native video. Hive reserved for human review-queue triage if needed. |
| FEATURES.md recommends Cloudflare R2; PROJECT.md commits to Vercel Blob | Use Vercel Blob per PROJECT.md | PROJECT.md is the source of truth. Vercel Blob limitations are manageable: blob GC job covers orphan cleanup; public-read URLs avoid signed-URL refresh complexity. |
| PITFALLS.md P0-8 recommends fail-open with quarantine; ARCHITECTURE.md recommends fail-closed for all failures | Fail-closed on CSAM and timeout; fail-open with quarantine for 5xx outage | CSAM is a statutory requirement. For general classifier 5xx outage, fail-open with moderation_status=unknown surfaces in admin queue without black-holing a live demo. |
| Newsworthy corroboration belongs in Phase 4 vs v1.2 | Ship newsworthy corroboration in Phase 4 | Reuses existing CLUSTERS.distinct_parent_count signal; single conditional in run.py; prevents false positives that would break the core product premise. |
| Pool sizing: asyncpg max_size=10 vs Pitfall 2 warning about worker multiplication | max_size=10, --workers 1, locked in Railway Procfile | With --workers 1, a pool of 10 is well under Neon free tier limit of ~100. Pitfall fires only if someone adds --workers 4. |

### Anonymity Invariants Checklist

Verify in plan-check for every phase that touches the data layer or observability:

- [ ] reports table has no session_uuid column (segment_id, reason_code, freetext, server_timestamp only)
- [ ] IP used for rate limiting is hashed with daily-rotation HMAC key and not stored on any row
- [ ] X-Forwarded-For is stripped in FastAPI middleware before structlog bind_contextvars
- [ ] Sentry: send_default_pii=False, max_request_body_size="never", before_send scrubs session_uuid / gps_lat / gps_lng / blob_url
- [ ] structlog context: bind only session_hash (sha256 of UUID), clip_id, request_id — never raw session UUID or IP
- [ ] Logfire / OTel span attributes: whitelist (stage, clip_id, cluster_id, latency_ms); never session_uuid, IP, GPS
- [ ] Moderation API call: strip GPS, session_uuid, upload timestamp from request payload — send video bytes only
- [ ] Admin queue UI: shows clip, moderation scores, GPS redacted to city-level, report reasons — never uploader session_uuid, IP, exact GPS
- [ ] reported_csam table: no session_uuid; content_preserved_until TIMESTAMPTZ enforces 90-day statutory retention window

### Gaps to Address

- **Gemini 2.5 Flash-Lite latency benchmark**: empirical 1.5-3 s estimate is extrapolated from token throughput metrics, not measured on a 10 s Newz clip. If real p50 exceeds 5 s, the parallel-pipeline latency-hiding claim weakens. Validate with a benchmark on the demo dataset before Phase 4 starts.
- **Vercel Blob AsyncBlobClient API stability**: SDK released April 22, 2026. Run a spike (put/delete/head round-trip) before Phase 3 planning to confirm API surface.
- **Cloudflare CSAM Scanning Tool onboarding timeline**: NCMEC approval required. Unknown lead time. Start the application process before Phase 4 is scheduled.
- **Neon cold-start under pre-warm**: Neon free tier scales to zero after 5 min idle; ~500 ms cold start. Extend the existing Marengo pre-warm heartbeat to issue a SELECT 1 against Neon every 4 min. Validate before Phase 2 cutover.
- **asyncpg + Neon TLS**: Neon requires TLS. Confirm asyncpg DSN includes sslmode=require and does not conflict with pool pre-ping on Railway's network.

## Sources

### Primary (HIGH confidence — Context7-verified)
- /pydantic/logfire — instrument_fastapi, instrument_sqlalchemy, instrument_anthropic, logfire.span patterns
- /getsentry/sentry-python — sentry_sdk.init, FastAPI auto-instrumentation, OpenTelemetry integration, AsyncioIntegration
- /hynek/structlog — bound logger, processor pipeline, ProcessorFormatter for stdlib bridge
- /magicstack/asyncpg — driver capabilities, async API surface, pool sizing

### Primary (HIGH confidence — official docs)
- Vercel Blob server uploads — AsyncBlobClient patterns
- Sentry FastAPI integration docs — auto-detect, AsyncioIntegration, send_default_pii
- Alembic async template env.py — official async migration pattern
- SQLAlchemy 2.0 asyncio docs — create_async_engine, async session patterns
- FFmpeg Protocols Documentation — HTTPS input protocol, -protocol_whitelist
- Logfire vs Sentry comparison (Pydantic official) — recommends running both side-by-side
- Neon plans pricing — Free: 0.5 GB, 191.5 compute-hr
- 18 U.S.C. 2258A — CSAM mandatory reporting statutory text

### Secondary (MEDIUM confidence — community consensus)
- asyncpg + Supabase pooler issue (GitHub) — prepared-statement collision in transaction-pooler mode
- Neon vs Supabase 2026 comparison — branching, cold-start, pricing
- FastAPI + SQLAlchemy 2.0 patterns — production async patterns
- Vercel Blob expiry/TTL community thread — confirms no native lifecycle rules
- Video moderation platform comparison 2026 — Hive, Rekognition, Azure tradeoffs
- Meta adversarial threat reports — brigading and mass-report patterns

### Internal codebase reads (HIGH confidence for v1.0 facts)
- backend/app.py, db.py, pipeline/run.py, pipeline/embed.py, pipeline/cluster.py, pipeline/compile.py, pipeline/stitch.py, pipeline/caption_pipeline.py, events.py
- frontend/src/api.ts
- .planning/PROJECT.md, CLAUDE.md, .planning/MILESTONES.md, .planning/RETROSPECTIVE.md

### Tertiary (LOW confidence — single-source or extrapolated)
- Gemini 2.5 Flash-Lite empirical 1.5-3 s latency on 10 s clip — extrapolated from token throughput; validate before Phase 4
- Hive per-clip pricing ~$0.017/10 s clip — back-of-envelope; verify with Hive sales if Hive is selected
- Vercel Python SDK 0.5.8 AsyncBlobClient full API surface — released April 22, 2026; run spike before Phase 3

---
*Research completed: 2026-04-27*
*Ready for roadmap: yes*
