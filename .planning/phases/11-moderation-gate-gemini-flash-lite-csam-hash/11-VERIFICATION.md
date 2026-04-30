---
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
verified: 2026-04-30T18:56:00Z
status: gaps_found
score: 22/23 must-haves verified (1 regression in cross-cutting test)
overrides_applied: 0
gaps:
  - truth: "OBS-04 cardinality drift defense (test_metrics_output_only_uses_allowed_stage_values) green"
    status: failed
    reason: "Phase 11 added stage='moderate' to STAGE_DURATION emits in run.py:89 and moderate.py:594, but the cross-cutting cardinality-drift defense test in test_observability_pipeline_metrics.py hard-codes ALLOWED_STAGES = {ingest, embed, cluster, compile, stitch} (D-17 enum). The 11-05 plan + summary updated metrics.py docstring/comment but did NOT update the test's ALLOWED_STAGES constant. Test passes in isolation (no moderation samples in registry) but fails in the full suite once any moderate-stage emit pollutes the global Prometheus registry. Verified locally: `pytest tests/pipeline/test_moderate.py tests/test_observability_pipeline_metrics.py::test_metrics_output_only_uses_allowed_stage_values` reproduces `AssertionError: unexpected stage values in /metrics: {'moderate'}`."
    artifacts:
      - path: "backend/tests/test_observability_pipeline_metrics.py"
        issue: "Line 22: ALLOWED_STAGES = {'ingest', 'embed', 'cluster', 'compile', 'stitch'} — missing 'moderate'. Test asserts /metrics output only contains stage values in this set; Phase 11's gate emits stage='moderate'."
    missing:
      - "Add 'moderate' to ALLOWED_STAGES set at backend/tests/test_observability_pipeline_metrics.py:22 — single-line change. Phase 8's D-17 enum is being amended by Phase 11; this is the canonical update site."
human_verification:
  - test: "Wave-0 smoke deploy on Railway preview"
    expected: "One real clip uploaded → exactly one moderation_decisions row (provider='gemini_flash_lite', decision='passed', prompt_version='1.0.0', latency_ms<20000) + one segments row with soft_flag=false; /feed JSON contains soft_flag:false; /metrics exposes STAGE_DURATION{stage='moderate'} histogram; Railway logs show one 'Phase 11 ships classifier-only CSAM detection' WARN at startup; no Sentry errors in deploy window."
    why_human: "Plan 11-07 Task 4 was explicitly deferred to HUMAN-UAT per orchestrator instruction. Cannot be automated from the planner side (requires Railway dashboard access, iOS PWA upload, Neon DB SELECTs, /metrics curl, Sentry dashboard scan). Use backend/seed/prewarm.mp4 (known-safe) — DO NOT use CSAM-shaped content for this smoke."
  - test: "Frontend tap-to-view interstitial on soft-flagged segments (MOD-08 UI side)"
    expected: "When a segment carries soft_flag=true, the feed renders a tap-to-reveal overlay over autoplay. User must tap to start playback."
    why_human: "Backend ships soft_flag boolean on /feed JSON (verified end-to-end via test_feed_includes_soft_flag); UI implementation lives in feature-track #6 owned by Roan and is not part of Phase 11 backend scope. Visual / interaction behavior cannot be verified programmatically."
  - test: "Common-case end-to-end upload-to-publish latency does not regress vs v1.0 baseline (MOD-03)"
    expected: "Median upload-to-publish wall-clock within 10% of v1.0 baseline; STAGE_DURATION{stage='moderate'} p50 ≤ STAGE_DURATION{stage='embed'} p50 in production (cancel-when-embed-finishes is the load-bearing latency primitive)."
    why_human: "Latency-no-regression is a steady-state production-traffic property. The cancel-when-embed-finishes mechanism is verified in unit tests (deterministic asyncio.Event), but the actual latency comparison requires a live deployment with representative clip-corpus traffic. Pending in STATE.md as Gemini Flash-Lite latency benchmark (D-29)."
---

# Phase 11: Moderation Gate Verification Report

**Phase Goal:** Every uploaded clip passes through a moderation gate before entering cluster/compile; gate runs parallel-with-Marengo so common-case latency does not regress; tiered failure policy (timeout fail-CLOSED, 5xx outage fail-OPEN to admin queue); CSAM detection via Gemini classifier `csam` category → hard-block + `reported_csam` preservation per § 2258A (1-year retention per 2024 REPORT Act); soft-flag for hate/violence regardless of corroboration count.

**Verified:** 2026-04-30T18:56:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### ROADMAP Success Criteria

ROADMAP.md L127 lists Phase 11 success criteria. Each verified:

| # | Criterion | Status | Evidence |
| - | --------- | ------ | -------- |
| SC-1 | Disallowed content never reaches public feed | VERIFIED | `_route_verdict` (moderate.py:370) routes any HARD_BLOCK_CATEGORIES verdict in {flag, block} to `decision='blocked'`; run.py:96-103 returns early on blocked, never calls cluster_worker. test_moderate_hard_block_csam asserts cleanup_blocked_clip is called. |
| SC-2 | Common-case latency within 10% of v1.0 baseline | NEEDS HUMAN | Cancel-when-embed-finishes verified deterministically in test_moderate_cancel_when_embed_finishes_first; production latency comparison requires live traffic (Pending Todo: Flash-Lite latency benchmark, D-29). |
| SC-3 | Fail-CLOSED on timeout | VERIFIED | _classify_exception maps asyncio.TimeoutError → ('blocked', 'classifier_timeout'); _moderate_real Branch A also sets reason='classifier_timeout' on cancel-when-embed-finishes; Branch C sets reason='max_budget_exceeded'. test_moderate_failure_tier_classification[timeout] asserts. |
| SC-4 | OFFLINE_DEMO produces 'passed' with no external call | VERIFIED | moderate.py:199-211 short-circuits before any Gemini SDK construction; test_moderate_offline_demo_passthrough asserts respx routes have call_count=0; test_offline_demo_no_moderation_calls asserts the same end-to-end. |
| SC-5 | Hate/violence soft-flag → tap-to-view | VERIFIED (backend) / NEEDS HUMAN (UI) | _route_verdict returns ('passed', f'soft_flag_{cat}', soft_flag_categories) for hate/violence; compile.py:617-650 reads moderation_decisions for cluster members and sets segments.soft_flag=true; /feed JSON includes soft_flag boolean (test_feed_includes_soft_flag asserts). UI overlay is feature-track #6 (Roan) — out of phase scope. |
| SC-6 | Outbound payload contains video bytes only | VERIFIED | _gemini_classify uses google.genai SDK's files.upload + system_instruction + USER_PROMPT — no metadata serialized. _strip_anonymity_metadata defense-in-depth. test_moderate_priv_03_outbound_payload_anonymized verifies _gemini_classify call signature carries no anonymity-keyed dict and _strip_anonymity_metadata strips forbidden keys. |
| SC-7 | Classifier-only CSAM detection w/ manual NCMEC reporting | VERIFIED | csam category in HARD_BLOCK_CATEGORIES routes to reason='gemini_csam_block' which writes reported_csam (SHA-256 + 1yr preserved_until) BEFORE cleanup_blocked_clip. ncmec_report_id BIGINT NULL column added in migration 0004 for manual receipt id. Lifespan WARN at app.py:131 surfaces "real hash vendor + NCMEC reporting deferred post-pilot". No Cloudflare/CSAM_PROVIDER symbols in codebase (verified by grep). |

**Score:** 5/7 fully VERIFIED, 2/7 NEEDS HUMAN (latency benchmark + UI overlay)

### Observable Truths (from PLAN frontmatters merged)

| #   | Truth   | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| T-01 | config.GEMINI_MODERATION_MODEL exists with default 'gemini-2.5-flash-lite' | VERIFIED | config.py:72 |
| T-02 | config.MODERATION_MAX_BUDGET_S exists with default 20.0 | VERIFIED | config.py:76 |
| T-03 | No CSAM_PROVIDER / CLOUDFLARE_CSAM_API_KEY / CSAM_STUB_ALLOW_PRODUCTION env vars | VERIFIED | grep returns 0 in config.py, app.py |
| T-04 | Migration 0004 descends from 0003_merge_comments_blob | VERIFIED | down_revision = "0003_merge_comments_blob" at line 22 |
| T-05 | Migration 0005 descends from 0004 | VERIFIED | down_revision = "0004_moderation_columns" at line 19 |
| T-06 | moderation_decisions has decision/reason/provider/raw_response/latency_ms/prompt_version | VERIFIED | Plan 03 SUMMARY confirms schema introspection on Postgres `newz` DB pass; migration 0004 lines 33-38 add columns |
| T-07 | UNIQUE INDEX(clip_id, provider) on moderation_decisions | VERIFIED | Migration 0004 line 41-44; ON CONFLICT DO UPDATE used in write_moderation_decision (both backends) |
| T-08 | reported_csam has nullable BIGINT ncmec_report_id | VERIFIED | Migration 0004 line 48 |
| T-09 | segments.soft_flag BOOLEAN NOT NULL DEFAULT FALSE | VERIFIED | Migration 0005 line 25-26 |
| T-10 | db.write_moderation_decision callable from both backends | VERIFIED | grep confirms `^async def write_moderation_decision` in db_postgres.py:922 + db_sqlite.py:980; __all__ exports |
| T-11 | db.write_reported_csam callable from both backends | VERIFIED | db_postgres.py:956 + db_sqlite.py:1020 |
| T-12 | db.set_clip_hidden flips clips.is_hidden in both backends | VERIFIED | db_postgres.py:979 + db_sqlite.py:1039 |
| T-13 | db.get_moderation_decisions returns rows ordered by created_at DESC | VERIFIED | db_postgres.py:985 + db_sqlite.py:1053 |
| T-14 | db.aggregate_verdict precedence (blocked > unknown > passed) | VERIFIED | db_postgres.py:1026 + db_sqlite.py:1111 |
| T-15 | moderate_clip returns ModerationResult with decision in {passed, blocked, unknown} | VERIFIED | dataclass at moderate.py:131-139; Literal['passed','blocked','unknown'] type annotation |
| T-16 | OFFLINE_DEMO=true short-circuits to passthrough w/ provider='stub'; no Gemini HTTP call | VERIFIED | moderate.py:199-211; test_moderate_offline_demo_passthrough + test_offline_demo_no_moderation_calls assert call_count=0 |
| T-17 | embed_task and gemini_task fire in parallel; cancel-when-embed-finishes triggers TimeoutError → blocked | VERIFIED | moderate.py:520-557; test_moderate_cancel_when_embed_finishes_first uses asyncio.Event for deterministic ordering |
| T-18 | Typed-exception ladder maps Timeout+4xx → blocked; 5xx+network → unknown | VERIFIED | _classify_exception at moderate.py:403-452; covers genai_errors.ClientError + ServerError (CR-03 fix) AND legacy httpx; test_moderate_failure_tier_classification[parametrized 4 cases] + test_moderate_genai_client_error_blocked + test_moderate_genai_server_error_unknown |
| T-19 | csam-category hit writes reported_csam (SHA-256 + 1yr) AND cleanup_blocked_clip; ordering enforced | VERIFIED | moderate.py:613-642; test_moderate_hard_block_csam asserts call order ["write_reported_csam", "cleanup_blocked_clip"]. test_moderate_csam_preservation_failure_skips_cleanup verifies CR-02 audit-trail integrity (cleanup skipped when preservation write fails). |
| T-20 | hate/violence flag/block writes decision='passed' reason='soft_flag_<cat>' | VERIFIED | _route_verdict moderate.py:386-400; test_moderate_soft_flag_violence + test_moderate_hard_block_preserves_soft_flag_categories (WR-06 regression) |
| T-21 | Outbound Gemini payload contains video bytes only — no GPS/session/timestamp | VERIFIED | _strip_anonymity_metadata at moderate.py:157-174; test_moderate_priv_03_outbound_payload_anonymized verifies (a) _gemini_classify call signature carries no anonymity-keyed kwargs and (b) _strip_anonymity_metadata strips forbidden keys |
| T-22 | raw_response + prompt_version in REDACT_KEYS (D-27) | VERIFIED | observability/anonymity.py:27-28; csam_hash deliberately absent (reconciliation); _scrub round-trip test passes |
| T-23 | run_pipeline calls moderate_clip BEFORE cluster_worker | VERIFIED | run.py:89-90 inside STAGE_DURATION.labels(stage="moderate") wrapper |
| T-24 | STAGE_DURATION wraps gate call with stage='moderate' | VERIFIED | run.py:89; moderate.py:594 also emits via .observe() |
| T-25 | decision='blocked' short-circuits run_pipeline (cluster + compile do not run) | VERIFIED | run.py:96-103; explicit early return; events.broadcast pipeline_blocked |
| T-26 | decision='unknown' short-circuits run_pipeline AND clip is hidden via set_clip_hidden | VERIFIED | run.py:108-114; moderate.py:644-649 calls db.set_clip_hidden(clip_id, hidden=True) |
| T-27 | _resume_pipeline(clip_id) is exposed as a public function | VERIFIED | run.py:160; pulls db.get_embedding, runs cluster_worker, fires _should_compile + compile_segment |
| T-28 | Lifespan WARN under (not OFFLINE_DEMO and SENTRY_ENVIRONMENT=='production') | VERIFIED | app.py:131-135 — non-blocking, message verbatim "Phase 11 ships classifier-only CSAM detection. Real hash vendor + NCMEC reporting deferred post-pilot." |
| T-29 | compile_segment reads moderation_decisions for every cluster member; soft_flag derivation | VERIFIED | compile.py:617-650; defensive try/except defaults to False on derivation failure; per WR-07 fix uses batched get_moderation_decisions_for_clips |
| T-30 | When no soft-flag-category signal, segments.soft_flag is False | VERIFIED | compile.py soft_flag = False default; ON CONFLICT(cluster_id) DO UPDATE SET soft_flag=EXCLUDED.soft_flag in db_postgres.insert_segment |
| T-31 | insert_segment accepts soft_flag: bool = False kwarg in both backends | VERIFIED | inspect.signature both backends; db_postgres.py:355 + db_sqlite.py:[soft_flag in signature]; test verified post-fix |
| T-32 | Frontend Segment interface gains soft_flag: boolean | VERIFIED | frontend/src/types.ts:90 |
| T-33 | gemini_moderation_mock fixture in conftest.py (no per-provider parametrize) | VERIFIED | conftest.py:117 def gemini_moderation_mock; grep MODERATION_PROVIDER returns 0 |
| T-34 | test_moderate.py 9 test functions, 12+ collected (passed) | VERIFIED | 16 tests pass post-REVIEW-FIX (12 baseline + 4 regression: csam_preservation_failure_skips_cleanup, hard_block_preserves_soft_flag_categories, genai_client_error_blocked, genai_server_error_unknown) |
| T-35 | OBS-04 cardinality drift defense remains green (D-17 enum invariant) | **FAILED** | test_observability_pipeline_metrics.py::test_metrics_output_only_uses_allowed_stage_values asserts /metrics stage values ⊆ {ingest, embed, cluster, compile, stitch}. Phase 11 emits stage='moderate' but did NOT update ALLOWED_STAGES. Reproducible: `pytest tests/pipeline/test_moderate.py tests/test_observability_pipeline_metrics.py::test_metrics_output_only_uses_allowed_stage_values` → AssertionError: unexpected stage values in /metrics: {'moderate'}. |

**Score:** 34/35 truths VERIFIED; 1 FAILED (T-35); SC-2 + SC-5 (UI) are HUMAN VERIFICATION items (not gaps).

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| backend/config.py | GEMINI_MODERATION_MODEL + MODERATION_MAX_BUDGET_S | VERIFIED | Lines 72, 76 |
| backend/.env.example | Phase 11 commented block | VERIFIED | (per Plan 01 SUMMARY; tool denied direct read) |
| backend/migrations/versions/20260430_0004_moderation_columns.py | ALTERs + UNIQUE INDEX + ncmec_report_id | VERIFIED | 54 lines, all 6 column ALTERs + DROP DEFAULTs + UNIQUE INDEX + BIGINT |
| backend/migrations/versions/20260430_0005_segments_soft_flag.py | ALTER segments ADD COLUMN soft_flag | VERIFIED | 33 lines |
| backend/db_postgres.py | 6 Phase 11 functions exported | VERIFIED | __all__ contains write_moderation_decision, write_reported_csam, set_clip_hidden, get_moderation_decisions, get_moderation_decisions_for_clips, aggregate_verdict |
| backend/db_sqlite.py | Same 6 functions parity + Phase 11 SCHEMA_SQL (CR-04 fix) | VERIFIED | Parity functions exist; CR-04 closeout added moderation_decisions + reported_csam tables + clips.is_hidden ALTER |
| backend/pipeline/moderate.py | moderate_clip + helpers + constants | VERIFIED | 697 lines (>>200 min); all expected exports importable |
| backend/observability/anonymity.py | REDACT_KEYS extension (raw_response + prompt_version) | VERIFIED | Lines 27-28 |
| backend/pipeline/run.py | Gate wireup + _resume_pipeline | VERIFIED | from .moderate import moderate_clip at L10; gate at L89; _resume_pipeline at L160 |
| backend/app.py | Lifespan WARN + GEMINI_API_KEY fail-loud (WR-05) | VERIFIED | L131 WARN; L139-151 fail-loud guard |
| backend/observability/metrics.py | STAGE_DURATION docstring lists 'moderate' | VERIFIED | Per Plan 05 SUMMARY |
| backend/pipeline/compile.py | soft_flag derivation block + insert kwarg | VERIFIED | L617-650 derivation; L672 soft_flag=soft_flag |
| frontend/src/types.ts | Segment.soft_flag boolean | VERIFIED | L90 |
| backend/tests/pipeline/__init__.py | Package marker | VERIFIED | Empty file |
| backend/tests/pipeline/test_moderate.py | 9+ test functions covering all paths | VERIFIED | 663 lines; 16 collected; 16 pass |
| backend/tests/conftest.py | gemini_moderation_mock fixture | VERIFIED | L117 |
| backend/tests/test_offline_demo_firewall.py | MOD-10 zero-egress test | VERIFIED | test_offline_demo_no_moderation_calls + test_offline_demo_writes_moderation_row_to_sqlite (CR-04 regression) |
| backend/tests/test_feed_segments.py | MOD-08 soft_flag in /feed | VERIFIED | test_feed_includes_soft_flag |

### Key Link Verification

| From | To  | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| run.py | moderate_clip | from .moderate import moderate_clip | WIRED | run.py:10 import; L90 await call |
| run.py | _resume_pipeline | exported in module | WIRED | run.py:160 async def, callable by Phase 12 admin endpoint |
| moderate.py | db.write_moderation_decision | db.write_moderation_decision call | WIRED | moderate.py:201 (OFFLINE_DEMO path) + L602 (real path) + L671 (defense-in-depth) |
| moderate.py | db.write_reported_csam | csam-hit ordering before cleanup | WIRED | moderate.py:625; gated on safe_to_cleanup flag (CR-02 fix) |
| moderate.py | storage.cleanup_blocked_clip | hard-block cleanup | WIRED | moderate.py:35 import, L640 call |
| moderate.py | db.set_clip_hidden | unknown path hides clip | WIRED | moderate.py:647 (live) + L680 (defense-in-depth) |
| moderate.py | config.GEMINI_MODERATION_MODEL | classifier model selection | WIRED | moderate.py:341 |
| moderate.py | config.MODERATION_MAX_BUDGET_S | wait_for + asyncio.wait timeout | WIRED | moderate.py:319, 351, 527 |
| compile.py | db.get_moderation_decisions[_for_clips] | soft_flag derivation | WIRED | compile.py:[derivation block] uses batched get_moderation_decisions_for_clips per WR-07 fix |
| compile.py | db.insert_segment(soft_flag=...) | soft_flag write-through | WIRED | compile.py:672 |
| 0004 → 0003 | down_revision | Alembic chain | WIRED | down_revision = "0003_merge_comments_blob" |
| 0005 → 0004 | down_revision | Alembic chain | WIRED | down_revision = "0004_moderation_columns" |
| frontend Segment.soft_flag | Roan UI feature-track #6 | type system | WIRED (backend) | Field declared; UI handoff explicit per D-15 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| moderate.py moderate_clip | parsed (Gemini classifier output) | _gemini_classify → genai.Client.models.generate_content | Yes (when GEMINI_API_KEY set; OFFLINE_DEMO returns synthetic passthrough) | FLOWING |
| moderate.py raw_response → DB | sanitized_raw | _strip_anonymity_metadata(parsed) | Yes (passes through to JSONB column) | FLOWING |
| compile.py soft_flag | soft_flag bool | iterate db.get_moderation_decisions_for_clips → walk raw_response[hate/violence].verdict | Yes (real DB read, real classifier output, real verdict) | FLOWING |
| /feed JSON segments[].soft_flag | bool | fetch_recent_segments SELECT s.soft_flag → output dict | Yes (real DB query, real column) | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 11 test suite passes (16 tests) | pytest backend/tests/pipeline/test_moderate.py -q | 16 passed in 1.02s | PASS |
| Cross-cutting MOD-08+MOD-10 tests pass | pytest backend/tests/test_offline_demo_firewall.py backend/tests/test_feed_segments.py -q | 6 passed in 0.36s | PASS |
| Module-level imports + invariants OK | python -c "from backend.pipeline.moderate import ...; assert PROMPT_VERSION=='1.0.0'..." | All imports + invariants OK | PASS |
| OBS-04 cardinality drift defense (full suite) | pytest backend/tests/pipeline/test_moderate.py backend/tests/test_observability_pipeline_metrics.py::test_metrics_output_only_uses_allowed_stage_values | AssertionError: unexpected stage values in /metrics: {'moderate'} | **FAIL** |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| MOD-01 | 04, 05, 07 | Every uploaded clip runs through gate before cluster/compile | SATISFIED | run.py:90 await moderate_clip(clip_id) BEFORE cluster_worker; early-return on blocked/unknown |
| MOD-02 | 04, 07 | Gemini classifier runs in parallel with Marengo via asyncio.gather/wait | SATISFIED | moderate.py:520-528 asyncio.create_task + asyncio.wait FIRST_COMPLETED |
| MOD-03 | 04, 07 | Common-case latency does not regress vs v1.0 baseline | NEEDS HUMAN | Cancel-when-embed-finishes verified deterministically (test_moderate_cancel_when_embed_finishes_first); production latency comparison needs live deploy + benchmark |
| MOD-04 | 04, 05, 07 | Classifier-only CSAM detection (Gemini csam category → hard-block + reported_csam) | SATISFIED | csam in HARD_BLOCK_CATEGORIES; reason='gemini_csam_block' triggers reported_csam write before cleanup; test_moderate_hard_block_csam + test_moderate_csam_preservation_failure_skips_cleanup verify ordering + audit integrity |
| MOD-05 | 04, 07 | Tiered failure policy: timeout → blocked; 5xx → unknown | SATISFIED | _classify_exception covers asyncio.TimeoutError, genai_errors.ClientError (4xx → blocked), ServerError (5xx → unknown), httpx.* fallbacks; parametrized failure-tier test |
| MOD-06 | 02, 03, 04, 07 | Every decision recorded in moderation_decisions audit table | SATISFIED | All branches in _moderate_real call db.write_moderation_decision; UNIQUE(clip_id, provider) idempotency via ON CONFLICT DO UPDATE |
| MOD-07 | 02, 04, 06 | Hate/violence soft-flag (broadened, no corroboration) | SATISFIED | SOFT_FLAG_CATEGORIES = (hate, violence); _route_verdict returns ('passed', f'soft_flag_{cat}'...); compile.py reads cluster members' decisions and sets soft_flag=true regardless of corroboration count |
| MOD-08 | 02, 06, 07 | Feed UI tap-to-view interstitial on sensitive segments | SATISFIED (backend) / NEEDS HUMAN (UI) | /feed JSON includes soft_flag bool (test_feed_includes_soft_flag); UI overlay is feature-track #6 (Roan) |
| MOD-09 | 02, 03, 04, 07 | reported_csam preserves SHA-256 + 1-year retention | SATISFIED | _content_hash + _one_year_from_now_unix in moderate.py; ncmec_report_id BIGINT NULL added in migration 0004 for manual receipt audit; test_moderate_hard_block_csam asserts preserved_until ≈ now + 365d |
| MOD-10 | 01, 04, 07 | OFFLINE_DEMO=true bypasses every external moderation API; passthrough | SATISFIED | moderate.py:199-211 short-circuit; test_moderate_offline_demo_passthrough + test_offline_demo_no_moderation_calls assert respx call_count=0 |
| PRIV-03 | 04, 07 | Strip GPS/session_uuid/timestamp from outbound classifier calls | SATISFIED | _strip_anonymity_metadata helper; google.genai SDK upload+system_instruction+USER_PROMPT only; test_moderate_priv_03_outbound_payload_anonymized verifies application boundary |

**All 11 requirements (MOD-01..08, MOD-10, PRIV-03) accounted for.** REQUIREMENTS.md L144-153 maps exactly these 11 IDs to Phase 11 — no orphans. Two requirements (MOD-03 latency, MOD-08 UI overlay) have human-verification components which are flagged in the human_verification section.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| backend/pipeline/moderate.py | 124 | ALL_CATEGORIES constant unused (IN-01) | Info | Dead code; 6 Info findings remain post-REVIEW-FIX per orchestrator note |
| backend/pipeline/moderate.py | 177-183 | _now_unix and _one_year_from_now_unix trivial wrappers (IN-02) | Info | Single-use helpers; testability vs inline tradeoff |
| backend/db_sqlite.py | (write_reported_csam) | Doesn't return existing id on conflict (IN-03) | Info | Documented contract divergence; no live caller depends on the id |
| backend/pipeline/moderate.py | 157-174 | _strip_anonymity_metadata recursion unguarded against cycles (IN-04) | Info | Defense-in-defense; JSON from Gemini can't be cyclic |
| backend/tests/pipeline/__init__.py | 1 | Empty file marker (IN-05) | Info | Harmless |
| backend/migrations/versions/20260430_0004_moderation_columns.py | 33-40 | DEFAULT-DROP DEFAULT idiom assumes empty Phase 9 table (IN-06) | Info | Production-deploy precondition; verify against deploy snapshot |
| backend/tests/test_observability_pipeline_metrics.py | 22 | ALLOWED_STAGES missing 'moderate' | **Blocker** | Phase 11 cardinality enum drift — see gaps section |

The 6 Info findings remain per orchestrator note (post-fix scope). The Blocker (test_metrics) is the **gap** flagged in this verification — a real Phase 11 regression in cross-cutting OBS-04 enforcement.

### Human Verification Required

See frontmatter `human_verification` section. Three items:

1. **Wave-0 smoke deploy on Railway preview** (deferred per orchestrator instruction; Plan 11-07 Task 4)
2. **Frontend tap-to-view interstitial UI** (feature-track #6 owned by Roan; out of phase scope but needed for full MOD-08 satisfaction)
3. **Latency-no-regression benchmark on demo dataset** (MOD-03; pending in STATE.md as D-29)

### Gaps Summary

**Single Blocker:** Phase 11 added `stage="moderate"` to STAGE_DURATION emits in run.py and moderate.py, which is the correct architectural move (moderate is a real pipeline stage, deserves its own histogram label). The 11-05 plan + summary updated metrics.py docstring/comment to list `moderate` in the stage enum, but did NOT update `backend/tests/test_observability_pipeline_metrics.py:22` `ALLOWED_STAGES` constant. This test enforces D-17 (cardinality drift defense for OBS-04) and asserts `/metrics` output stage values ⊆ {ingest, embed, cluster, compile, stitch}.

The test passes when run in isolation (Prometheus registry is empty for `moderate` samples), but fails in any test ordering where a moderation-stage emit fires before this test runs. Concretely:
```
pytest backend/tests/pipeline/test_moderate.py backend/tests/test_observability_pipeline_metrics.py::test_metrics_output_only_uses_allowed_stage_values
→ FAILED: AssertionError: unexpected stage values in /metrics: {'moderate'} (D-17 enum forbids these)
```

This is a 1-line fix: add `'moderate'` to the `ALLOWED_STAGES` set at line 22. Phase 11 is amending the D-17 enum by design (moderate is a new pipeline stage); the test's locked-set needs to follow.

The orchestrator's note ("Pre-existing 11 test failures in tests/test_db_clusters.py / tests/test_segments_db.py / tests/test_pipeline_integration.py are unrelated to Phase 11") missed this one — base commit 968de16 had a different mix of 11 failures (test_segments_db::test_insert_segment_round_trip was failing, NOT test_observability_pipeline_metrics). Phase 11 fixed one (Plan 07 SQLite ALTER closeout) and introduced one (this metrics test). The total count of 11 happens to match by coincidence.

---

_Verified: 2026-04-30T18:56:00Z_
_Verifier: Claude (gsd-verifier)_
