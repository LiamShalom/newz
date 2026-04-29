# Pitfalls Research

**Domain:** Adding production-readiness (managed Postgres, Vercel Blob, content moderation, anonymous reporting, observability) to an existing single-process async FastAPI monolith with anonymous-by-default UGC and an `asyncio.create_task` AI pipeline.
**Researched:** 2026-04-27
**Confidence:** HIGH for stack-specific pitfalls (Context7 + official docs + community post-mortems agree); MEDIUM for moderation/abuse-pattern pitfalls (industry reporting verified, but project-specific severity is judgment).

Severity legend:
- **P0 — production-stopper.** Will break the demo, lose data, or break anonymity. Must be addressed before flipping the feature on.
- **P1 — quality gate.** Won't break the demo, but will burn an on-call rotation or leak PII at scale. Address before public launch.
- **P2 — nice-to-avoid.** Cleanup/cost/cognitive-load issues. Address opportunistically.

---

## Critical Pitfalls

### Pitfall 1 [P0]: Sync sqlite3 / sync psycopg2 on the async path

**What goes wrong:**
v1.0 used `aiosqlite` correctly, but the migration target (Postgres) has two drivers — sync `psycopg2` and async `asyncpg`. A copy-paste from a SQLAlchemy tutorial pulls in `psycopg2` + `Session` (sync). Each query then blocks the FastAPI event loop. Under low load it "works fine." Under contention, the embed pre-warm task, the SSE broadcast loop, and the compile pipeline all fight for the loop and request latency goes to seconds. Same failure shape that v1.0 avoided by putting Marengo's sync SDK behind `loop.run_in_executor`.

**Why it happens:**
Most FastAPI+Postgres tutorials still show sync SQLAlchemy with `Depends(get_db)`. The async path requires `create_async_engine` + `AsyncSession` + `asyncpg` driver — three things to get right at once.

**How to avoid:**
- Driver: `postgresql+asyncpg://...` (NOT `postgresql://` and NOT `postgresql+psycopg2://`).
- Engine: `create_async_engine(url, poolclass=AsyncAdaptedQueuePool)`. `QueuePool` is not asyncio-compatible — SQLAlchemy will pick `AsyncAdaptedQueuePool` automatically when you use `create_async_engine`, but specifying it makes the contract explicit.
- Session: `async_sessionmaker(engine, expire_on_commit=False)`.
- Lint rule: ban `from sqlalchemy.orm import Session` in repo; allow only `AsyncSession`.
- CI smoke: a test that asserts `inspect(engine).driver == "asyncpg"`.

**Warning signs:**
- p99 request latency rises with concurrent SSE clients.
- `await asyncio.sleep(0)` between DB calls "fixes" a hang (telltale that something blocks the loop).
- `psycopg2` or `psycopg` appears in `requirements.txt`.

**Phase to address:** Postgres-migration phase, day 1. Fix at architecture step before the first Alembic migration runs.

---

### Pitfall 2 [P0]: Connection pool sized for laptop, not for Railway memory budget × Postgres `max_connections`

**What goes wrong:**
SQLAlchemy default is `pool_size=5`, `max_overflow=10` → 15 connections per process. Railway runs one Uvicorn process per instance, but `--workers 4` in the Procfile silently multiplies that to 60. Neon free tier caps connections at ~100; Supabase pooled connection on the free tier caps lower. Pool hits ceiling → `QueuePool limit exceeded` → 503s. Worse: pool exhaustion under SSE long-poll workloads (each open SSE stream holding a session for the duration of the connection) is a documented FastAPI footgun.

**Why it happens:**
Defaults look fine in isolation. The failure mode is the product of (process count) × (pool_size + max_overflow) × (workers) — multiplicative, not additive.

**How to avoid:**
- Pin `--workers 1` on Railway. Single asyncio process is the v1.0 contract; uvicorn workers = process duplication, not asyncio concurrency.
- Size pool against the managed-Postgres ceiling: `pool_size = 5, max_overflow = 10` is plenty for a single-process monolith at this scale.
- Use Neon/Supabase's **pooled** connection string (PgBouncer-fronted, transaction mode) for short queries. Set `poolclass=NullPool` on the SQLAlchemy side when going through PgBouncer transaction mode — otherwise you pool inside a pool.
- **NEVER** hold a DB session for the lifetime of an SSE connection. Acquire → query → release. SSE keeps the HTTP socket open, not the DB session.
- Set `pool_pre_ping=True` to survive Neon's idle-connection scale-to-zero.

**Warning signs:**
- Intermittent `TimeoutError: QueuePool limit of size N overflow M reached`.
- Connection count graph in Neon/Supabase console hugs the ceiling.
- p99 latency cliff at a specific concurrency, not a smooth degradation.

**Phase to address:** Postgres-migration phase, before first deploy. Add Railway memory + Neon connection-count graphs to the observability dashboard so this is visible.

---

### Pitfall 3 [P0]: WAL semantics carried over to Postgres

**What goes wrong:**
SQLite WAL meant readers never blocked writers, and v1.0 leaned on `commit-then-read-immediately` patterns. Postgres has different visibility rules — under `READ COMMITTED` (the default), one transaction's writes are not visible to a concurrent transaction's `SELECT` until commit, *and* a long-running transaction sees a snapshot from its start, not real-time data. The `CLUSTERS` rebuild on startup (v1.0 reads all clips into an in-memory dict) will silently miss rows committed by the embed worker if the rebuild is wrapped in a long-lived session.

**Why it happens:**
SQLite's "everything is one file, WAL serializes" mental model doesn't transfer. Devs assume "I committed, so the next session sees it" without thinking about transaction boundaries.

**How to avoid:**
- Audit every `async with session:` block. Default to short-lived sessions per logical operation, not per request.
- For the `CLUSTERS` rebuild on startup: open one transaction, read once, close — don't reuse the rebuild session for the rest of startup.
- Reads-after-writes (e.g., embed worker writes a row, then SSE broadcaster needs to see it): the broadcaster must use a fresh session, not a session that started before the write.
- Document the isolation level explicitly: `isolation_level="READ COMMITTED"` (default; making it explicit is a checkpoint).

**Warning signs:**
- "Worked locally, fails on staging" where local is SQLite and staging is Postgres.
- Race-condition flakes only under load.
- Logs show a row written by phase N, but phase N+1 reports "not found."

**Phase to address:** Postgres-migration phase, in the schema-port plan-check. Add a "session lifetime per pipeline stage" diagram.

---

### Pitfall 4 [P0]: Alembic autogenerate misses indexes and constraints; baseline generated against wrong DB

**What goes wrong:**
Alembic's `--autogenerate` is well-known to miss CHECK constraints, EXCLUDE constraints, index renames, and partial indexes; it sometimes spuriously drops-and-recreates indexes on every run; PostgreSQL unique constraints backed by indexes can be flagged for removal because Alembic doesn't model "constraint = index" the way Postgres does. If the **baseline** migration is autogenerated against an empty DB but our SQLAlchemy models were authored against SQLite (no Postgres-specific types), the first migration will silently downgrade column types (e.g., `JSON` → `TEXT`) on the production DB.

**Why it happens:**
Devs trust autogenerate and don't read the diff. Hackathon-bred "ship it" reflex carries forward.

**How to avoid:**
- **Read every autogenerated migration before commit.** `alembic revision --autogenerate -m "..."` then `cat versions/<latest>.py` is mandatory.
- Name every constraint explicitly: `UniqueConstraint('col1', name="uq_clips_col1")`. Anonymous constraints break autogenerate diffing.
- Generate the **baseline** against a Postgres instance, never SQLite, even if you're starting from an empty schema.
- Add `compare_type=True` and `compare_server_default=True` to `alembic env.py` config — both are off by default and miss type-narrowing changes.
- For Postgres-specific types (JSONB, ARRAY, TSVECTOR, vector): use `sqlalchemy.dialects.postgresql` imports, not generic `JSON`. Otherwise the migration will create `JSON` (text) instead of `JSONB`.

**Warning signs:**
- Migration file shows `op.drop_index(...)` followed immediately by `op.create_index(...)` for the same index. (Spurious rebuild — fix the comparator before merging.)
- Migration file is empty after `--autogenerate` but you know you changed a model. (Detection failure.)
- Production query plan worse than dev. (Index didn't get created.)

**Phase to address:** Postgres-migration phase, before first `alembic upgrade head` against Neon.

---

### Pitfall 5 [P0]: Cutover dual-write window drops or duplicates clips

**What goes wrong:**
The "safe" cutover plan is: deploy code that writes to BOTH SQLite and Postgres, backfill old SQLite rows into Postgres, then flip reads to Postgres, then drop SQLite. Failure modes during the dual-write window:
- Writer crashes between SQLite write and Postgres write → SQLite has a row Postgres doesn't.
- Backfill races with live writes → backfill's `INSERT` collides with live writer's `INSERT` for the same `clip_id`.
- Reader still on SQLite serves stale data after Postgres has the truth.

For Newz specifically, dropping a clip means dropping a member of a cluster — and clustering is composite-score, so a missing row silently changes the cluster identity downstream.

**Why it happens:**
Dual-write is "obviously safe" until you run it under load. The hackathon-scale code (no transactions across stores, fire-and-forget pipeline) makes atomicity guarantees hard.

**How to avoid:**
- **Don't dual-write.** v1.0 demo dataset is small (~tens of clips, regenerable from `seed_demo.py`). Schedule a 5-minute maintenance window:
  1. `POST /admin/reset` to clear SQLite.
  2. Deploy the Postgres-only code.
  3. Re-seed via `seed_demo.py`.
- If dual-write is unavoidable for a real dataset: writes go through a single function that uses `INSERT ... ON CONFLICT (clip_id) DO UPDATE` on Postgres with a `last_modified` timestamp comparison (the Paxos pattern). And put the dual-write inside an outbox table, not inline.
- Backfill in a separate process with `WHERE clip_id NOT IN (SELECT clip_id FROM clips)` and explicit `SERIALIZABLE` isolation.

**Warning signs:**
- Cluster member counts drift between two consecutive `GET /debug/clusters` calls.
- SSE broadcasts a segment that references a `clip_id` not in the DB.
- Backfill log shows duplicate-key errors that "are fine because we ignore them."

**Phase to address:** Postgres-migration phase. Lock the cutover plan in the plan-check before writing migration code. **Recommendation: skip dual-write entirely; do a hard cutover with re-seed.**

---

### Pitfall 6 [P0]: ffmpeg can't reliably stream-concat from HTTPS signed URLs; download to /tmp fills the disk

**What goes wrong:**
v1.0 reads clips from local FS and concats with `-c copy`. Naive port to Vercel Blob: pass `https://...signed-url...` directly to ffmpeg's concat demuxer. Three failures:
1. ffmpeg's concat demuxer needs `-protocol_whitelist file,http,https,tcp,tls,crypto` AND `-safe 0` — without these it errors out with "Protocol not on whitelist."
2. Long signed-URL query strings get truncated by ffmpeg's internal URL handling (documented HLS bug pattern), turning the URL into an unauthenticated 403.
3. ffmpeg re-fetches the input multiple times during concat (probe + decode passes) → 2-3× the bandwidth, 2-3× the latency, breaks the 300s compile budget.

The fallback — download all clips to `/tmp` first — works locally but on Railway with multiple concurrent compiles fills `/tmp` (Railway's tmpfs is small) and causes ffmpeg to fail with `ENOSPC`.

**Why it happens:**
Cargo-culted ffmpeg flags from local-FS dev. Nobody measured re-fetch behavior. Nobody capped concurrent-compile disk usage.

**How to avoid:**
- Always download Blob → bounded scratch dir → ffmpeg → cleanup. **Don't** stream from HTTPS into ffmpeg.
- Use a per-compile scratch dir: `tempfile.TemporaryDirectory()` inside the compile coroutine, cleaned up by the context manager even on exception.
- Cap concurrent compiles via `asyncio.Semaphore(N)` where N is sized to fit `(N × max_cluster_size × max_clip_bytes) < /tmp budget`.
- Stream the download with `httpx.AsyncClient` + `iter_bytes()`, not `response.content` (don't load 50MB into memory per clip).
- Sign URLs with TTL ≥ `compile_budget + slow_mobile_download_margin` — recommend `TTL = 600s` for the backend's own use; client-facing playback URLs can be shorter (60-120s).

**Warning signs:**
- ffmpeg log shows the same input URL fetched twice.
- Compile p99 latency 2-3× what stitch alone takes.
- `df -h /tmp` over 80% on Railway during peak.
- ffmpeg returns "403 Forbidden" or "EOF" mid-concat.

**Phase to address:** Vercel-Blob-migration phase. Add a "scratch dir lifecycle + concurrent compile cap" to ARCHITECTURE.md.

---

### Pitfall 7 [P0]: Direct browser-to-Blob upload skips backend validation

**What goes wrong:**
Vercel Blob's "client upload" flow has the browser PUT directly to Blob storage. Faster, less backend bandwidth. But this skips the v1.0 backend's MIME-type sniff, size cap, and (in v1.1) the moderation gate trigger. Adversarial uploader posts a 500MB MOV that bypasses the 50MB cap, never gets moderated because no backend code ran, then enters the cluster as a "trusted" parent.

**Why it happens:**
The Vercel Blob "client upload" example in the docs is deliberately optimistic. Cost-saving on egress hides the validation gap.

**How to avoid:**
- For v1.1: **server-upload only.** Browser POSTs to `/clips` (multipart), backend validates + uploads to Blob + writes Postgres + kicks off pipeline. Adds backend bandwidth cost; that cost is a feature (it gives us the validation chokepoint).
- If client-upload is required for cost reasons later: use Vercel's `handleUpload` callback pattern — the browser still hits the backend first to get a signed token, and the backend can refuse based on session-level checks. Then a `onUploadCompleted` webhook on the backend triggers the pipeline. Validate in **both** the token-issue step (size header, content-type header) and the webhook (actual blob metadata).
- Always set Vercel Blob `addRandomSuffix: true` to prevent path collisions.
- Set `cacheControlMaxAge` on uploaded blobs explicitly (default is 1 year — fine for clips, but be intentional).

**Warning signs:**
- Blob storage shows files larger than the documented size cap.
- Pipeline starts running on a blob the backend never logged.
- `clip_id`s in Blob that don't exist in Postgres.

**Phase to address:** Vercel-Blob-migration phase, before flipping the upload path. Plan-check must include "where does the size cap get enforced?"

---

### Pitfall 8 [P0]: Moderation classifier's outage blocks the entire pipeline

**What goes wrong:**
v1.1 plan: moderation runs **in parallel** with Marengo embed (good — no added latency in the common case). But naive `asyncio.gather(embed, moderate)` re-raises the first exception, cancelling the embed task. Moderation provider has a hiccup → embed gets cancelled mid-Marengo-call → Marengo retry budget eaten → pipeline fails for content that was never going to be unsafe anyway.

Worse: classifier with no timeout will hang the pipeline indefinitely if the provider is silently slow rather than returning an error.

**Why it happens:**
`asyncio.gather` semantics are subtle. `return_exceptions=False` (default) cancels siblings on first error. Most tutorials don't cover this.

**How to avoid:**
- `asyncio.gather(embed, moderate, return_exceptions=True)`. Inspect both results separately.
- Wrap moderation call in `asyncio.wait_for(..., timeout=MODERATION_TIMEOUT_SECONDS)`. Recommend timeout = 0.5 × Marengo p99 (so moderation can't dominate the parallel branch).
- **Safe-default policy must be locked before code is written.** Two viable defaults:
  - **Fail-open** (publish if moderation fails): minimizes UX damage; widens trust window.
  - **Fail-closed** (block if moderation fails): minimizes content risk; could black-hole a live demo if the provider goes down.
  - Recommended for Newz: **fail-open with quarantine** — publish to feed but mark `moderation_status = 'unknown'`, surface in admin queue for retroactive review.
- Circuit breaker: if moderation fails N times in M seconds, automatic switch to fail-open + alert, don't keep hammering.

**Warning signs:**
- Pipeline stage timing histogram shows moderation latency dominating embed latency.
- Embed retry rate spikes when moderation provider has issues.
- `moderation_status = 'unknown'` rows accumulate without admin attention.

**Phase to address:** Moderation phase. Lock fail-open-vs-fail-closed in the requirements doc before plan-check.

---

### Pitfall 9 [P0]: False positives on legitimate news/protest footage

**What goes wrong:**
Generic content classifiers flag legitimate journalism. Documented Meta Oversight Board case: a cartoon depicting police violence in Colombia was wrongly added to a Media Matching Service bank, mass-removed across the platform. Amazon Rekognition can't distinguish a prop firearm from a brandished one — context blind. For Newz specifically, *crowd-sourced footage of protests, accidents, or breaking news is the core use case*, and these are exactly the categories most likely to false-positive.

If the classifier blocks 30% of newsworthy uploads, the product premise (multi-angle event clustering) breaks because clusters never get the ≥2-distinct-parents required for compile.

**Why it happens:**
Classifiers are trained on consumer-platform safety taxonomies (Twitter/Instagram/TikTok), where "violence" is bad. News-platform taxonomies need "violence in journalistic context" → allowed.

**How to avoid:**
- **Don't use a single binary classifier.** Use category-level scores (violence, gore, sexual, hate, weapons) and tune per-category thresholds.
- For violence/weapons categories specifically: ship with **lenient thresholds + admin review for medium-confidence cases**, not auto-block. Admin queue is the safety net.
- Run a **calibration set** against the v1.0 staged demo dataset before going live. Define a regression test: "X% of staged clips must pass." If staged news footage fails, the threshold is wrong.
- Carry forward v1.0 lesson: **calibration is anchored to specific inputs.** When you change moderation provider OR threshold, re-run the calibration set.
- Document the moderation taxonomy in PROJECT.md so a takedown decision is defensible later.

**Warning signs:**
- Compile rate (compiles per hour) drops sharply after moderation enables.
- Cluster size distribution shifts toward 1-parent (singleton) clusters.
- Admin queue floods with "this is news" appeals (assuming we build appeal UI).

**Phase to address:** Moderation phase, before flipping the gate on. Treat staged demo dataset as the calibration set, the way Phase 3 used CLU-07/CLU-08.

---

### Pitfall 10 [P0]: Anonymity broken because reporter session UUID is linkable to upload session UUID

**What goes wrong:**
Anonymous "report" UI calls `POST /reports` with `session_uuid` (current convention from v1.0 localStorage). Admin queue stores `(reported_clip_id, reporter_session_uuid)`. Now you can correlate: same session_uuid uploaded clip A and reported clip B → same person. Cross-reference against IP logs (Railway has access logs by default), and the anonymity claim is false even though there's no "account."

This is the kind of failure that **doesn't break in tests**, **doesn't break in prod**, and **only breaks when a journalist or court asks "do you know who reported this?"** — and the answer is "yes, indirectly, against our claim."

**Why it happens:**
Hackathon habit: pass `session_uuid` everywhere because it's easier to debug. Privacy is a code-review concern, not a runtime one.

**How to avoid:**
- **Reports MUST NOT carry session_uuid.** A report is `(clip_id, reason_code, optional_freetext, server_timestamp)`. Period.
- Rate-limit reports per IP (not per session) and **drop the IP after the rate-limit decision is made** — don't store it on the report row.
- Strip `X-Forwarded-For` from request logs at the FastAPI middleware layer. Railway access logs: route through a log middleware that drops the source IP before shipping to the log aggregator.
- Audit `Sentry` integration — `send_default_pii=False` is the default, but verify; Sentry-FastAPI middleware does NOT capture IP by default.
- Tracing/spans MUST NOT carry session_uuid. If you need to correlate spans across a single user's pipeline, generate a fresh per-pipeline UUID server-side that's never exposed to the client.

**Warning signs:**
- Code review finds `session_uuid` in any of: reports table, logs, Sentry tags, OTel attributes, metrics labels.
- Database schema review shows a foreign key from `reports` to `sessions`.
- Privacy policy says "anonymous" but `EXPLAIN` of the admin-queue query reveals you can join reports → clips → uploader's session_uuid.

**Phase to address:** Reactive-report phase, in the requirements doc. **Block plan-check** until the privacy invariant is written down explicitly.

---

### Pitfall 11 [P0]: Brigading / mass-report attacks crush the admin queue

**What goes wrong:**
Coordinated group reports the same `clip_id` 1000 times in 10 seconds. Three failure modes:
1. Admin queue UI shows 1000 rows for the same clip → reviewer can't see the actual queue depth.
2. Naive auto-action ("if N reports → auto-hide") = trivially weaponized to suppress real news.
3. Reports table grows unbounded → DB cost explosion.

Documented at scale by Meta's Adversarial Threat Reports: mass-reporting and brigading are well-understood adversarial patterns. Newz's anonymity-by-default makes us *more* vulnerable than account-based platforms because there's no reputation signal.

**Why it happens:**
Naive design treats reports as votes. At scale, reports are an attack surface.

**How to avoid:**
- Dedupe at write time: `UNIQUE (clip_id, reporter_ip_hash)` where `reporter_ip_hash = HMAC(clip_id, ip)` (per-clip hash so the IP can't be reversed across the table; clip-scoped uniqueness so one IP can report each clip once).
- Show admin queue grouped by `clip_id`, not flat. `count(*)` per clip is signal; raw rows are noise.
- **Never auto-hide based on report count alone.** Auto-hide on count requires a corroborating signal (moderation classifier flagged the same clip, OR a trusted-reviewer manual flag).
- Rate limit at the network edge (Vercel Edge or Railway middleware): max 10 reports/min/IP. Burst above that → 429.

**Warning signs:**
- Admin queue depth grows faster than upload volume.
- Same `clip_id` appears in the queue with 100+ reports in <1 hour.
- Single IP responsible for >5% of reports in any hour.

**Phase to address:** Reactive-report phase, before the admin queue UI is built. Brigading defense must be in the schema, not in the UI.

---

### Pitfall 12 [P1]: Sentry captures request bodies → clip URL or moderation context leaks

**What goes wrong:**
Sentry's FastAPI integration captures request data on errors. Default is `send_default_pii=False` (good), but request bodies are still captured for non-form-data POSTs unless explicitly disabled. If `/clips` upload errors, Sentry gets the multipart body (the clip itself in worst case, or its blob URL). If `/reports` errors, Sentry gets the report body. If a moderation webhook errors, Sentry gets the moderation provider's full response (may include the provider's content snippets / sanitized text excerpts).

**Why it happens:**
Sentry defaults are conservative for cookies/headers but more permissive for bodies. The "default safe" reputation lulls devs into not checking.

**How to avoid:**
- Set `max_request_body_size="never"` in `sentry_sdk.init(...)`. Disables body capture entirely.
- Set `send_default_pii=False` (default, but make it explicit).
- Add a `before_send` hook that scrubs known fields by name: `session_uuid`, `ip`, `gps_lat`, `gps_lng`, `signed_url`, `blob_url`.
- Document the scrubber as part of the v1.1 privacy invariant.
- Periodically (monthly) audit a sample of Sentry events for unscrubbed PII.

**Warning signs:**
- Sentry event detail shows `body: {...}` with content.
- A field that should be PII (gps_lat) is visible in Sentry tags or breadcrumbs.

**Phase to address:** Observability phase, before Sentry is enabled in production.

---

### Pitfall 13 [P1]: OpenTelemetry context lost across `asyncio.create_task` → orphaned compile spans

**What goes wrong:**
v1.0's pipeline contract is `POST /clips → asyncio.create_task(embed_then_cluster_then_compile)`. Naive OTel instrumentation traces the request handler — span ends when the handler returns 202. The `create_task` coroutine runs in a *new* asyncio task, and **`Task` does copy contextvars at creation time**, BUT only if the task is created inside an active span context. If the handler spawns the task and returns, then the span closes, then the task starts executing — by that time the span is closed, child spans become orphaned roots in the trace UI.

Result: the trace dashboard for "what happened to clip X" shows the upload, then nothing — embed/cluster/compile are visible only as separate, parentless traces.

**Why it happens:**
Subtle interaction between three things: span context lifetime, `asyncio.Task` contextvar capture timing, and the fire-and-forget pattern. Each is documented in isolation; the combination is not.

**How to avoid:**
- Inside the request handler, **start a long-lived span before** `asyncio.create_task`, and pass the context explicitly:
  ```
  ctx = otel_context.get_current()
  task = asyncio.create_task(_pipeline_with_context(ctx, clip_id))
  ```
  where `_pipeline_with_context` does `token = otel_context.attach(ctx); try: ... finally: otel_context.detach(token)` at entry.
- Or: use the official `opentelemetry-instrumentation-asyncio` package (it patches `create_task` to copy context). Verify by tracing a test pipeline end-to-end and confirming embed/cluster/compile are children of the upload span.
- Span hierarchy assertion in CI: spawn a fake clip, query the OTel test exporter, assert `compile_span.parent == upload_span.id`.

**Warning signs:**
- Trace UI shows an upload span with no children, even though logs prove the pipeline ran.
- Pipeline-stage spans appear as standalone root traces.
- Distributed tracing dashboards show "upload latency" that's just the sync ingest, missing 99% of pipeline work.

**Phase to address:** Observability phase, in the OTel instrumentation plan. Bake span propagation into a wrapper utility used by every `create_task` call site.

---

### Pitfall 14 [P1]: Metrics cardinality blows up — clip_id / session_uuid / cluster_id as labels

**What goes wrong:**
Naive instrumentation: `pipeline_stage_duration_seconds{stage="embed", clip_id="..."}`. Each unique `clip_id` creates a new time series. Prometheus / managed metrics backends bill per-series per-month. At 10K clips, that's 10K series for one metric — not catastrophic, but `clip_id × stage × pod_id × status` multiplies fast. Documented antipattern: per-id labels are the #1 cardinality bomb.

For Newz: `cluster_id` rotates frequently as clustering recomputes; `session_uuid` is per-user. Either as a label = unbounded growth.

**Why it happens:**
Devs want to slice metrics by ID to debug. Ergonomic for debugging, expensive for the metrics system.

**How to avoid:**
- Allowed labels: `stage`, `status` (success/error/timeout), `route`, `method`. Bounded sets, low cardinality.
- **Forbidden labels:** `clip_id`, `cluster_id`, `session_uuid`, `ip`, `user_agent`, `gps_lat`, `gps_lng`.
- For ID-level debugging, use **logs and traces**, not metrics. The split is: metrics = aggregate, traces = per-request, logs = per-event.
- Add a metrics-cardinality budget alert: if total unique series > N, page on-call. Catches accidental label additions.

**Warning signs:**
- Metrics-backend dashboard shows "active series" growing linearly with traffic.
- Bill from metrics provider grows month-over-month without traffic growth.
- Grafana queries timeout because the series count is too high.

**Phase to address:** Observability phase, in the metrics-schema plan-check. Lock the allowed-label list before instrumenting code.

---

### Pitfall 15 [P1]: OFFLINE_DEMO mode broken by new external dependencies

**What goes wrong:**
v1.0's `OFFLINE_DEMO=true` serves cached embeddings + cached compile output, no external API calls. v1.1 adds: Postgres (network), Vercel Blob (network), moderation API (network), Sentry (network), OTel collector (network). Naive integration: each of these gets initialized at startup unconditionally. `OFFLINE_DEMO=true` no longer means "no network" — it means "no Twelve Labs and no Anthropic, but yes Postgres and yes Vercel Blob and yes moderation."

If the demo machine has no internet, demo dies at startup because Neon connection times out.

**Why it happens:**
OFFLINE_DEMO was designed against v1.0's two external deps. New deps don't get retrofitted.

**How to avoid:**
- Define the OFFLINE_DEMO contract explicitly in `.planning/PROJECT.md`: when `OFFLINE_DEMO=true`:
  - Postgres → in-memory SQLite fallback (or skip schema entirely; load demo dataset from JSON).
  - Vercel Blob → local FS fallback (the v1.0 path).
  - Moderation → fail-open with `moderation_status = 'offline-demo-passthrough'`.
  - Sentry → disabled (`dsn=None`).
  - OTel exporter → no-op exporter.
- Add a CI test: `OFFLINE_DEMO=true python -c "import app; app.startup()"` with **the network firewalled** at the OS level (e.g., via `unshare -n`). If startup completes with no errors, OFFLINE_DEMO works.
- Document at top of each new module: `if settings.OFFLINE_DEMO: return _offline_fallback()`.

**Warning signs:**
- Startup log on a no-network machine shows DNS resolution errors.
- `OFFLINE_DEMO=true` flag is set but pipeline still calls external APIs (visible in logs).

**Phase to address:** Every phase that introduces a new external dependency. Plan-check must answer "what does this look like under OFFLINE_DEMO?"

---

### Pitfall 16 [P1]: Schema migration during live deploy → readers see partial schema

**What goes wrong:**
Standard Railway deploy: new code starts, old code stops, gap of seconds. If the new code runs `alembic upgrade head` at startup AND the migration adds a column the new code reads, there's a window where:
- New code (instance N+1) starts → runs migration → new column exists.
- Old code (instance N) is still serving requests → still selects without the new column → fine.
- BUT: if the migration removes a column or renames one, old code sees missing column on a read → crash.

The Newz pipeline is fire-and-forget — a request taking 30s to complete (compile pipeline) can span the deploy boundary. Pipeline started against old schema, finishes against new schema.

**Why it happens:**
Devs treat deploy as atomic. It's not.

**How to avoid:**
- **Expand-contract migrations.** Never remove a column in the same deploy as the code that stops using it. Process:
  1. Deploy 1: add new column, code writes both old + new.
  2. Backfill new column.
  3. Deploy 2: code reads new column.
  4. Deploy 3: stop writing old column.
  5. Deploy 4: drop old column (only after monitoring confirms no readers).
- For Newz's small deploys: schedule schema-changing deploys during a quiet window and use `POST /admin/reset` to drain pipeline state if needed.
- **Don't run `alembic upgrade head` from app startup in production.** Run migrations as a separate Railway job before the app deploys. Otherwise app health-check fails during long migrations.

**Warning signs:**
- Deploy log shows app instance starting *and* running migrations *and* serving traffic.
- "Column does not exist" errors immediately after deploy.
- In-flight pipeline requests fail with schema mismatches during deploy.

**Phase to address:** Postgres-migration phase, in the deploy-process plan. Document the expand-contract rule once, apply it forever.

---

### Pitfall 17 [P1]: Cross-service rollback impossible — Postgres + Vercel Blob deploy can't be atomic

**What goes wrong:**
Deploy day: ship new code that uses Postgres + Blob. Postgres migration succeeds. Blob token wrong. App boots half-broken: writes to Postgres succeed, blob uploads 401. Pipeline fires → embed succeeds → compile fails because clip not in Blob. Now Postgres has rows pointing to non-existent blobs. Roll back the code → old code expects local FS → reads fail. Roll back the migration → the rows added by the half-broken deploy are now in a downgraded schema → silent data corruption.

**Why it happens:**
Two stateful services + one stateless service = no atomic rollback. Industry-standard problem.

**How to avoid:**
- **Feature flags, not big-bang deploys.** Add `STORAGE_BACKEND=local|blob` env. Default `local` until Blob is proven. Flip per-instance.
- Same for Postgres: `METADATA_BACKEND=sqlite|postgres`. v1.0 code path stays in repo behind a flag. (Carry forward v1.0 lesson: keep the old path until the new path is verified.)
- Document a rollback runbook before deploy:
  1. Flip `STORAGE_BACKEND=local` (no redeploy needed).
  2. App resumes on local FS.
  3. Postgres rows pointing to Blob are quarantined, not deleted.
- Health check that exercises both deps: `GET /healthz` writes a sentinel row to Postgres + uploads a sentinel blob. Returns 503 if either fails. Railway won't promote a failing instance.

**Warning signs:**
- Deploy succeeds but health check reports degraded.
- Postgres rows reference blob URLs that 404.
- Code path "STORAGE_BACKEND=local" was deleted (no rollback option).

**Phase to address:** Postgres-migration AND Vercel-Blob-migration phases. Feature flag must exist before the migration code is merged.

---

### Pitfall 18 [P1]: Forgotten blob cleanup → orphaned blobs accumulate cost

**What goes wrong:**
Failure paths leave orphaned blobs:
- Upload succeeds → moderation blocks → blob never used, never deleted.
- Upload succeeds → embed fails → blob never enters cluster, never used, never deleted.
- Compile produces a stitched output → cluster invalidated by new clip → old stitch never deleted.
- `POST /admin/reset` wipes Postgres but doesn't wipe Blob.

Vercel Blob bills per-GB-stored. At 50MB clips, 1000 orphans = 50GB. Bill goes up monthly even with zero traffic.

**Why it happens:**
Cleanup is a cross-cutting concern, owned by no specific code path. Hackathon-bred "we'll deal with it later."

**How to avoid:**
- **Reference counting via DB.** `blob_url` column in Postgres `clips` table is the source of truth. Anything in Blob not referenced by a clips row is orphaned.
- **Periodic GC job.** Once a day: list all blob keys, diff against `SELECT blob_url FROM clips`, delete the difference. Run as a Railway scheduled task, gate by `--dry-run` for the first week.
- **Hard delete on moderation block.** Moderation = block → `await blob.delete(url)` synchronously, before the failure response.
- **Update `POST /admin/reset` to wipe Blob too.** Token-guarded, irreversible, but consistent.
- Track blob count + total bytes as a metric. Alert if growth rate diverges from clips-table growth rate.

**Warning signs:**
- Vercel Blob storage size grows faster than Postgres `clips` row count.
- `POST /admin/reset` followed by Blob list shows non-zero blobs.
- Moderation-blocked clips visible in Blob storage.

**Phase to address:** Vercel-Blob-migration phase. GC job must exist before launch, even if it runs in dry-run mode for the first week.

---

### Pitfall 19 [P1]: OTel instrumentation overhead degrades p99 latency

**What goes wrong:**
Auto-instrumentation libraries (`opentelemetry-instrumentation-fastapi`, `-sqlalchemy`, `-httpx`) wrap every call. Synchronous span context manipulation, attribute serialization, batch export — all on the hot path. v1.0 baseline was tuned tight (compile budget = 300s already eats most of the headroom). Adding 10ms per stage × 6 stages = 60ms overhead, which sounds fine until you notice the OTel batch span exporter blocks on a full queue.

**Why it happens:**
OTel libraries have improved a lot but are still not zero-cost. Default `BatchSpanProcessor` queue size + flush behavior can starve the event loop briefly.

**How to avoid:**
- Use `BatchSpanProcessor` (NOT `SimpleSpanProcessor` — that's synchronous). Tune queue: `max_queue_size=2048, max_export_batch_size=512, schedule_delay_millis=5000`.
- Sample. `TraceIdRatioBased(0.1)` = 10% sampling. For Newz at low traffic, full-sample is fine; at scale, drop to 1-10%.
- Don't auto-instrument everything. Instrument: FastAPI route handlers, the pipeline stages (manually, with explicit span names), the Twelve Labs/Anthropic/Gemini API calls. **Don't** instrument every `await` inside a coroutine.
- Benchmark before/after. v1.0 had `~0.8s p50 stitch`. After OTel, re-measure. If regression > 10%, back off instrumentation.
- Make OTel exporter URL configurable; in OFFLINE_DEMO point at a no-op exporter.

**Warning signs:**
- p99 pipeline latency regresses after enabling tracing.
- Periodic latency spikes correlated with OTel batch flushes.
- Memory growth correlated with OTel queue depth.

**Phase to address:** Observability phase. Benchmark gate in plan-check: "post-instrumentation p99 must be within 10% of pre-instrumentation."

---

### Pitfall 20 [P1]: Admin queue UI built without preview — reviewer can't tell context

**What goes wrong:**
Admin queue lists report rows: clip_id, reason, count. Reviewer clicks "block" or "approve" without watching the clip, because the UI doesn't preview it inline. Easy mistake → wrongful takedown of legitimate news → reputational risk that anonymous-by-default cannot defend against (no recorded uploader to apologize to).

**Why it happens:**
"Admin tools are internal, ship fast" mindset. UI iterations skip the design review that customer-facing UI gets.

**How to avoid:**
- Admin queue MUST embed clip playback (HTML5 video tag against signed Blob URL). No "click to download" friction.
- Show: clip itself, AI moderation scores per category, GPS coordinates redacted to ~city level, upload timestamp, report reasons grouped + counted.
- DO NOT show: uploader's session_uuid, IP, exact GPS. The reviewer's job is "is this content safe to publish," not "who uploaded it."
- Audit log every admin action: `(admin_id, clip_id, action, reason, server_timestamp)`. Even though we have no user accounts, the admin SHOULD have an account — not anonymous.
- Build an "appeal queue" later (v1.2+). v1.1 just needs the audit log so future appeals are defensible.

**Warning signs:**
- Admin actions disproportionately "block" without clip preview engagement (analytics on admin UI: time spent on each row).
- Admin takedowns of clips that turn out to be newsworthy.
- No audit trail when asked "why did you take this down?"

**Phase to address:** Reactive-report phase, in the admin-UI requirements.

---

### Pitfall 21 [P2]: Adversarial probing of moderation classifier

**What goes wrong:**
Adversary uploads borderline content repeatedly with small variations to map the classifier's decision boundary. Once mapped, they craft uploads that pass the gate but are unsafe. v1.0 has no abuse-control infrastructure (deferred to v1.2 per PROJECT.md), so this is feasible without rate limits.

**Why it happens:**
Anonymity-by-default + no rate limits = unlimited free queries against the classifier.

**How to avoid:**
- v1.1: at least IP-based rate limit on `/clips` (10 uploads/min/IP). Not abuse control proper, but raises the cost of probing. Note this is in tension with anonymity — IPs are PII. Hash the IP, store only the hash with a daily rotation key.
- Random small noise on the classifier threshold per-request (e.g., threshold ± 0.02) so probing doesn't get a deterministic boundary.
- Log moderation decisions to a separate, retention-limited store (auto-delete after 30d). If adversarial pattern detected (many borderline-uploads from one IP hash), trigger admin review.
- Defer real abuse controls to v1.2 per PROJECT.md. This is a known limitation; document it.

**Warning signs:**
- Many uploads from one IP hash that cluster near the moderation threshold.
- Classifier's distribution of confidence scores becomes bimodal (clearly safe + clearly borderline).

**Phase to address:** Acknowledged in v1.1 PITFALLS as deferred to v1.2. Surface in PROJECT.md "known limitations."

---

### Pitfall 22 [P2]: Moderation provider's data retention terms violate anonymity-by-default

**What goes wrong:**
Most moderation APIs retain the submitted media for some period for retraining. Even if our database has no PII, the moderation provider's database has all our clips with their GPS metadata if we passed it along. Worse, some providers retain logs that include the requester IP. Anonymity-by-default at our database doesn't extend to upstream providers.

**Why it happens:**
Devs don't read provider TOS. "Compliance is someone else's problem."

**How to avoid:**
- Read the provider's data-retention TOS before committing. Specifically check: (a) is uploaded media retained? (b) for how long? (c) used for training? (d) is requester IP logged?
- Pick a provider with an explicit "no retention" or "configurable retention = 0" mode. Many enterprise tiers offer this.
- Strip metadata before sending: NEVER send GPS, session_uuid, or upload timestamp to the moderation API. Just the video bytes.
- If sending video bytes is itself a problem, consider on-device or self-hosted classifier (Caltech NSFW models, etc.). v1.1 likely needs hosted; document the tradeoff.

**Warning signs:**
- Provider TOS mentions "we may use submitted content to improve our models."
- Provider's API takes optional fields like `user_id` or `session_id` (signal that they correlate across requests).

**Phase to address:** Moderation phase, in the provider-selection plan-check. Block plan-check if the TOS is unclear.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Sync `psycopg2` "just to ship the migration" | Faster initial port; fewer async-related bugs | Event loop blocks; latency cliff under SSE concurrency; full rewrite later to async | **Never.** Async-from-day-1 is non-negotiable for this monolith. |
| Skip Alembic, use `Base.metadata.create_all()` | One less moving part | No version control on schema; can't reproduce schema history; can't roll forward/back; data loss on schema drift | Only acceptable in a single-developer prototype that is explicitly disposable. **Not acceptable for v1.1.** |
| `OFFLINE_DEMO=true` only updated for *some* new deps | Faster to ship features | Demo dies on a no-network machine; carry-forward v1.0 lesson lost | Never. Update OFFLINE_DEMO with every new external dep. |
| Direct browser-to-Blob upload | Lower backend bandwidth cost | Validation gap; size cap bypass; moderation skip | Only with handleUpload + onUploadCompleted webhook + double validation. Defer to v1.2. |
| Naive `asyncio.gather(embed, moderate)` | One-line implementation | Moderation flakiness cancels embed; pipeline brittleness | Never. Always `return_exceptions=True` + `wait_for` timeout. |
| Sentry default config | Zero-effort error tracking | Request body capture; PII leak risk | Only after `max_request_body_size="never"` + `before_send` scrubber. |
| Auto-instrument-everything OTel | Easy "look, traces!" | p99 latency regression; cardinality blowup | Only after benchmarking + manual instrumentation of pipeline stages. |
| `clip_id` as a metrics label "for debugging" | Convenient ad-hoc queries | Cardinality bomb; metrics-backend bill explosion | Never. Use traces for per-id slicing. |
| Auto-hide content on N reports | Simple abuse signal | Trivially weaponized; legitimate news suppressed | Only with corroborating signal (classifier + reports). |
| Skip blob cleanup in v1.1, "audit later" | Faster phase close | Storage cost grows linearly with failed uploads | Never. GC job in dry-run mode is acceptable; absent GC is not. |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **Neon/Supabase Postgres** | Use direct connection from FastAPI | Use pooled (PgBouncer transaction-mode) connection string + `poolclass=NullPool` on SQLAlchemy side; use direct connection only for migrations. |
| **Neon/Supabase Postgres** | Forget Neon's idle-scale-to-zero | Set `pool_pre_ping=True` and tolerate 1-2s reconnect on first query after idle. |
| **Vercel Blob** | Pass HTTPS URL directly to ffmpeg | Always download → scratch dir → ffmpeg → cleanup. Use `httpx` streaming download. |
| **Vercel Blob** | Forget `addRandomSuffix: true` | Always set it. Path collisions silently overwrite. |
| **Vercel Blob** | Sign URL with TTL = 30s | TTL ≥ compile budget + slow-mobile-margin. Recommend 600s for backend, 60-120s for client playback. |
| **Moderation API** | Default to fail-closed without thinking | Decide fail-open vs fail-closed before code; for Newz, fail-open + quarantine. |
| **Moderation API** | Send GPS / session_uuid alongside video | Send video bytes only; strip metadata before HTTP request. |
| **Moderation API** | Use single binary "safe/unsafe" output | Use category-level scores; tune per category against staged calibration set. |
| **Sentry** | Default request body capture | `max_request_body_size="never"` + scrubbing `before_send` hook. |
| **Sentry** | Capture session_uuid in tags for "debugging" | Never tag PII. Use a per-pipeline correlation ID generated server-side. |
| **OpenTelemetry** | Spawn `asyncio.create_task` outside span context | Capture `otel_context.get_current()` BEFORE create_task; attach inside the new task. Use `opentelemetry-instrumentation-asyncio` for automatic propagation. |
| **OpenTelemetry** | Use `SimpleSpanProcessor` in production | Always `BatchSpanProcessor`; tune queue size; sample at scale. |
| **Prometheus / metrics** | Use `clip_id` as a label | Bounded labels only; per-id slicing via traces. |
| **Railway deploy** | Run `alembic upgrade head` from app startup | Run as separate Railway job before app deploy; app startup just reads schema, doesn't migrate. |
| **Railway deploy** | `--workers 4` in Procfile | `--workers 1`; single asyncio process is the contract. |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Sync DB driver in async path | p99 latency cliff at moderate concurrency; SSE clients backing up | `asyncpg` only; ban `psycopg2` import | ~10 concurrent SSE clients |
| Connection pool too small for SSE workload | `QueuePool limit exceeded`; 503s | Don't hold sessions across SSE lifetime; size pool against PgBouncer | Any SSE traffic that holds sessions |
| ffmpeg streaming from HTTPS | 2-3× compile latency (re-fetches); ENOSPC on /tmp | Download → scratch dir → ffmpeg → cleanup | Always — don't even start down this path |
| Moderation API blocks pipeline | Time-to-feed regresses; embed cancellations | `wait_for` timeout + `return_exceptions=True` | First moderation provider hiccup |
| Per-id metrics labels | Metrics-backend bill grows linearly with traffic | Bounded label sets | ~1000 unique IDs in label position |
| OTel auto-instrumentation overhead | p99 regression after enabling tracing | Manual instrumentation + sampling + `BatchSpanProcessor` | Any production load |
| Mass-report attack | Admin queue depth explodes; DB write hot-spot | Dedup at write time + edge rate limit | First coordinated attack (could be week 1) |
| Blob cleanup absence | Storage bill grows month-over-month with no traffic growth | Reference-counting GC job | ~1000 failed uploads (single weekend) |
| Synchronous startup tasks | Deploy times out on health check | Pre-warm via `asyncio.create_task` from `lifespan`; never block startup | Any startup task >30s |

---

## Security / Anonymity Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| `session_uuid` on `reports` rows | Anonymity false; reporter ↔ uploader correlation | Reports schema = (clip_id, reason_code, freetext, server_ts). Period. |
| Source IP logged in Railway access logs | PII exfiltration via log aggregator | Strip `X-Forwarded-For` in middleware before log emission. |
| Sentry default `send_default_pii` | IP / cookies / body captured | Verify `send_default_pii=False`; add scrubber `before_send`. |
| OTel span attributes carrying `session_uuid` or `gps` | PII in trace backend (third-party) | Whitelist span attributes; ban PII fields by name. |
| Moderation provider retains uploaded video | PII / content held by third party with worse anonymity guarantees than us | Pick provider with `retain=0` mode; read TOS. |
| Direct browser → Blob upload | Bypasses validation, moderation, size cap | Server-upload only for v1.1; defer client-upload to v1.2. |
| Auto-action on report count alone | Brigading suppression of legitimate content | Auto-action only with corroborating signal (classifier + reports). |
| Admin queue exposing uploader info | Reviewer can correlate; reviewer becomes target | Admin UI shows clip + scores + report reasons; never uploader's session_uuid. |
| GPS stored at full precision | Re-identification (e.g., home address) | Store full precision in DB; redact to city-level for any UI surface (admin or feed); never expose full GPS via API. |
| `POST /admin/reset` token leaks in logs | Attacker can wipe production | Treat token as secret; never log; rotate quarterly. |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Moderation gate blocks during upload (synchronous) | Upload latency regresses; user thinks app is slow | Run moderation in parallel with embed; UI shows "uploaded" immediately. |
| "Your clip was blocked" UX | Anonymous user can't appeal; confused | Don't surface block decisions to the uploader (anonymous = no account to message). Silently quarantine; admin can later un-quarantine. Document as known UX gap. |
| Reporter has to type a freetext reason | Friction → fewer reports → worse signal | Predefined reason codes (multiple-choice) + optional freetext. |
| Admin queue requires download to review | Reviewer fatigue; rushed decisions | Inline video playback in queue UI. |
| "Report submitted" with no confirmation of action | User feels report is ignored | Acknowledgment screen: "report received; queue depth N; expected review time X." Set expectations. |

---

## "Looks Done But Isn't" Checklist

- [ ] **Postgres migration:** Verify driver is `asyncpg`, not `psycopg2`. Verify `--workers 1` in Procfile. Verify `pool_pre_ping=True`. Verify pool size against managed-Postgres ceiling.
- [ ] **Alembic:** Verify autogenerated migration was hand-reviewed. Verify `compare_type=True` and `compare_server_default=True` in env.py. Verify all constraints have explicit names. Verify baseline was generated against Postgres, not SQLite.
- [ ] **Vercel Blob:** Verify ffmpeg never reads from HTTPS directly — always scratch-dir download. Verify scratch dir is per-compile and cleanup-on-exception. Verify `addRandomSuffix=true`. Verify TTL on signed URLs.
- [ ] **Moderation:** Verify `return_exceptions=True` on the parallel gather. Verify `wait_for` timeout. Verify fail-open-vs-fail-closed policy is documented and locked. Verify category-level thresholds calibrated against v1.0 staged dataset.
- [ ] **Reactive report:** Verify reports schema does NOT contain session_uuid. Verify dedup at write time (UNIQUE constraint). Verify edge rate limit. Verify admin queue groups by clip_id. Verify admin actions are audit-logged.
- [ ] **Observability — logs:** Verify IP stripping middleware. Verify session_uuid / gps not in any structured log field. Verify GC on log retention.
- [ ] **Observability — Sentry:** Verify `max_request_body_size="never"`. Verify `send_default_pii=False`. Verify `before_send` scrubber. Verify Sentry disabled in OFFLINE_DEMO.
- [ ] **Observability — OTel:** Verify span context propagated across `asyncio.create_task` (test: pipeline trace shows nested spans). Verify `BatchSpanProcessor` in use. Verify p99 latency regression < 10%. Verify span attributes don't carry PII.
- [ ] **Observability — metrics:** Verify allowed-label list is documented. Verify cardinality budget alert. Verify no per-id labels.
- [ ] **OFFLINE_DEMO:** Verify startup completes with network firewalled. Verify Postgres → SQLite/in-memory fallback. Verify Blob → local FS fallback. Verify Sentry/OTel disabled. Verify moderation passthrough.
- [ ] **Cross-service deploy:** Verify feature flags (`STORAGE_BACKEND`, `METADATA_BACKEND`). Verify rollback runbook documented. Verify health check exercises both Postgres and Blob.
- [ ] **Schema migrations during deploy:** Verify expand-contract pattern documented. Verify migrations run as separate Railway job, not from app startup.
- [ ] **Blob cleanup:** Verify GC job exists (even in dry-run mode). Verify `POST /admin/reset` wipes Blob. Verify hard-delete on moderation block.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Sync driver shipped to prod | MEDIUM | Hotfix to async driver; redeploy; verify p99 improvement. v1.0 had this discipline; revert is straightforward. |
| Pool exhausted at peak | LOW | Increase `pool_size` + `max_overflow` if Postgres ceiling has room; otherwise reduce `--workers` to 1; flip to PgBouncer. |
| Cutover dropped rows | HIGH | If detected within 24h: re-run `seed_demo.py` to rebuild from source clips. If detected later: data is gone; document as v1.1 incident. |
| Alembic migration corrupted prod schema | HIGH | Restore from Neon point-in-time recovery (Neon supports PITR). Re-run hand-corrected migration. |
| ffmpeg ENOSPC during compile | LOW | Restart Railway instance (clears /tmp). Lower concurrent-compile semaphore. Investigate scratch-dir cleanup leaks. |
| Moderation provider outage | LOW | Circuit breaker auto-flips to fail-open. Quarantined clips visible in admin queue for catch-up. |
| Brigading attack | MEDIUM | Increase edge rate limit; manually purge queue rows for the attacked `clip_id`s; add the attack pattern to dedup heuristic. |
| Sentry leaked PII in events | HIGH | Use Sentry's data scrubbing project setting to retroactively drop matching events. Audit retention. Report to user community if anonymity guarantee was breached. |
| OTel cardinality blew metrics bill | MEDIUM | Add metric relabeling rules to drop offending labels; rotate metrics retention to expire bad series. |
| Blob storage full | LOW | Run GC job (`--no-dry-run`); confirm size drop; verify clips table integrity. |
| OFFLINE_DEMO broke at hackathon-style live demo | HIGH (reputation) | Local fallback: switch to staged dataset + `POST /admin/reset`. Pre-flight check: test OFFLINE_DEMO before every demo. |

---

## Pitfall-to-Phase Mapping

Suggested phase ordering (informs ROADMAP). Each pitfall flagged with which phase should prevent it; "verification" describes the gate.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Sync driver in async path | Postgres-migration | CI assert: `inspect(engine).driver == "asyncpg"`; lint ban on `psycopg2` import |
| Connection pool sizing | Postgres-migration | Load test + Neon connection-count graph |
| WAL → Postgres visibility | Postgres-migration | Plan-check: session-lifetime-per-pipeline-stage diagram |
| Alembic autogenerate misses | Postgres-migration | Hand-review every migration; `compare_type=True` set |
| Cutover drops rows | Postgres-migration | Recommendation: skip dual-write; hard cutover via `seed_demo.py` re-seed |
| ffmpeg HTTPS streaming | Vercel-Blob-migration | Plan-check: scratch-dir lifecycle + concurrent-compile semaphore |
| Browser → Blob skips validation | Vercel-Blob-migration | Plan-check: server-upload only for v1.1 |
| Moderation outage blocks pipeline | Moderation | Code review: `wait_for` + `return_exceptions=True`; fail-open policy locked in requirements |
| Moderation false positives on news | Moderation | Calibration set against v1.0 staged dataset; per-category thresholds |
| Reporter session_uuid linkable | Reactive-report | Schema review: reports table has no session_uuid; privacy invariant in PROJECT.md |
| Brigading / mass-report | Reactive-report | Dedup at write time; admin UI groups by clip_id; edge rate limit |
| Sentry captures bodies | Observability | Sentry config review: `max_request_body_size="never"` + `before_send` scrubber |
| OTel context lost across `create_task` | Observability | Trace test: pipeline trace shows nested spans; CI assertion |
| Metrics cardinality blowup | Observability | Allowed-label list documented; cardinality budget alert |
| OFFLINE_DEMO broken | Every phase that adds external dep | CI: startup with network firewalled |
| Cross-service deploy rollback | Postgres-migration AND Vercel-Blob-migration | Feature flag in code; rollback runbook documented |
| Schema migration during deploy | Postgres-migration | Expand-contract rule documented; migrations as separate job |
| Blob cleanup orphans | Vercel-Blob-migration | GC job exists (dry-run mode acceptable for v1.1) |
| OTel overhead | Observability | Benchmark gate: p99 within 10% of pre-instrumentation |
| Admin queue without preview | Reactive-report | UI review: inline playback present |
| Adversarial probing of classifier | Deferred to v1.2 | Document as known limitation in PROJECT.md |
| Provider data retention violates anonymity | Moderation | TOS review in provider-selection plan-check |

**Recommended phase ordering** (based on pitfall dependencies, demoable-at-every-phase principle):

1. **Postgres migration first** — riskiest data-layer change; must complete before observability can produce useful traces of the new path. Hard cutover via re-seed avoids dual-write pitfalls (#5).
2. **Vercel Blob second** — depends on Postgres for the `blob_url` column. Feature flag (`STORAGE_BACKEND=local|blob`) keeps v1.0 path available for rollback (#17).
3. **Observability third (early)** — install before moderation + reports so the new features come up *with* tracing/metrics, not retrofitted. PII scrubbing must be live before any new user-facing endpoint (#10, #12, #14).
4. **Moderation fourth** — depends on observability (need to see classifier latency, false-positive rate). Calibration against v1.0 staged dataset (#9).
5. **Reactive report fifth** — last because schema design depends on whether moderation already covers most cases. Brigading defense + privacy invariant (#10, #11).

This ordering carries forward v1.0's "demoable-at-every-phase" lesson: after each phase, the system is more production-ready *and* still demoable.

---

## Sources

- [SQLAlchemy 2.0 Connection Pooling docs](https://docs.sqlalchemy.org/en/20/core/pooling.html) — pool sizing, AsyncAdaptedQueuePool
- [SQLAlchemy Pooling for Serverless FastAPI: QueuePool vs. NullPool](https://davidmuraya.com/blog/sqlalchemy-connection-pooling-for-serverless-fastapi/) — PgBouncer + NullPool pattern
- [How to Use Async Database Connections in FastAPI (OneUptime, 2026-02-02)](https://oneuptime.com/blog/post/2026-02-02-fastapi-async-database/view) — async-driver pitfalls
- [Handling PostgreSQL Connection Limits in FastAPI Efficiently](https://medium.com/@rameshkannanyt0078/handling-postgresql-connection-limits-in-fastapi-efficiently-379ff44bdac5) — pool exhaustion patterns
- [Alembic Autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) — known limitations
- [Alembic Issue #157 — autogenerate detected removed index for constraints](https://github.com/sqlalchemy/alembic/issues/157) — index/constraint detection bug
- [Alembic Issue #468 — CREATE INDEX missing when table dropped](https://github.com/sqlalchemy/alembic/issues/468)
- [Alembic Discussion #1160 — drops and recreates index/FK every migration](https://github.com/sqlalchemy/alembic/discussions/1160)
- [Zero-Downtime Data Migration: Strategies to Beat the Race Condition (Medium)](https://medium.com/@chaitanya.vcs22/zero-downtime-data-migration-strategies-to-beat-the-race-condition-ec1312962aff) — dual-write conditional logic
- [Paxos Engineers 371ms Cutover for 21TB Postgres Ledger Migration](https://bitcoinethereumnews.com/tech/paxos-engineers-371ms-cutover-for-21tb-postgres-ledger-migration/) — partition-cutover pattern
- [FFmpeg Protocols Documentation](https://ffmpeg.org/ffmpeg-protocols.html) — concat protocol, whitelist requirements
- [Fix for FFmpeg "protocol not on whitelist" Error](https://blog.yo1.dog/fix-for-ffmpeg-protocol-not-on-whitelist-error-for-urls/) — `-protocol_whitelist` + `-safe 0`
- [CasparCG Issue #1548 — HLS stream URLs truncated in ffmpeg](https://github.com/CasparCG/server/issues/1548) — URL truncation with auth params
- [Vercel Blob documentation](https://vercel.com/docs/vercel-blob)
- [Vercel Blob Server Upload guide](https://vercel.com/docs/vercel-blob/server-upload)
- [Vercel Blob Client Upload guide](https://vercel.com/docs/vercel-blob/client-upload)
- [Vercel Storage Issue #544 — signed URL support](https://github.com/vercel/storage/issues/544)
- [Sentry Python — Scrubbing Sensitive Data](https://docs.sentry.io/platforms/python/data-management/sensitive-data/)
- [Sentry FastAPI Configuration Options](https://docs.sentry.io/platforms/python/guides/fastapi/configuration/options) — `send_default_pii`, `max_request_body_size`
- [How to Fix Context Loss in Python Asyncio Tasks When OpenTelemetry Trace (OneUptime, 2026-02-06)](https://oneuptime.com/blog/post/2026-02-06-fix-python-asyncio-context-loss/view) — `create_task` context propagation
- [OpenTelemetry asyncio Instrumentation docs](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/asyncio/asyncio.html) — official auto-propagation
- [How to Manage High Cardinality Metrics in Prometheus (Last9)](https://last9.io/blog/how-to-manage-high-cardinality-metrics-in-prometheus/) — per-id label antipattern
- [The Prometheus Cardinality Bomb (OpenObserve)](https://openobserve.ai/blog/prometheus-data-cardinality/) — cardinality explosion patterns
- [Prometheus Metric and Label Naming](https://prometheus.io/docs/practices/naming/) — official guidance
- [Meta Outlines Evolving Efforts to Combat Mass Reporting and Brigading (Social Media Today)](https://www.socialmediatoday.com/news/meta-outlines-evolving-efforts-to-combat-mass-reporting-and-brigading-in/628958/)
- [Meta Adversarial Threat Report](https://about.fb.com/news/2021/12/metas-adversarial-threat-report/) — coordinated attack patterns
- [Reporting online abuse to platforms (Cover et al., 2026, SAGE Journals)](https://journals.sagepub.com/doi/10.1177/13548565251324508) — anonymous reporting research
- [Content Moderation Trends 2026 (GetStream)](https://getstream.io/blog/content-moderation-trends/)
- [Ethical Pitfalls in Automated Content Moderation with Amazon Rekognition (Next World, 2026-04)](https://www.nextworldpro.com/2026/04/the-cost-of-censorship-ethical-pitfalls.html) — context-blind classifiers
- [Meta content moderation shortcomings risk Bangladesh violence (Amnesty International, 2026-03)](https://www.amnesty.org/en/latest/news/2026/03/bangladesh-metas-content-moderation-delays-risk-fuelling-real-world-violence/)
- [FastAPI Lifespan Events documentation](https://fastapi.tiangolo.com/advanced/events/) — startup non-blocking pattern
- [Case Study: Fixing FastAPI Event Loop Blocking (techbuddies, 2026-01)](https://www.techbuddies.io/2026/01/10/case-study-fixing-fastapi-event-loop-blocking-in-a-high-traffic-api/)
- [.planning/RETROSPECTIVE.md (Newz v1.0)](../RETROSPECTIVE.md) — carry-forward lessons
- [.planning/PROJECT.md (Newz)](../PROJECT.md) — anonymity-by-default invariant, OFFLINE_DEMO contract

---
*Pitfalls research for: Newz v1.1 — Public-Launch-Ready Backbone*
*Researched: 2026-04-27*
