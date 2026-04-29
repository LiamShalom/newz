---
status: partial
phase: 08-observability-scaffolding
source: [08-VERIFICATION.md]
started: 2026-04-28T00:00:00Z
updated: 2026-04-28T19:15:00Z
---

## Current Test

[UAT-1 verified locally. UAT-2 awaiting post-merge Railway smoke with valid SENTRY_DSN.]

## Tests

### 1. Structured JSON in Railway production log stream
expected: Upload a clip against the live Railway deployment. Every log line is a single-line JSON object with at least `event`, `level`, `logger`, `timestamp`, `request_id`, and `clip_id` fields. No plain-text lines. Verifies SC-1 and OBS-01.
result: passed (verified locally with `LOG_FORMAT=json uvicorn` + `clip-1.mp4` ingest)
evidence:
  - request_id (`cfe65dc...`) propagated end-to-end through middleware → db → events → embed → cluster
  - clip_id (`c13ceb9b...`) bound to contextvars at run_pipeline entry, visible in pipeline.run / cluster / events lines
  - Third-party loggers bridged through dictConfig: httpx, python_multipart.multipart, claude_agent_sdk._internal, backend.db, backend.events
  - X-Forwarded-For `1.2.3.4` stripped before any log emit (no occurrence in any line)
note: uvicorn's own startup banner (`Started server process`, `Application startup complete`, `Uvicorn running on http://...`) is plain-text and emits before dictConfig binds — known/expected, framework boundary.

### 2. Sentry event received with PII scrubbed
expected: With a valid `SENTRY_DSN` set in Railway env, trigger a deliberate exception. Event appears in Sentry dashboard within 60s, payload contains none of: `session_uuid`, `gps_lat`, `gps_lng`, `blob_url`. Verifies SC-2 and PRIV-01.
result: pending
note: Deferred to post-merge Railway smoke. Already covered by integration test `test_observability_sentry.py::test_before_send_scrub_round_trip` (patches actual sentry-sdk and verifies scrubber redacts realistic event shapes including request.data, breadcrumbs, nested extra). Live-environment confirmation only validates Railway env wiring, not new behavior.

## Summary

total: 2
passed: 1
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps

### G-08-01: Raw GPS in `backend.db::insert_clip` log line — RESOLVED
discovered: 2026-04-28 during UAT-1 local run
status: resolved
fix_commit: 86f492f
detail: `insert_clip` was string-interpolating `lat=%.2f lng=%.2f` into its log event field. PRIV-02 contract forbids raw GPS in any log line. `backend/db.py` was outside Phase 8's source scope (only `observability/`, `app.py`, `pipeline/run.py` were modified) and the verifier missed this. One-line fix dropped lat/lng from the log message; values still persist to the clips table (needed for clustering).
