---
status: partial
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
source: [11-VERIFICATION.md]
started: 2026-04-30T18:59:56Z
updated: 2026-04-30T18:59:56Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Wave-0 smoke deploy on Railway preview
expected: One real clip uploaded → exactly one moderation_decisions row (provider='gemini_flash_lite', decision='passed', prompt_version='1.0.0', latency_ms<20000) + one segments row with soft_flag=false; /feed JSON contains soft_flag:false; /metrics exposes STAGE_DURATION{stage='moderate'} histogram; Railway logs show one "Phase 11 ships classifier-only CSAM detection" WARN at startup; no Sentry errors in deploy window. Use backend/seed/prewarm.mp4 (known-safe) — DO NOT use CSAM-shaped content.
result: [pending]

### 2. Frontend tap-to-view interstitial on soft-flagged segments (MOD-08 UI side)
expected: When a segment carries soft_flag=true, the feed renders a tap-to-reveal overlay over autoplay. User must tap to start playback. Backend ships soft_flag boolean on /feed JSON (verified end-to-end via test_feed_includes_soft_flag); UI implementation lives in feature-track #6 owned by Roan.
result: [pending]

### 3. Common-case end-to-end upload-to-publish latency does not regress vs v1.0 baseline (MOD-03)
expected: Median upload-to-publish wall-clock within 10% of v1.0 baseline; STAGE_DURATION{stage='moderate'} p50 ≤ STAGE_DURATION{stage='embed'} p50 in production (cancel-when-embed-finishes is the load-bearing latency primitive). Pending in STATE.md as Gemini Flash-Lite latency benchmark (D-29).
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
