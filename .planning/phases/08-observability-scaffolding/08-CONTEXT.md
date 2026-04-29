# Phase 8: Observability Scaffolding - Context

**Gathered:** 2026-04-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the observability primitives once, up front, so every subsequent v1.1 migration phase (Postgres, Blob, Moderation, Reporting) is debuggable from day one — eliminate Railway log spelunking before it accumulates.

**In scope (from REQUIREMENTS.md):**
- structlog JSON log emission (OBS-01)
- Sentry error capture with PII scrubber (OBS-02, OBS-03)
- Prometheus `/metrics` endpoint with bounded labels only (OBS-04)
- `X-Forwarded-For` strip middleware (PRIV-01)
- structlog contextvars whitelist: `session_hash`, `clip_id`, `request_id` only (PRIV-02)

**Out of scope (deferred to Phase 13):**
- Logfire span tracing (OBS-05, OBS-06, OBS-07, OBS-09)
- Sentry `traces_sample_rate=0` enforcement test (OBS-08)
- OFFLINE_DEMO firewalled-startup CI smoke test (DEMO-02)
- Anonymity regression test for spans/labels (covered by Phase 13)

</domain>

<decisions>
## Implementation Decisions

### Logger Migration Strategy
- **D-01:** Bridge structlog to stdlib via `structlog.stdlib.ProcessorFormatter`. All 71 existing `log = logging.getLogger(__name__)` call sites emit JSON automatically through structlog's processor chain — zero call-site rewrites in this phase.
- **D-02:** The processor chain MUST include `structlog.contextvars.merge_contextvars` so that bridged stdlib calls pick up the per-request bound contextvars (`request_id`, `session_hash`, `clip_id`). Without this, PRIV-02 fails for legacy call sites.
- **D-03:** No native structlog kv-style call sites in this phase. Pipeline hot-path conversion (e.g., `log.info("embed_done", clip_id=cid, latency_ms=ms)`) is explicitly deferred — adopt opportunistically when those files are touched in Phases 9-13, do not bundle into Phase 8.

### Renderer Toggle
- **D-04:** `LOG_FORMAT` env var, values `json | console`, default `json`. Prod (Railway) leaves it unset → JSON. Local dev sets `LOG_FORMAT=console` in `backend/.env`.
- **D-05:** Read `LOG_FORMAT` once at logger configuration time (module import or lifespan startup). No runtime toggle.

### session_hash Strategy
- **D-06:** `session_hash = sha256(session_uuid).hexdigest()`. Constant across all time — same session UUID always produces the same hash. No HMAC, no key rotation.
- **D-07:** **Known divergence from Phase 12 (REPORT-03):** REPORT-03 uses daily-rotated HMAC for `reporter_ip_hash` because it lives in the long-lived `reports` DB table. `session_hash` lives only in append-only logs and is constant for cross-day debugging correlation. The Phase 12 planner MUST NOT re-litigate this — the two surfaces have different threat models and different anonymity windows.
- **D-08:** Implementation: a single helper, e.g. `def session_hash(uuid: str) -> str` in a new `backend/observability/anonymity.py` (or co-located with the contextvars binder). Pure function, no state.

### /metrics Endpoint Auth
- **D-09:** `GET /metrics` is `ADMIN_TOKEN`-guarded using the same auth pattern as `POST /admin/reset`. Empty `ADMIN_TOKEN` env var → endpoint returns 503 (consistent with existing admin-endpoint behavior).
- **D-10:** Authenticated callers receive standard Prometheus text format from `prometheus-client`. Bearer token in the `Authorization` header, or whatever scheme `/admin/reset` already uses — match it exactly.

### Claude's Discretion (locked-in defaults the planner can act on)
- **D-11:** `request_id` is generated server-side (UUID4) by middleware. Do NOT trust upstream `X-Request-ID` headers — consistent with the XFF-strip posture (anonymity-by-default doesn't trust client headers).
- **D-12:** Middleware execution order (outermost → innermost): `XFFStrip → RequestID + ContextvarsBind → CORSMiddleware → routes`. XFF strip must run before any code path that could log the inbound request.
- **D-13:** Sentry config: `sample_rate=1.0` (capture all errors at hackathon scale), `traces_sample_rate=0.0` (locked by REQ-OBS-08, enforced here so Phase 13 audit passes), `send_default_pii=False`, `max_request_body_size="never"`.
- **D-14:** Sentry `before_send` scrubber redacts at minimum: `session_uuid`, `gps_lat`, `gps_lng`, `blob_url`. Implement as a list-driven recursive walker so adding fields is one-liner-cheap (Phase 11/12 will add more).
- **D-15:** Library picks: `structlog` (latest stable), `sentry-sdk[fastapi]`, `prometheus-client`. Pin exact versions in `requirements.txt` matching v1.0's pin discipline. No `python-json-logger` (structlog's bridge handles JSON natively).
- **D-16:** OFFLINE_DEMO behavior: empty `SENTRY_DSN` → `sentry_sdk.init()` is skipped entirely (no DSN, no network). `/metrics` continues to work in-process (`prometheus-client` is purely in-process; no scraper dependency). structlog continues to emit normally. Result: `OFFLINE_DEMO=true` startup makes zero outbound network calls from observability layer.
- **D-17:** Prometheus label policy: only bounded labels — `route` (FastAPI route template, not raw path), `method`, `status_class` (2xx/3xx/4xx/5xx, not full code), `stage` (named pipeline stages: ingest/embed/cluster/compile/stitch). Explicitly forbidden: `clip_id`, `session_uuid`, `session_hash`, raw path with IDs, GPS-derived values.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and acceptance criteria
- `.planning/ROADMAP.md` §"Phase 8: Observability Scaffolding" — phase goal, depends-on (none), success criteria (5 items)
- `.planning/REQUIREMENTS.md` §"Observability" (OBS-01..04) — structured logs, Sentry config, Prometheus bounded labels
- `.planning/REQUIREMENTS.md` §"Anonymity Invariants" (PRIV-01, PRIV-02) — XFF strip + contextvars whitelist (cross-cutting; Phase 8 establishes the scaffolding the rest of v1.1 inherits)

### Project-level constraints (cross-phase)
- `.planning/PROJECT.md` §"Constraints" — anonymity is load-bearing, single Uvicorn worker, OFFLINE_DEMO must work
- `.planning/STATE.md` §"Locked Decisions" — Logfire owns spans (Phase 13), Sentry traces_sample_rate=0, --workers 1 locked, OFFLINE_DEMO end-to-end gate

### v1.0 architecture this phase wraps (read for integration points)
- `backend/app.py` — current `logging.basicConfig` setup at module top, `lifespan()` startup hook, single existing middleware (`CORSMiddleware`), `/admin/reset` token-guard pattern that `/metrics` will mirror
- `backend/config.py` — env-var loading pattern (uses `python-dotenv`); `ADMIN_TOKEN` already loaded here; `LOG_FORMAT` and `SENTRY_DSN` belong here
- `backend/pipeline/run.py`, `backend/pipeline/embed.py`, `backend/pipeline/cluster.py`, `backend/pipeline/caption_pipeline.py` — pipeline stages where contextvars binding (`clip_id`, `request_id`) needs to propagate across `asyncio.create_task` boundaries (Phase 13 deepens this with OTel context; Phase 8 only needs structlog contextvars to survive create_task, which structlog handles natively when bound on the parent task before spawning)

### Forward-looking (do NOT implement now, but plan for)
- Phase 13 (REQ-OBS-05..09, DEMO-01..02) will deepen this — Logfire spans, regression test for anonymity invariants, firewalled CI smoke test. Phase 8's scaffolding must not paint Phase 13 into a corner: keep observability config in one module so Logfire can be added alongside Sentry without restructuring.
- Phase 12 REQ-REPORT-03 reuses the `daily-rotated HMAC` pattern for IP hashes. Phase 8 deliberately does NOT use that pattern for `session_hash` (see D-07).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`/admin/reset` token-guard** (`backend/app.py:343-407`): Existing `ADMIN_TOKEN` auth pattern. `/metrics` endpoint reuses this verbatim — same env var, same 503-on-empty-token behavior, same header scheme.
- **`config.py` env-var loader** (`backend/config.py`): All env vars loaded once at module import via `python-dotenv`. New env vars (`LOG_FORMAT`, `SENTRY_DSN`, optional `SENTRY_ENVIRONMENT`) belong here, not scattered.
- **`lifespan()` startup hook** (`backend/app.py:58-69`): Where pre-warm tasks fire. Logger configuration must run **before** lifespan (at module import) so even DB init logs are JSON.
- **`asyncio.create_task` pattern** (`backend/app.py:67-68`, `backend/pipeline/run.py`): structlog contextvars bound on the parent task propagate to spawned coroutines automatically — no manual context-passing needed in Phase 8 (Phase 13 adds OTel context, which is a separate concern).

### Established Patterns
- **Single-worker asyncio** (`backend/Procfile`, `backend/railway.json`): `--workers 1` is locked. Means contextvars work without per-request isolation gymnastics. Logger config initialized once at module import; safe.
- **Stdlib `logging.getLogger(__name__)` everywhere** (71 sites across `app.py`, `db.py`, `events.py`, `pipeline/*`): Bridge approach (D-01) preserves all of these without modification.
- **Empty-token-disables-endpoint** (e.g., `/admin/reset` returns 503 when `ADMIN_TOKEN` is empty): `/metrics` follows this exact convention.
- **OFFLINE_DEMO graceful-degrade** (existing `_pre_warm_sdk` skips when `ANTHROPIC_API_KEY` unset, `app.py:43-48`): Sentry init follows the same pattern — empty `SENTRY_DSN` → skip init entirely with one INFO log line.

### Integration Points
- **Logger init site:** new module `backend/observability/__init__.py` (or `backend/observability/logging.py`). Imported at the top of `backend/app.py` *before* anything else — first import wins for stdlib `logging.basicConfig` replacement.
- **Sentry init site:** same `backend/observability/` module. Init function called at module import, gated on `SENTRY_DSN`.
- **Middleware registration:** `backend/app.py:74` (`app.add_middleware(CORSMiddleware, ...)`). New middleware (`XFFStrip`, `RequestIDAndContextvarsBind`) registered in order such that they wrap CORS — i.e., added *after* CORS in code (FastAPI applies middleware in reverse-add-order, so the last-added is outermost).
- **Metrics route registration:** `backend/app.py` after existing route registrations. Uses `prometheus_client.generate_latest()` + `CONTENT_TYPE_LATEST`. Token check inline (mirror `/admin/reset:343-407`).
- **Pipeline stage labels:** `pipeline/run.py` is the natural place to wrap stage timing in a `Histogram.time()` context manager, since it's already the orchestrator. Counters/histograms defined as module-level globals in `backend/observability/metrics.py` so they're not recreated per-request.

</code_context>

<specifics>
## Specific Ideas

- The bridge approach is the explicit recommendation: this phase's purpose is to *not break v1.0* while installing scaffolding. A 71-site refactor mixed with new infrastructure is exactly the failure mode this phase exists to prevent.
- `/metrics` reuses `ADMIN_TOKEN` rather than introducing `METRICS_TOKEN` — explicit choice to keep the env-var surface area small until horizontal scrape requirements emerge (which they won't at v1.1).
- `LOG_FORMAT` defaults to `json` (prod-safe default) — local dev opts in to console, not the other way around. If a developer forgets to set `LOG_FORMAT=console`, they get JSON output in their terminal — annoying but not unsafe. The reverse default would risk plain-text logs in prod.

</specifics>

<deferred>
## Deferred Ideas

- **Logfire span tracing** — Phase 13 (REQ-OBS-05, OBS-06, OBS-07, OBS-09). Phase 8 ships only the scaffolding Logfire will plug into.
- **`instrument_anthropic()` token tracing** — Phase 13 (REQ-OBS-06).
- **OTel context propagation across `asyncio.create_task`** — Phase 13 (REQ-OBS-07). Phase 8 relies on structlog's native contextvars propagation, which is sufficient for log correlation but not for cross-process span trees.
- **Anonymity regression test (asserts no log/span/metric label/admin payload contains raw session_uuid, exact GPS, or raw IP)** — Phase 13 (DEMO-02 + locked test in OBS-09).
- **OFFLINE_DEMO firewalled-startup CI smoke test** — Phase 13 (DEMO-02). Phase 8 ensures the observability layer is *capable* of working offline (D-16) but does not add the CI gate.
- **Native structlog kv-style call-site conversion in pipeline hot path** — Adopt opportunistically when those files are touched in Phases 9-13. Not a separate phase.
- **Per-admin login / per-admin audit trail** — Already deferred to v1.2 (REQUIREMENTS.md §Future). `/metrics` reusing `ADMIN_TOKEN` is consistent with this deferral.
- **Pipeline stage-level token-cost metrics** — Phase 13's `instrument_anthropic` produces these. Phase 8 ships only stage timing/count, not token cost.

</deferred>

---

*Phase: 08-observability-scaffolding*
*Context gathered: 2026-04-28*
