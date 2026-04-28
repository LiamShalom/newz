# Phase 8: Observability Scaffolding - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-28
**Phase:** 08-observability-scaffolding
**Areas discussed:** Logger migration approach, Renderer toggle, session_hash strength, /metrics endpoint exposure

---

## Logger Migration Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Bridge only | Install structlog as the stdlib logging handler with `merge_contextvars` in the chain. All 71 existing `log.info()` sites emit JSON with bound contextvars automatically — zero call-site changes. Smallest diff, lowest risk during a phase whose job is to NOT break v1.0. | ✓ |
| Hybrid | Bridge legacy sites + convert pipeline hot path (ingest, embed, cluster, compile, stitch) to native structlog API so those sites can emit kv pairs natively. ~15-20 sites converted. | |
| Big-bang | Rip out stdlib `logging.basicConfig`, convert all 71 sites to native structlog API in this phase. Cleanest end state, biggest diff, highest review cost. | |

**User's choice:** Bridge only
**Notes:** User initially asked "what are stdlib loggers?" — provided a plain-language explanation of stdlib `logging` vs structlog and how the bridge processor lets the 71 existing sites emit JSON without rewrites. After the explanation, user confirmed Bridge only. The hot-path conversion (Hybrid) is preserved as an opportunistic adoption pattern in CONTEXT.md D-03 — files touched in Phases 9-13 may convert their logger calls when convenient, but it's never bundled into Phase 8.

---

## Renderer Toggle (JSON vs Console)

| Option | Description | Selected |
|--------|-------------|----------|
| `LOG_FORMAT` env var | Explicit `LOG_FORMAT=json\|console`, default to `json`. Set `LOG_FORMAT=console` in `backend/.env` for local dev. Predictable, no surprise behavior. | ✓ |
| `stderr.isatty()` auto-detect | Pretty console when running in a TTY, JSON when piped. Zero config but confuses screen/tmux setups and tools that fake a TTY. | |
| `OFFLINE_DEMO=true` → console | Reuse the existing flag — couples log format to demo flag. | |
| `ENV=production` → JSON | Standard 12-factor convention. Requires introducing an `ENV` env var (currently absent). | |

**User's choice:** `LOG_FORMAT` env var
**Notes:** Default is `json` (prod-safe). Local dev opts in to console via `backend/.env`. Reasoning captured in CONTEXT.md D-04, D-05.

---

## session_hash Strength

| Option | Description | Selected |
|--------|-------------|----------|
| Daily-rotated HMAC | `HMAC-SHA256(daily_key, session_uuid)`, daily_key rotates at UTC midnight. Same pattern as REPORT-03 for IP hashes. Strongest anonymity; cross-day correlation breaks. | |
| Constant sha256 | Literal `sha256(session_uuid)`. Stable cross-day correlation; weakest anonymity if logs leak. PRIV-02 reads literally as this option. | ✓ |
| Constant HMAC with static secret | `HMAC-SHA256(static_secret, session_uuid)`. Stable correlation + secret prevents trivial reversal. Middle ground. | |

**User's choice:** Constant sha256
**Notes:** User asked for plain-language pros/cons before selecting (was unfamiliar with hashing/HMAC concepts). After receiving full pros/cons, user chose simplicity (constant sha256) over the daily-HMAC anonymity model recommended for cross-codebase consistency with Phase 12 REPORT-03. This creates an intentional divergence: `session_hash` (logs, append-only) is constant sha256; `reporter_ip_hash` (long-lived DB rows, Phase 12) is daily-rotated HMAC. CONTEXT.md D-06, D-07 explicitly note this divergence so the Phase 12 planner does not re-litigate.

---

## /metrics Endpoint Exposure

| Option | Description | Selected |
|--------|-------------|----------|
| `ADMIN_TOKEN`-guarded | Reuse existing `ADMIN_TOKEN` env var (same pattern as `/admin/reset`). One env var, one auth model. Empty token → 503. | ✓ |
| Public unauth | Standard Prometheus pattern. Bounded labels mean no PII leaks. Trade-off: traffic volume and error rates are public. | |
| Separate `METRICS_TOKEN` | New env var distinct from `ADMIN_TOKEN`. Lets a Prometheus scraper be granted scrape access without full admin power. One more secret to manage. | |

**User's choice:** `ADMIN_TOKEN`-guarded
**Notes:** Mirrors the existing `/admin/reset` token-guard pattern at `backend/app.py:343-407`. CONTEXT.md D-09, D-10 lock the auth scheme to match exactly.

---

## Claude's Discretion

The following sub-decisions were locked by Claude based on locked project constraints (PROJECT.md, REQUIREMENTS.md, STATE.md) — flagged in CONTEXT.md D-11..D-17 so the user can revisit if desired:

- `request_id` source: middleware-generated UUID4 (no upstream `X-Request-ID` trust) — consistent with XFF-strip's anonymity-by-default posture
- Middleware order: `XFFStrip → RequestID + ContextvarsBind → CORSMiddleware → routes`
- Sentry config: `sample_rate=1.0`, `traces_sample_rate=0.0`, `send_default_pii=False`, `max_request_body_size="never"`
- Sentry `before_send` redaction list (initial): `session_uuid`, `gps_lat`, `gps_lng`, `blob_url` — implement as list-driven walker for cheap extension in Phases 11/12
- Library picks: `structlog`, `sentry-sdk[fastapi]`, `prometheus-client` (latest stable, version-pinned to match v1.0 pin discipline)
- OFFLINE_DEMO: empty `SENTRY_DSN` skips `sentry_sdk.init()`; `/metrics` works in-process; structlog emits normally → zero outbound network calls from observability layer
- Prometheus label policy: bounded labels only (`route`, `method`, `status_class`, `stage`); explicitly forbidden — `clip_id`, `session_uuid`, `session_hash`, raw paths, GPS-derived values

## Deferred Ideas

- **Logfire span tracing** — Phase 13 (REQ-OBS-05, OBS-06, OBS-07, OBS-09)
- **`instrument_anthropic()` token tracing** — Phase 13 (REQ-OBS-06)
- **OTel context propagation across `asyncio.create_task`** — Phase 13 (REQ-OBS-07)
- **Anonymity regression test** (no log/span/metric label/admin payload contains raw `session_uuid`, exact GPS, or raw IP) — Phase 13 (DEMO-02 + OBS-09)
- **OFFLINE_DEMO firewalled-startup CI smoke test** — Phase 13 (DEMO-02)
- **Native structlog kv-style call-site conversion in pipeline hot path** — adopt opportunistically when those files are touched in Phases 9-13; not a separate phase
- **Per-admin login / per-admin audit trail** — already deferred to v1.2 (REQUIREMENTS.md §Future)
- **Pipeline stage-level token-cost metrics** — Phase 13's `instrument_anthropic` produces these; Phase 8 ships only stage timing/count
