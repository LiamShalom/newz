---
status: partial
phase: 08-observability-scaffolding
source: [08-VERIFICATION.md]
started: 2026-04-28T00:00:00Z
updated: 2026-04-28T00:00:00Z
---

## Current Test

[awaiting human testing on live Railway deployment with SENTRY_DSN configured]

## Tests

### 1. Structured JSON in Railway production log stream
expected: Upload a clip against the live Railway deployment. Every log line in `railway logs` is a single-line JSON object with at least `event`, `level`, `logger`, `timestamp`, `request_id`, and `clip_id` fields. No plain-text lines, no multi-line tracebacks. Verifies SC-1 and OBS-01 in production conditions.
result: [pending]

### 2. Sentry event received with PII scrubbed
expected: With a valid `SENTRY_DSN` set in Railway env, trigger a deliberate exception (e.g., POST malformed payload to `/clips`). Confirm an event appears in the Sentry dashboard within 60 seconds. Inspect the event payload — it must contain none of: `session_uuid`, `gps_lat`, `gps_lng`, `blob_url`. Stack trace and request metadata otherwise intact. Verifies SC-2 and PRIV-01.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
