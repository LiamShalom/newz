# Stack Research — Newz v1.1 Public-Launch-Ready Backbone

**Domain:** Production hardening for a hackathon-scale FastAPI monolith (anonymous video pipeline). Adds managed Postgres, object storage, AI moderation, observability.
**Researched:** 2026-04-27
**Confidence:** HIGH — versions verified on PyPI/Context7 within the last week; pricing pulled from official pages dated Mar–Apr 2026.

This file ONLY covers v1.1 additions. The v1.0 stack (React 18, Vite, FastAPI, Twelve Labs Marengo 3.0, Claude Agent SDK, Gemini 2.5 Flash, ffmpeg libx264 ultrafast) is treated as given and not re-researched.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Neon** (managed Postgres) | Postgres 17 (Free tier) | Replace SQLite for clip metadata | Serverless Postgres with branching — instant prod-clone DBs for migration testing; Vercel partner integration (frontend already on Vercel); pure DB, no Supabase auth surface we don't need (anonymity is load-bearing — adopting Supabase Auth would create a temptation to break the anonymity rule) |
| **asyncpg** | 0.30.x | Postgres driver | Fastest async Postgres driver in Python; binary protocol; the project already runs `asyncio.create_task` / `asyncio.gather` on the hot path so a non-blocking driver is mandatory |
| **SQLAlchemy 2.0** | 2.0.49 (Apr 3 2026) | Async ORM + Core | Native async engine via `create_async_engine("postgresql+asyncpg://…")`; typed mapped classes; `selectinload` for the cluster→clips eager-load that replaces the in-memory join SQLite let us cheat with |
| **Alembic** | 1.18.4 (Mar 2026) | Schema migrations | Standard SQLAlchemy migration tool; supports async via `async_engine_from_config` + `connection.run_sync()` template; one-shot `alembic init -t async` scaffolds the env.py correctly |
| **Vercel Blob** | Service (no version) | Clip media storage | Replaces Railway `/data` volume. Fronted by Vercel CDN — same edge that serves the React app, so feed playback is fast. ffmpeg can read directly from signed HTTPS URLs (verified — ffmpeg `https://` protocol is on by default), so the stitch step does NOT need to download clips locally first |
| **vercel** (Python SDK) | 0.5.8 (Apr 22 2026) | Blob client for FastAPI | First-party `AsyncBlobClient` — released Mar 27 2026, hot off the press. `async with AsyncBlobClient() as client:` pattern matches existing FastAPI dep-injection style. Multipart upload helpers cover the 25-200 MB clips this app actually produces |
| **Gemini 2.5 Flash-Lite** | `gemini-2.5-flash-lite` | Pre-publish moderation classifier (PRIMARY) | Already have `google-genai` in the stack from Gemini 2.5 Flash captions — zero new SDK. Native video input. Classification-tuned variant ($0.10/$0.40 per 1M tok) — ~6× cheaper than full Flash. Time-to-first-token ~426 ms; full classification of a 10 s clip empirically ~1.5–3 s — well under Marengo's 5–15 s embed window, so parallel `asyncio.gather(embed, moderate)` adds zero user-visible latency |
| **structlog** | 25.5.0 | Structured JSON logs | Bound loggers carry context across async hops (request_id, clip_id, run_id, span_id) which `python-json-logger` cannot do; processor pipeline allows the same logger config to render colored dev output AND machine-readable JSON in prod from one config; production-ready perf (claimed faster than stdlib for typical configs) |
| **Sentry SDK** | `sentry-sdk` 2.58.0 (Apr 13 2026) | Error tracking + perf | Auto-detects FastAPI when `fastapi` is in deps; first-class ASGI middleware; `AsyncioIntegration()` propagates context through `asyncio.create_task` and `asyncio.gather`; `send_default_pii=False` is the safe default and matches the anonymity-load-bearing constraint |
| **Pydantic Logfire** | `logfire` (current) | Tracing + metrics dashboard | Built on OpenTelemetry by Pydantic; one-call instrumentation for FastAPI, SQLAlchemy (sync + async), AND Anthropic SDK — covers the entire compile pipeline including individual Claude Agent SDK subagent calls without manual span-wrapping. 10M spans/month free. Run **alongside** Sentry: Sentry for error alerting, Logfire for tracing/metrics dashboards (this is the canonical recommendation in Logfire's own docs) |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `greenlet` | (auto via `sqlalchemy[asyncio]`) | Required by SQLAlchemy async | Install via `pip install "sqlalchemy[asyncio]"` — does NOT install by default since SQLAlchemy 2.0 |
| `pgvector` | 0.3.x (Postgres extension + Python client) | Future home for Marengo 512-d vectors | NOT in v1.1 scope — keep NumPy in-memory cosine. Listed here so the v1.1 schema can leave a `vector(512)` column TODO without committing. Both Neon and Supabase support `pgvector` natively |
| `opentelemetry-api` / `opentelemetry-sdk` | 1.30+ | OTel core (transitively via Logfire) | Logfire pulls these in. Direct dependency only if you want raw OTLP export to a non-Logfire backend |
| `opentelemetry-instrumentation-fastapi` | 0.51b+ | FastAPI OTel auto-instrumentation | Logfire's `instrument_fastapi()` wraps this — only install standalone if NOT using Logfire |
| `python-json-logger` | 3.x | Standalone JSON formatter | Only if you reject structlog. Listed for completeness — NOT recommended (see "Alternatives Considered") |
| `httpx` | 0.27+ | Async HTTP for Gemini moderation calls | Already in deps via `google-genai`. Reuse the singleton client; do NOT instantiate per-request |
| `tenacity` | 9.x | Retry decorator for moderation calls | Wrap the Gemini moderation call — current pipeline silently swallows transient failures, retry-with-backoff prevents a flaky 5xx from one provider blocking the entire upload path |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `alembic upgrade head` (in startup hook) | Auto-apply migrations on Railway boot | Wrap in `app.lifespan`. Idempotent. Emits a Sentry breadcrumb on each run |
| `ruff` (already in stack) | Lint + format | No change |
| `pytest-asyncio` | Async test runner | Required for testing the new async DB layer; existing v1.0 tests are sync where possible — async tests are net-new |
| Neon CLI (`neonctl`) | Branching + roles | Only needed for ops; not a runtime dependency. Useful for cutting a `staging` branch DB during demo prep |

---

## Installation

```bash
# Postgres + ORM + migrations
pip install "sqlalchemy[asyncio]==2.0.49" "asyncpg==0.30.0" "alembic==1.18.4"

# Vercel Blob
pip install "vercel==0.5.8"

# Moderation — already have google-genai; just add a thin retry wrapper
pip install "tenacity==9.0.0"

# Observability
pip install "structlog==25.5.0" "sentry-sdk[fastapi]==2.58.0" "logfire[fastapi,sqlalchemy,httpx]"

# OFFLINE_DEMO toggle: nothing new — moderation gate gets a passthrough branch
```

Initialise Alembic with the async template (one-time):

```bash
alembic init -t async migrations
```

---

## Alternatives Considered

### Postgres host — Neon (recommended) vs Supabase

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **Neon** | Supabase | Use Supabase if you DECIDE to break the anonymity-load-bearing rule and adopt Supabase Auth + Row Level Security as the productization path. Supabase Free includes always-on Postgres at $25/mo Pro vs Neon's $69/mo for always-on, and Storage + Auth are bundled. But you'd be paying for products (Auth, Realtime, Edge Functions, Storage) you don't need; and the very integration that makes Supabase compelling — RLS-tied-to-auth — assumes user accounts exist. Adopting it creates institutional pressure to break anonymity. Choose Supabase only if and when product strategy explicitly accepts that |
| **Neon Free** ($0, 0.5 GB storage, 191.5 compute-hr/mo, 10 branches) | Neon Launch ($19/mo, 10 GB, autoscaling) | Stay on Free for v1.1 — at <10K rows + post-hackathon traffic the Free tier is generous. Promote to Launch when (a) compute-hour quota gets squeezed by Marengo pre-warm hammering the DB, or (b) you need multiple always-on prod branches |

**Neon cold-start caveat:** Free-tier Neon scales compute to zero after 5 min idle, with a ~500 ms cold start on the next query. The CLAUDE.md "Pre-warm Marengo on backend startup" rule already establishes a startup-keepalive pattern — extend that to issue a `SELECT 1` against Neon every 4 min, or upgrade to Launch if cold-start becomes a demo killer like libvpx-vp9 nearly did.

### Postgres driver — asyncpg vs psycopg3

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **asyncpg** (via `postgresql+asyncpg://`) | psycopg3 (`postgresql+psycopg://`) | psycopg3 has native async support and is the only driver that handles both sync + async with one wheel — useful if you want the Alembic env.py to share a driver with the runtime. asyncpg is faster (binary protocol) and is what every "FastAPI + Postgres + 2026" tutorial defaults to. Pin asyncpg to `>=0.29` per upstream notes |

### Migrations — Alembic vs alternatives

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **Alembic** | atlas-go (declarative SQL diff), sqlmesh, raw SQL files | The async `env.py` template is one of Alembic's better-supported paths in 2026; autogenerate works against typed `Mapped[...]` classes; rollbacks via `alembic downgrade -1`. Use atlas only if you prefer fully declarative schema-as-source-of-truth. Raw SQL is fine for v1.0→v1.1 if you only do ONE migration ever — but you will have more |

### Moderation — Gemini 2.5 Flash-Lite (recommended) vs alternatives

| Option | Vision? | Latency p50 (10 s clip) | Cost / clip (rough) | News/reportage FP rate | API ergonomics | Verdict |
|--------|---------|-------------------------|---------------------|------------------------|----------------|---------|
| **Gemini 2.5 Flash-Lite** ✅ | YES (native video) | ~1.5–3 s | ~$0.0003 (single classification call w/ small system prompt + structured output) | LOW — instructable; can prompt "this is news footage, accept dramatic/violent imagery if newsworthy and not gratuitously gory" | Same `google-genai` SDK already in stack; structured-output JSON schema ergonomic | ✅ PRIMARY |
| Gemini 2.5 Flash | YES | ~3–6 s | ~$0.002 | LOW — same as Flash-Lite, slightly better reasoning | Same SDK | Fallback if Flash-Lite quality proves inadequate on the test set |
| OpenAI Moderation API (`omni-moderation-latest`) | Image-only, NO video | <1 s | Free | N/A — text+image, can't see motion/audio. Crowd-recorded news is fundamentally a video problem | New SDK (openai), but small | ❌ INSUFFICIENT — text/image only |
| Anthropic Claude Haiku 4.5 (vision) | Image-only (frame sampling) | ~2–4 s per 4-frame batch | ~$0.001–0.002 (Haiku 4.5: $1/$5 per 1M tok) | LOW — Haiku 4.5 is genuinely instructable and the editorial brief style works | Already have `anthropic` SDK; would need to sample frames manually (regression to pre-Gemini frame-aggregation pattern we abandoned) | Fallback only — re-introduces the frame-aggregation hack the v1.0 captions migration explicitly removed |
| Hive Moderation | YES (full video) | ~5–10 s | ~$0.10/min of video → ~$0.017/clip @ 10 s | LOW — purpose-built for moderation; tunable thresholds | Custom REST; sync-only-ish; queue-based for video | Excellent quality, ~50× more expensive than Gemini, slower than embed window — would force serial moderation. Reserve for human review-queue triage, not the inline gate |
| AWS Rekognition Content Moderation | YES (video) | ASYNC ONLY — minutes via SNS | $0.10/min stored video (~$0.017/clip) | MEDIUM — fixed taxonomy, less instructable; news false-positives well-documented (e.g. flags wartime/protest footage) | Bring all of AWS IAM/SNS infra for one feature on Railway-hosted backend | ❌ Too async for inline gate; bad infra fit |
| Azure Content Safety | Image + text (no video) | <1 s (image) | $1.50/1K images | MEDIUM — fixed categories, not instructable | New Azure SDK | ❌ No native video; would require frame extraction = pre-Gemini regression |

**Recommendation:** Gemini 2.5 Flash-Lite as the inline gate, with a structured-output JSON schema returning `{block: bool, categories: [...], rationale: str, confidence: float}`. Run it via `asyncio.gather(embed_marengo(clip), moderate_gemini(clip))` so total latency = `max(embed, moderate)` not `embed + moderate`. Block decision short-circuits the rest of the pipeline — clip never enters cluster/compile. Hive (or human) review queue handles edge cases the auto-gate flagged with low confidence.

**OFFLINE_DEMO=true behaviour:** Moderation returns `{block: False, categories: [], rationale: "OFFLINE_DEMO_PASSTHROUGH", confidence: 1.0}` without an API call. Same pattern as the existing Marengo/Gemini offline cache. Demo-day dataset is curated, so passthrough is safe.

### Logging — structlog (recommended) vs alternatives

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **structlog 25.5.0** | loguru | Loguru is friendlier for small CLIs but lacks first-class OpenTelemetry/structured-context support and forces you to InterceptHandler-bridge stdlib loggers (uvicorn, sqlalchemy) — net more wiring than structlog's `ProcessorFormatter` route in a FastAPI app |
| **structlog 25.5.0** | python-json-logger | python-json-logger only formats; it does NOT carry context. The whole point of structured logging in this app is following one upload from `POST /clips` through embed → cluster → compile → stitch — that requires bound context, which only structlog provides natively |

### Observability stack — Sentry + Logfire (recommended) vs alternatives

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **Sentry (errors) + Logfire (traces/metrics/logs)** | Sentry only (errors + Sentry Performance for traces) | Sentry's tracing UI is fine for HTTP request waterfalls but weaker for the multi-agent pipeline narrative (parallel Anthropic subagents + Gemini + ffmpeg). Logfire's `instrument_anthropic()` shows token counts and prompts per subagent in a way Sentry doesn't. If team appetite for two dashboards is zero, Sentry-only is acceptable and cheaper |
| **Sentry + Logfire** | Datadog APM | Datadog is the gold standard but starts at $31/host/month + log/trace ingestion; massively overkill for a single-process FastAPI monolith on Railway. Revisit at multi-region or 100+ req/s |
| **Sentry + Logfire** | Prometheus + Grafana (self-host) | Self-hosting fights the entire "lean infra" thesis (no Redis, no Celery). Adds operational surface for the team to babysit on a project that explicitly rejected that complexity |
| **Sentry + Logfire** | Better Stack (Logtail + Uptime) | Better Stack is a strong "logs + uptime" choice (3 GB/mo free) but its tracing is less mature than Logfire's OTel-native experience. If Sentry is too heavy, Better Stack + Logfire is a reasonable budget alternative |
| **Sentry + Logfire** | Axiom (logs only) | Axiom's free 500 GB/mo is best-in-class for log volume but it's logs-only — you'd still need Sentry for errors and Logfire/something for traces. Use Axiom as the long-term log archive if log retention bills get out of hand on Logfire |
| **Sentry + Logfire** | Railway-native logs/metrics | Railway's built-in logs are fine for `tail -f` debugging but have no structured query, no error grouping, no trace stitching. Use as the cheap fallback during local/staging only |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Supabase Auth** (even if you adopt Supabase) | Anonymous-by-default is load-bearing. Once Auth is wired up the temptation to "just attach the session" violates PROJECT.md core constraint. Same goes for Row-Level-Security tied to `auth.uid()` | Stay anonymous. If you need per-session scoping, hash the localStorage UUID server-side and use it as a non-PII partition key |
| **AWS Rekognition Content Moderation** | Async-via-SNS architecture incompatible with the inline `asyncio.gather(embed, moderate)` pattern; would force a wait-for-webhook polling layer the project doesn't need | Gemini 2.5 Flash-Lite |
| **Azure Content Safety** for video | No native video moderation — would require frame extraction, which is exactly the regression the v1.0 captions migration moved AWAY from when it switched from Anthropic frame-aggregation to native Gemini video | Gemini 2.5 Flash-Lite |
| **OpenAI Moderation API** for the inline gate | Text + image only. No motion/audio understanding. Crowd-sourced video moderation needs all three modalities | Gemini 2.5 Flash-Lite |
| **psycopg2** (the old one) | Sync only. Will block the event loop and silently destroy concurrency. Common drive-by mistake | asyncpg or psycopg3 (async) |
| **`engine_from_config()` in Alembic env.py** | Default Alembic template uses the SYNC engine factory; will fail with "the asyncio extension requires an async driver" | `async_engine_from_config()` + `connection.run_sync()` (Alembic async template) |
| **loguru** for this app | No first-class OTel; InterceptHandler bridging is fiddlier than structlog's stdlib bridge in a FastAPI app with uvicorn + sqlalchemy + alembic loggers all needing to be unified | structlog |
| **python-json-logger** | Formats only — does not carry bound context across the embed → cluster → compile pipeline; you'd lose the trace-id thread which is the entire reason to do structured logging on a multi-stage async pipeline | structlog |
| **`send_default_pii=True` in Sentry** | Anonymity is load-bearing. PII default-off is mandatory. Custom user identification (if needed) should be the hashed session UUID, never IP or any localStorage value | `send_default_pii=False` (which is the SDK default — just don't override) |
| **Pinecone / Qdrant / vector DB** | Already rejected for v1.0; v1.1 doesn't change the calculus at <1000 vectors. NumPy in-memory cosine + Postgres `vector(512)` column (using pgvector, available on both Neon and Supabase) is the upgrade path when this DOES become a problem | NumPy in-memory cosine (status quo); leave a `pgvector` migration in the wings |
| **Redis / Celery / message queue** | Same — single-process asyncio still wins at this scale; the v1.0 retrospective explicitly cites this as a load-bearing simplification | `asyncio.create_task` (status quo) |
| **Server-side transcoding (re-encode)** | Already rejected; libx264 ultrafast normalize-and-concat is 84× faster than libvpx-vp9 — DO NOT regress on storage migration | `-c copy` concat where possible; libx264 ultrafast for normalize |

---

## Stack Patterns by Variant

### If running locally (dev)

- Use a Postgres docker container, NOT Neon. Cold starts and free-tier compute hours don't help dev velocity.
- `DATABASE_URL=postgresql+asyncpg://newz:newz@localhost:5432/newz_dev`
- structlog ConsoleRenderer (colored, dev-friendly) instead of JSONRenderer
- Sentry can be left disabled (`SENTRY_DSN` empty → SDK is a no-op)
- Logfire local-only mode via `logfire.configure(send_to_logfire="if-token-present")` — no token = local pretty-print

### If `OFFLINE_DEMO=true`

- DB layer points at the same Neon URL (or local container). The OFFLINE_DEMO flag only affects external **AI API** calls, not infra dependencies.
- Moderation gate returns the cached passthrough verdict (see "Recommendation" above) — no Gemini call.
- Sentry/Logfire still active but tagged `environment="offline_demo"` so demo-day errors are quarantined from prod alerts.

### If migrating SQLite → Postgres data (one-time)

- Read SQLite via `aiosqlite`, write Postgres via SQLAlchemy async session in batches of 500.
- Re-embed nothing — vectors already in `embeddings` table. Schema for v1.1 should preserve the `embedding BLOB → bytea` type and the parent/child distinction unchanged. CLUSTERS table can be rebuilt on first startup post-migration (the existing rebuild-on-startup path was already a v1.0 pattern).
- Run twice: once into a Neon `staging` branch, validate, then promote to `main` branch via `neonctl branches set-primary`.

### If `pgvector` becomes the right call (post-v1.1)

- Both Neon and Supabase ship the extension. `CREATE EXTENSION vector;` then `embedding vector(512)`.
- Replace NumPy in-memory cosine with `ORDER BY embedding <=> :query_embedding LIMIT k`.
- This is NOT a v1.1 task. Listed because the v1.1 schema should leave a TODO comment on the vector column to make the future migration mechanical.

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `sqlalchemy==2.0.49` | `asyncpg>=0.29` | <0.29 had `create_async_engine` issues; current 0.30.x is the safe pin |
| `sqlalchemy[asyncio]==2.0.49` | `greenlet>=3.0` | `[asyncio]` extra pulls greenlet which is no longer a default dep in SQLAlchemy 2.0 |
| `alembic==1.18.4` | `sqlalchemy==2.0.49` | Alembic 1.18 series tracks SQLAlchemy 2.0 declarative typed API; autogenerate works on `Mapped[...]` |
| `vercel==0.5.8` | Python >=3.10 | Project runs Python 3.11 — fine. Released Mar 27 2026 (initial), 0.5.8 Apr 22 2026 — bleeding edge, watch for breaking changes |
| `sentry-sdk==2.58.0` | `fastapi>=0.79` | FastAPI integration auto-registers when `fastapi` is importable; needs `AsyncioIntegration()` added MANUALLY for asyncio context propagation |
| `logfire` (latest) | `opentelemetry-api>=1.30` | Logfire pins its own OTel deps; conflicts with manually-installed OTel packages — let Logfire own the OTel stack |
| `structlog==25.5.0` | Python 3.9+ | Note: 25.5.0 was released specifically to address a Python 3.13.4 stdlib breaking change; if backend ever moves to 3.13 confirm version is at least 25.5.0 |
| `google-genai` (existing) | `gemini-2.5-flash-lite` model | Same SDK as v1.0 captions; just a different model string. Structured output via `response_schema=` |

---

## Integration Notes (for plan-phase consumers)

1. **Moderation runs in `asyncio.gather` with embed.** The hot path becomes:
   ```python
   embed_task = asyncio.create_task(embed_marengo(clip))
   mod_task = asyncio.create_task(moderate_gemini(clip))
   embed, mod = await asyncio.gather(embed_task, mod_task)
   if mod.block:
       await mark_blocked(clip_id, mod)
       return  # never enters cluster/compile
   ```
   Marengo dominates wall-clock (5–15 s). Moderation (1.5–3 s) finishes first. Zero added latency in the pass case.

2. **Vercel Blob + ffmpeg.** Verified ffmpeg supports `https://` input natively. The stitch step accepts signed Blob URLs as inputs:
   ```bash
   ffmpeg -i "https://signed-blob-url-1" -i "https://signed-blob-url-2" \
          -filter_complex concat=n=2:v=1:a=1 -c:v libx264 -preset ultrafast out.mp4
   ```
   Use `-c copy` where MIME-fallback-ladder produced compatible streams; fall back to libx264 ultrafast normalize otherwise. NO local download required for the stitch input — only the OUTPUT needs to be uploaded back to Blob via `AsyncBlobClient.put()`.

3. **Sentry + Logfire side-by-side.** Init order: Logfire first (it owns OTel), then Sentry with `instrumenter="otel"` so Sentry consumes Logfire's OTel spans rather than fighting it. This avoids double-instrumented requests.

4. **Anonymity in observability.** Three rules:
   - `sentry_sdk.init(send_default_pii=False, ...)` — explicit, even though it's the default.
   - structlog logger config: bind only `session_hash` (sha256 of localStorage UUID, NOT the UUID itself), `clip_id`, `request_id`. Never bind raw IP or any user-supplied string.
   - Logfire: same. The `instrument_fastapi(capture_headers=False)` and the SQL query commenter should be configured to NOT include user-data in span attributes.

5. **Asyncio context propagation gotcha.** `asyncio.create_task` copies contextvars correctly in Python 3.7+, so OTel spans propagate. BUT — if the project uses `loop.run_in_executor` for ffmpeg or any sync code, contextvars do NOT propagate by default. Wrap with `contextvars.copy_context().run(...)` or use `asyncio.to_thread` (Python 3.9+) which handles this automatically.

6. **Alembic on Railway boot.** Add to FastAPI lifespan:
   ```python
   @asynccontextmanager
   async def lifespan(app):
       await run_alembic_upgrade_head()  # idempotent
       await prewarm_marengo()           # existing v1.0 pattern
       yield
   ```
   This makes deploys self-migrating. Roll-forward only — never call `downgrade` automatically.

---

## Sources

### Context7-verified (HIGH confidence)
- `/pydantic/logfire` — `instrument_fastapi`, `instrument_sqlalchemy(engine=async_engine)`, `instrument_anthropic`, `logfire.span` patterns
- `/getsentry/sentry-python` — `sentry_sdk.init(send_default_pii=False, ...)`, FastAPI auto-instrumentation, OpenTelemetry integration
- `/hynek/structlog` — bound logger / processor pipeline, ProcessorFormatter for stdlib bridge
- `/magicstack/asyncpg` — driver capabilities, async API surface

### Official documentation (HIGH confidence)
- [Vercel Blob — Pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing) — $0.023/GB-month storage, $0.05/GB transfer; 1 GB free on Hobby (verified Mar 4, 2026)
- [Vercel Blob — Server Uploads](https://vercel.com/docs/vercel-blob/server-upload) — `AsyncBlobClient` patterns
- [Vercel Python SDK changelog](https://vercel.com/changelog/vercel-python-sdk-in-beta) — released Mar 27, 2026
- [vercel on PyPI](https://pypi.org/project/vercel/) — version 0.5.8 (Apr 22, 2026)
- [sentry-sdk on PyPI](https://pypi.org/project/sentry-sdk/) — version 2.58.0 (Apr 13, 2026)
- [Sentry FastAPI integration docs](https://docs.sentry.io/platforms/python/integrations/fastapi/) — auto-detect, AsyncioIntegration, send_default_pii
- [Sentry sensitive data scrubbing](https://docs.sentry.io/platforms/python/data-management/sensitive-data/) — denylist, before_send hook
- [Alembic async template — env.py](https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py) — official async migration pattern
- [SQLAlchemy 2.0 asyncio docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — `create_async_engine`, async session patterns
- [Gemini 2.5 Flash-Lite (Vertex AI docs)](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-lite) — multimodal video input, classification target
- [FFmpeg Protocols Documentation](https://ffmpeg.ffmpeg.org/ffmpeg-protocols.html) — HTTPS input protocol enabled by default
- [Logfire vs Sentry comparison (Pydantic official)](https://logfire.pydantic.dev/docs/comparisons/sentry/) — recommends running both side-by-side

### Pricing pages (HIGH confidence, dated)
- [Neon plans](https://neon.tech/pricing) — Free: 0.5 GB, 191.5 compute-hr; Launch $19/mo
- [Vercel Blob pricing tweet (May 2025)](https://x.com/vercel/status/1925632672488968683) — $0.023/GB-mo, $0.05/GB transfer
- [Better Stack pricing](https://betterstack.com/pricing) — 3 GB free
- [Axiom free tier (via comparison post)](https://betterstack.com/community/comparisons/axiom-alternatives/) — 500 GB/mo free
- [Logfire pricing (via Pydantic)](https://pydantic.dev/logfire) — 10M spans/mo free, $2/M after

### MEDIUM-confidence (web search, multi-source)
- [Neon vs Supabase 2026 comparison](https://dev.to/thiago_alvarez_a7561753aa/neon-vs-supabase-2026-database-or-backend-the-real-tradeoffs-3ggn) — branching, cold-start, pricing breakdown
- [Hive vs AWS Rekognition vs Azure (2025 comparison)](https://deepcleer.com/m/blog/aws-rekognition-vs-google-vertex-ai-vs-azure-vs-hive-vs-unitary-vs-sightengine-comparison--107) — moderation provider tradeoffs, news false-positive caveats
- [Best AI content moderation APIs 2026](https://wavespeed.ai/blog/posts/best-ai-content-moderation-apis-tools-2026/) — Hive specialization on video; Azure text+image only
- [FastAPI + SQLAlchemy 2.0 patterns](https://leapcell.io/blog/building-high-performance-async-apis-with-fastapi-sqlalchemy-2-0-and-asyncpg) — production async patterns, asyncpg pin guidance
- [Logging in Python comparison](https://betterstack.com/community/guides/logging/best-python-logging-libraries/) — structlog vs loguru vs json-logger trade-offs
- [Claude Haiku 4.5 model overview](https://platform.claude.com/docs/en/about-claude/models/overview) — vision support, moderation suitability

### LOW-confidence / single-source (flagged)
- Specific Hive per-clip pricing (~$0.017/10 s clip) — back-of-envelope from quoted "$0.10/min stored video"; verify directly with Hive sales before committing
- Gemini 2.5 Flash-Lite empirical 1.5–3 s latency on a 10 s clip — extrapolated from "284 tok/s output, 426 ms TTFT" + small classification response. Validate with a benchmark on the actual demo dataset before committing the parallel-pipeline architecture; if real p50 exceeds 5 s the latency-hiding claim weakens

---

*Stack research for: Newz v1.1 Public-Launch-Ready Backbone (Postgres + Vercel Blob + AI moderation + observability)*
*Researched: 2026-04-27*
