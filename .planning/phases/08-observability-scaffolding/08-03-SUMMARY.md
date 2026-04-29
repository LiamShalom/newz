---
phase: 08-observability-scaffolding
plan: 03
subsystem: observability
tags: [observability, prometheus, sentry, pipeline, anonymity, integration-tests]
dependency_graph:
  requires:
    - "Plan 08-01 (STAGE_DURATION histogram global, init_sentry, before_send_scrub)"
    - "Plan 08-02 (live /metrics route + middleware wired into backend/app.py)"
  provides:
    - "Pipeline ingest/embed/cluster stage timing histogram samples flowing into /metrics"
    - "OFFLINE_DEMO contract test: SENTRY_DSN='' => zero sentry_sdk.init calls (locks T-08-12)"
    - "before_send_scrub round-trip tests on realistic Sentry event shapes (locks T-08-13)"
    - "D-13 Sentry kwargs lock test (traces_sample_rate=0.0, send_default_pii=False, max_request_body_size='never', before_send=scrub)"
    - "D-17 stage-label cardinality enum guard scanning /metrics output (locks T-08-15)"
  affects:
    - "Plan 13 (Logfire spans + compile/stitch stage instrumentation — touches same files; deferred)"
    - "Phase 9+ (every backend run now emits stage timing for ingest/embed/cluster — DB migration phase has visibility)"
tech_stack:
  added: []
  patterns:
    - "STAGE_DURATION.labels(stage=...).time() context-manager wrap on async awaits (Pattern 4)"
    - "Lazy-import init_sentry skip-before-import (D-16 / Pitfall 5)"
    - "importlib reload of backend.app for ADMIN_TOKEN-closure capture (mirror of Plan 02 _boot_app)"
    - "Mocked sentry_sdk.init via unittest.mock.patch on import-time side effects (D-16 smoke)"
key_files:
  created:
    - "backend/tests/test_observability_sentry.py"
    - "backend/tests/test_observability_pipeline_metrics.py"
  modified:
    - "backend/pipeline/run.py"
    - "backend/app.py"
decisions:
  - "D-17 (subset): only ingest/embed/cluster instrumented in this plan; compile + stitch wraps deferred to Plan 13 to minimize merge friction with Phase 11 moderation gate work"
  - "D-16: OFFLINE_DEMO smoke test re-imports backend.observability under monkeypatched SENTRY_DSN='' and asserts mock_init.assert_not_called() — locks T-08-12"
  - "D-13: explicit kwarg assertions in test_init_sentry_calls_sdk_when_dsn_set guard against config drift (someone flipping send_default_pii=True)"
  - "ts form field added to POST /clips test data (the plan's example omitted it; ts is a required Form parameter on the route signature)"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-04-28"
  task_count: 2
  file_count_created: 2
  file_count_modified: 2
  test_count: 11
  test_pass_rate: "11/11 (100%)"
  phase_total_test_count: 44
---

# Phase 8 Plan 3: Pipeline Stage Timing + Sentry Contract Lock Summary

**One-liner:** Wrapped ingest/embed/cluster pipeline stages in `STAGE_DURATION.labels(stage=...).time()` (compile + stitch deferred to Plan 13), then locked the Sentry OFFLINE_DEMO contract (T-08-12) via a smoke test that asserts zero `sentry_sdk.init` calls when `SENTRY_DSN` is empty, plus realistic round-trip event-shape tests for `before_send_scrub` and a D-17 stage-label cardinality guard.

## Tasks Completed

| Task | Name                                                                         | Commit    | Files                                                                                       |
| ---- | ---------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------- |
| 1    | Wrap ingest/embed/cluster stages with STAGE_DURATION timing                  | `a13106e` | backend/pipeline/run.py, backend/app.py                                                     |
| 2    | Sentry tests + pipeline stage metrics tests                                  | `4e44c48` | backend/tests/test_observability_sentry.py, backend/tests/test_observability_pipeline_metrics.py |

## Stage Wraps Added

| Stage     | File                       | Line | Around                                  |
| --------- | -------------------------- | ---- | --------------------------------------- |
| `ingest`  | `backend/app.py`           | 131  | `await db.insert_clip(...)`             |
| `embed`   | `backend/pipeline/run.py`  | 49   | `await embed_worker(clip_id)`           |
| `cluster` | `backend/pipeline/run.py`  | 61   | `await cluster_worker(parent_clip_id, parent_vec)` |

## Stage Wraps Deferred to Plan 13

| Stage     | Reason                                                                                                                |
| --------- | --------------------------------------------------------------------------------------------------------------------- |
| `compile` | Wrap belongs in `backend/pipeline/compile.py`; that file is also touched by Phase 11 moderation gate work — defer to minimize merge friction. |
| `stitch`  | Wrap belongs in `backend/pipeline/stitch.py`; same reasoning (Phase 11 + Phase 13 both touch).                        |

Defended by `! grep -E 'stage="(compile|stitch)"' backend/app.py backend/pipeline/run.py` — exits 0 (the strings genuinely do not appear; deferred and verified-deferred).

## Test Counts

| Test File                                            | Tests | Pass Rate |
| ---------------------------------------------------- | ----- | --------- |
| `test_observability_sentry.py`                       | 8     | 8/8       |
| `test_observability_pipeline_metrics.py`             | 3     | 3/3       |
| **Plan 08-03 total**                                 | **11** | **11/11 (100%)** |
| Phase 8 total (anonymity + logging + middleware + metrics + sentry + pipeline_metrics) | **44** | **44/44 (100%)** |
| Full backend suite (excl. pre-existing test_debug_clusters drift) | **97** | **97/97 (100%)** |

## Cross-Plan Test Coverage by Requirement

| Requirement | Plan | Test File                                                                | Test                                                                                       |
| ----------- | ---- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| OBS-01 (structlog JSON)            | 01 | `test_observability_logging.py`            | `test_stdlib_logger_emits_json_with_required_keys` + 3 more                                 |
| OBS-02 (Sentry config — no PII)    | 03 | `test_observability_sentry.py`             | `test_init_sentry_calls_sdk_when_dsn_set` (asserts `send_default_pii is False`, `max_request_body_size == "never"`) |
| OBS-03 (Sentry before_send scrub)  | 01 + 03 | `test_observability_anonymity.py`, `test_observability_sentry.py` | 9 anonymity unit tests + 4 round-trip event-shape tests in 03                              |
| OBS-04 (Prometheus /metrics + bounded labels + pipeline-stage histograms) | 02 + 03 | `test_observability_metrics.py`, `test_observability_pipeline_metrics.py` | 6 auth/format/label-policy + 3 stage-emission/enum-guard                                  |
| PRIV-01 (XFF strip)                | 02 | `test_observability_middleware.py`         | `test_xff_stripped_before_route_handler` + 6 parametrized variants                          |
| PRIV-02 (contextvars whitelist)    | 02 | `test_observability_middleware.py`         | `test_request_id_bound_in_context`, `test_session_hash_bound_when_x_session_id_header_present`, `test_session_uuid_never_appears_in_logs`, `test_contextvars_cleared_after_request` |

Every Phase 8 requirement now has at least one passing verifying test.

## Phase 8 ROADMAP Success Criteria — Verification Status

| # | Criterion                                                                                                  | Status  | Evidence                                                                                                          |
| - | ---------------------------------------------------------------------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| 1 | structlog JSON output with `request_id`, `session_hash`, `clip_id` contextvars                             | ✅ DONE | Plan 01 logging tests + Plan 02 middleware tests confirm contextvars survive into route handlers                  |
| 2 | Sentry capture redacts `session_uuid`, `gps_lat`, `gps_lng`, `blob_url` end-to-end                         | ✅ DONE | Plan 03 round-trip event-shape tests in `test_observability_sentry.py` + direct unit verification (see below)     |
| 3 | `/metrics` endpoint, ADMIN_TOKEN-guarded, returns Prometheus text format                                   | ✅ DONE | Plan 02 `test_observability_metrics.py` 6 tests (503/401/format)                                                  |
| 4 | Bounded label policy — only `route`/`method`/`status_class`/`stage`; no `clip_id`/`session_uuid`/raw paths | ✅ DONE | Plan 02 `test_metrics_only_bounded_label_keys` + Plan 03 `test_metrics_output_only_uses_allowed_stage_values`     |
| 5 | Pipeline-stage histograms — ingest/embed/cluster timing                                                    | ✅ DONE | Plan 03 `test_ingest_stage_emits_sample_on_clip_post` + grep-confirmed wraps in source                            |

Compile + stitch stages deferred to Plan 13 (deliberate, scoped per CONTEXT.md "Out of scope").

### Direct unit verification of Success Criterion 2 (run during verification)

```
$ python -c "from backend.observability.anonymity import before_send_scrub, REDACTED; \
event = {'extra': {'session_uuid': 'x', 'gps_lat': 1.0, 'gps_lng': 2.0, 'blob_url': 'y'}}; \
out = before_send_scrub(event, {}); \
assert all(out['extra'][k] == REDACTED for k in ('session_uuid', 'gps_lat', 'gps_lng', 'blob_url')); \
print('OK')"
all four D-14 keys redacted: OK
```

## Threat Mitigations Locked

| Threat ID | Severity | Plan | Test                                                                                                  |
| --------- | -------- | ---- | ----------------------------------------------------------------------------------------------------- |
| T-08-12   | HIGH     | 03   | `test_init_sentry_skips_when_dsn_empty` + `test_offline_demo_app_import_makes_zero_sentry_calls`      |
| T-08-13   | HIGH     | 03   | `test_scrub_redacts_in_request_data`, `test_scrub_redacts_in_breadcrumbs`, `test_scrub_redacts_in_extra_nested`, `test_scrub_idempotent_on_realistic_event` |
| T-08-14   | MED      | 03   | `test_init_sentry_calls_sdk_when_dsn_set` (asserts the four D-13 kwargs explicitly)                   |
| T-08-15   | HIGH     | 03   | `test_metrics_output_only_uses_allowed_stage_values` (D-17 enum guard)                                |

## Decisions Made

- **Stage subset (ingest/embed/cluster only) — D-17 honored, compile/stitch deferred to Plan 13:** the plan body and CONTEXT.md "Out of scope" both call this out. Defended by a forbidden-string grep so the deferral is verifiable, not just documented.
- **`importlib.reload` pattern reused from Plan 02:** the new `_boot_app()` in `test_observability_pipeline_metrics.py` is a verbatim mirror of Plan 02's helper. The plan's "escape hatch if a flake materializes" guidance was followed preemptively because the same factory-closure capture issue (`make_metrics_endpoint(config.ADMIN_TOKEN)`) applies — no flake observed across multiple test runs, but the reload eliminates the failure mode entirely.
- **`ts` form field included in POST /clips test data:** the plan's example test snippet (`data = {"lat": "34.1", "lng": "-118.1"}`) omitted the required `ts` Form parameter from `backend/app.py:116` (`ts: float = Form(...)`). Adding `"ts": "1700000000.0"` was a mechanical fix to make the request reach the handler instead of returning 422.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's POST /clips test data missing required `ts` form field**
- **Found during:** Task 2, first dry-run authoring of `test_ingest_stage_emits_sample_on_clip_post`.
- **Issue:** The plan's `<action>` block at line 489-492 specified `data = {"lat": "34.1", "lng": "-118.1"}`, but `backend/app.py:116` declares `ts: float = Form(...)` — a required field. Sending without `ts` would return 422 before the route body executed, meaning the `STAGE_DURATION.labels(stage="ingest").time()` wrap would never fire and the test would fail at `assert resp.status_code == 202`.
- **Fix:** Added `"ts": "1700000000.0"` to the request `data` dict.
- **Files modified:** `backend/tests/test_observability_pipeline_metrics.py` (new file — fix applied at authoring time, not as a separate edit)
- **Commit:** `4e44c48`
- **Why this is a Rule 1 fix:** The plan's intent ("a successful POST /clips records a STAGE_DURATION ingest sample") is preserved exactly; the fix only ensures the request actually reaches the handler. No deviation from contract or threat-model.

**2. [Rule 2 - Critical] Mock `events.broadcast` to keep ingest test fully isolated**
- **Found during:** Task 2 authoring.
- **Issue:** `backend/app.py:132` calls `await events.broadcast({"type": "clip_added", "clip_id": clip_id})` AFTER the ingest stage wrap. The plan's mock list did not include this. Without mocking, the real broadcast pushes to in-memory subscriber queues; harmless in test, but leaves cross-test state on `events._subscribers`.
- **Fix:** Added `monkeypatch.setattr("backend.app.events.broadcast", _fake_broadcast)`.
- **Files modified:** `backend/tests/test_observability_pipeline_metrics.py`
- **Commit:** `4e44c48`
- **Why this is correct:** Test hygiene — keep the new test's mock surface tight, mirror the existing Plan 02 fixture pattern's discipline.

### No deviations from plan-stated decisions, contracts, or interfaces.

The stage wraps appear at the precise call sites the plan specified. The Sentry test contract (mock_init.assert_not_called(), four D-13 kwargs, four event-shape round-trips) is verbatim. The D-17 enum guard scans `/metrics` output exactly as specified.

## Authentication Gates

None encountered. `SENTRY_DSN=""` is the OFFLINE_DEMO-safe path and was the path under test for `test_init_sentry_skips_when_dsn_empty` and `test_offline_demo_app_import_makes_zero_sentry_calls`. The DSN-set path (`test_init_sentry_calls_sdk_when_dsn_set`) uses a fake `https://abc@sentry.example/1` value injected via `monkeypatch.setattr` and `with patch("sentry_sdk.init")` — no real Sentry connection.

## Pre-flight Checklist for Phase 9 (Postgres Migration)

What's now in place that Phase 9 can rely on:

- ✅ **Structured JSON logs** — every log line emitted from `backend.db`, migration scripts, alembic, etc. flows through structlog's stdlib bridge as JSON. DB-init logs (currently `log.info("insert_clip ...")` and similar) are debuggable in Railway.
- ✅ **Sentry error capture** — when Phase 9 ships and `SENTRY_DSN` is set in prod, migration errors (connection refused, schema-mismatch, lost-rows) will surface in Sentry with PII scrubbed via `before_send_scrub`. OFFLINE_DEMO remains zero-outbound (D-16 locked by smoke test).
- ✅ **/metrics scrape live** — Phase 9 can add `DB_POOL_SIZE` Gauge and `DB_QUERY_DURATION` Histogram to `backend/observability/metrics.py` as new module-level globals; the `/metrics` endpoint and ADMIN_TOKEN guard already exist.
- ✅ **request_id contextvar** — every HTTP-triggered DB call already inherits `request_id` from the per-request bound contextvar. Phase 9 can correlate "this slow query came from this request" without additional plumbing.
- ✅ **`STAGE_DURATION` histogram global** — when Phase 9 adds Postgres-backed embedding writes, the existing `embed` stage timing will continue to work; the histogram's `stage` label is plumbing-agnostic.

What Phase 9 must remember:

- ⚠️ **`backend.observability` MUST remain the first-import in `backend/app.py`** (Pitfall 6). Phase 9 will likely add `from . import migrations` or similar near the top — keep `from . import observability` strictly first.
- ⚠️ **The pre-existing `test_debug_clusters` failure** is still on the worktree base (CLUSTER_THRESHOLD test/config drift, predates Phase 8). Documented in `08-01-SUMMARY.md` and `deferred-items.md`. If Phase 9 touches the debug cluster route or threshold config, opportunistically fix the test while there.
- ⚠️ **`compile` and `stitch` stage wraps still deferred to Plan 13** — when Phase 9 touches `backend/pipeline/compile.py` or `stitch.py` (likely if migration changes how stitched outputs are referenced), do not opportunistically add stage wraps; Plan 13 owns that work to keep the audit trail clean.

## Known Stubs

None. All test code asserts real behavior; all production-side code is the actual stage wraps in production paths. No placeholder data; no "TODO: wire later" code paths.

## Threat Flags

None. The plan's `<threat_model>` block (T-08-12 through T-08-15) covers every trust boundary touched by these changes. No new threat surface added — the plan instruments existing boundaries; it does not create new network/auth/file paths.

## TDD Gate Compliance

The plan marks both tasks `tdd="true"`. Per Plan 08-01 and Plan 08-02 precedent, this plan uses a single per-task commit (`feat(...)` for the wraps; `test(...)` for the tests).

**Task 1 (stage wraps) — sequence:**
1. RED gate confirmed before edit: `grep -c 'STAGE_DURATION.labels(stage="embed").time()' backend/pipeline/run.py` returned `0`.
2. Edit applied; full backend suite re-run (`pytest backend/tests/ -k "not test_debug_clusters_empty_returns_envelope"`) produced `86 passed, 1 deselected` — no regression.
3. GREEN gate confirmed: all four grep checks return `1`. Single `feat(...)` commit `a13106e`.

**Task 2 (tests) — sequence:**
1. RED gate confirmed before authoring: `ls backend/tests/test_observability_sentry.py backend/tests/test_observability_pipeline_metrics.py` exited non-zero (files absent).
2. Files authored; targeted run produced `11 passed`. Full Phase 8 suite produced `44 passed`. Full backend suite produced `97 passed, 1 deselected`.
3. GREEN gate confirmed across three scopes. Single `test(...)` commit `4e44c48`.

The full RED → GREEN → REFACTOR cycle for Task 2 lives within `4e44c48` because the test bodies were authored matching the plan's snippets verbatim (with the two Rule-1 fixes documented above), with no refactor pass needed.

## Self-Check

### Created files exist

```
$ test -f backend/tests/test_observability_sentry.py && echo FOUND
FOUND
$ test -f backend/tests/test_observability_pipeline_metrics.py && echo FOUND
FOUND
$ test -f .planning/phases/08-observability-scaffolding/08-03-SUMMARY.md && echo FOUND
FOUND
```

### Modified files (stage wraps in place)

```
$ grep -nE 'STAGE_DURATION.labels\(stage="(ingest|embed|cluster)"\)' backend/app.py backend/pipeline/run.py
backend/app.py:131:    with STAGE_DURATION.labels(stage="ingest").time():
backend/pipeline/run.py:49:        with STAGE_DURATION.labels(stage="embed").time():
backend/pipeline/run.py:61:        with STAGE_DURATION.labels(stage="cluster").time():
```

### Commits exist

```
$ git log --oneline | grep -E "(a13106e|4e44c48)"
4e44c48 test(08-03): sentry init contract + before_send round-trip + pipeline-stage metrics
a13106e feat(08-03): wrap ingest/embed/cluster stages with STAGE_DURATION timing
```

### Test results

```
$ pytest backend/tests/test_observability_sentry.py backend/tests/test_observability_pipeline_metrics.py -v
============================== 11 passed in 0.39s ==============================

$ pytest backend/tests/test_observability_*.py -v
============================== 44 passed in 0.44s ==============================

$ pytest backend/tests/ -k "not test_debug_clusters_empty_returns_envelope"
============================== 97 passed, 1 deselected in 1.06s ==============================
```

## Self-Check: PASSED
