---
phase: 08-observability-scaffolding
plan: 01
subsystem: observability
tags: [observability, structlog, sentry, prometheus, anonymity, asgi-middleware]
dependency_graph:
  requires: []
  provides:
    - "configure_logging()/init_sentry() module-import side effects"
    - "session_hash() + before_send_scrub() pure helpers"
    - "XFFStrip + RequestIDAndContextvarsBind pure-ASGI classes"
    - "REQUEST_COUNT/REQUEST_DURATION/STAGE_DURATION metric globals"
    - "MetricsMiddleware + make_metrics_endpoint factory"
  affects:
    - "Plan 08-02 (wires observability into backend/app.py)"
    - "Plan 08-03 (pipeline stage timing — uses STAGE_DURATION)"
    - "Phases 9-13 (opportunistic native structlog kv-style adoption)"
tech_stack:
  added:
    - "structlog==25.5.0"
    - "sentry-sdk[fastapi]==2.53.0"
    - "prometheus-client==0.25.0"
  patterns:
    - "structlog.stdlib.ProcessorFormatter bridge (D-01 — zero call-site rewrites)"
    - "merge_contextvars in BOTH processors and foreign_pre_chain (D-02; Pitfall 2)"
    - "Pure ASGI middleware classes (Pitfall 1 — never BaseHTTPMiddleware)"
    - "Module-level Prometheus metric globals (Pitfall 3 — never per-request)"
    - "scope.get('route') templated route label (Pitfall 4 — never raw URL)"
    - "Empty-DSN early return BEFORE sentry_sdk import (Pitfall 5; D-16 OFFLINE_DEMO contract)"
    - "Recursive scrubber rebuilds dicts (Pitfall 8 — no mutation-during-iteration)"
    - "ExtraAdder() in foreign_pre_chain (Pitfall 7 — extra= kwargs flow through)"
key_files:
  created:
    - "backend/observability/__init__.py"
    - "backend/observability/anonymity.py"
    - "backend/observability/logging_config.py"
    - "backend/observability/sentry.py"
    - "backend/observability/middleware.py"
    - "backend/observability/metrics.py"
    - "backend/tests/test_observability_anonymity.py"
    - "backend/tests/test_observability_logging.py"
    - ".planning/phases/08-observability-scaffolding/deferred-items.md"
  modified:
    - "backend/config.py"
    - "backend/requirements.txt"
    - "backend/.env.example"
decisions:
  - "D-04: LOG_FORMAT defaults to 'json' (prod-safe); console opt-in for local dev via LOG_FORMAT=console"
  - "D-06: session_hash = sha256(uuid).hexdigest() — pure, constant, no key rotation"
  - "D-13: sentry_sdk.init locked kwargs — sample_rate=1.0, traces_sample_rate=0.0, send_default_pii=False, max_request_body_size='never'"
  - "D-16: empty SENTRY_DSN -> early return BEFORE any sentry_sdk import (zero outbound calls; OFFLINE_DEMO-safe)"
  - "Idempotency test re-binds buf after second configure_logging() call (handlers replaced on each invocation)"
metrics:
  duration: "~8.5 minutes"
  completed_date: "2026-04-28"
  task_count: 2
  file_count_created: 9
  file_count_modified: 3
  test_count: 15
  test_pass_rate: "15/15 (100%)"
---

# Phase 8 Plan 1: Observability Module Skeleton Summary

**One-liner:** Standalone observability primitives (structlog dictConfig bridging stdlib/structlog, gated Sentry init with PII scrubber, pure-ASGI middleware for XFF strip + request_id binding, module-level Prometheus globals) — six new files under `backend/observability/`, zero changes to `backend/app.py`.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Add config env vars + library pins + .env.example documentation | `2fa3529` | backend/config.py, backend/requirements.txt, backend/.env.example |
| 2 | Create observability module — anonymity helpers, logging config, Sentry init, middleware classes, metrics globals | `3fbb2e8` | backend/observability/{__init__,anonymity,logging_config,sentry,middleware,metrics}.py + 2 test files |

## Files Created (9)

**Module files (6):**
- `backend/observability/__init__.py` — module-import side effects (`configure_logging()` + `init_sentry()`)
- `backend/observability/anonymity.py` — `REDACT_KEYS` frozenset, `session_hash()`, `before_send_scrub()` (+`_scrub` recursive walker)
- `backend/observability/logging_config.py` — `configure_logging()` dictConfig keystone (idempotent; LOG_FORMAT-driven renderer toggle; merge_contextvars in both shared_processors and foreign_pre_chain; ExtraAdder for Pitfall 7)
- `backend/observability/sentry.py` — `init_sentry()` gated on `config.SENTRY_DSN` (early return BEFORE import; D-13 locked kwargs)
- `backend/observability/middleware.py` — `XFFStrip` (6 forbidden header bytes) and `RequestIDAndContextvarsBind` (server-side `uuid.uuid4().hex`; clear+bind+try/finally clear)
- `backend/observability/metrics.py` — module-level `REQUEST_COUNT`/`REQUEST_DURATION`/`STAGE_DURATION` + `MetricsMiddleware` (pure ASGI; templated route label via `scope.get("route")`) + `make_metrics_endpoint(admin_token)` factory (mirrors `/admin/reset` 503/401 auth verbatim)

**Test files (2):**
- `backend/tests/test_observability_anonymity.py` — 11 synchronous unit tests (sha256 hex shape, constancy, divergence, top-level/nested/list/breadcrumbs scrubbing, no-mutation-during-iteration regression, idempotence)
- `backend/tests/test_observability_logging.py` — 4 tests (stdlib JSON shape with required keys, contextvars in bridged log, native-structlog vs bridged-stdlib key-set parity, idempotent configure_logging)

**Auxiliary:**
- `.planning/phases/08-observability-scaffolding/deferred-items.md` — documents one pre-existing test failure (`test_debug_clusters` threshold drift) discovered during full-suite run, out of Phase 8 scope.

## Files Modified (3)

- `backend/config.py` — appended `LOG_FORMAT` (default "json"), `SENTRY_DSN` (default ""), `SENTRY_ENVIRONMENT` (default "production") below existing `ADMIN_TOKEN`. All `os.environ.get(...).strip()` per established convention.
- `backend/requirements.txt` — appended exact `==` pins: `structlog==25.5.0`, `sentry-sdk[fastapi]==2.53.0`, `prometheus-client==0.25.0`.
- `backend/.env.example` — appended `# Phase 8: Observability` block documenting the three new env vars (commented opt-in, matching existing Phase 3+ block convention).

## Library Versions Pinned

| Library | Version | Purpose |
|---------|---------|---------|
| `structlog` | 25.5.0 | dictConfig + ProcessorFormatter bridge |
| `sentry-sdk[fastapi]` | 2.53.0 | Error capture + before_send PII scrubber |
| `prometheus-client` | 0.25.0 | Counter/Histogram + /metrics text format |

## Test Counts

- `test_observability_anonymity.py`: **11 tests** — all passing
- `test_observability_logging.py`: **4 tests** — all passing
- **Total Phase 8 Plan 1 tests: 15/15 PASSING**
- Full backend suite outside Phase 8: **68/68 PASSING** (1 pre-existing failure deselected — see Deferred Issues)

## Verification Output

```
$ pytest backend/tests/test_observability_anonymity.py backend/tests/test_observability_logging.py -v
============================== 15 passed in 0.02s ==============================

$ python -c "import backend.observability"
{"event": "sentry skipped: SENTRY_DSN unset", ...}    # JSON output proves dictConfig active

$ ! grep -rq "BaseHTTPMiddleware" backend/observability/    # PURE-ASGI invariant holds
PURE-ASGI-OK

$ grep -c merge_contextvars backend/observability/logging_config.py    # D-02 holds
4    # >=2 required (BOTH chains)

$ pytest backend/tests/ -k "not test_debug_clusters_empty_returns_envelope"
68 passed, 1 deselected in 9.19s
```

## Confirmation: backend/app.py NOT modified

`git diff cd26e791..HEAD -- backend/app.py` produces empty output. Plan 08-02 owns the `app.py` wiring (`from . import observability` first import, middleware registration order, `/metrics` route registration). Phase 8 Plan 1 cleanly isolates the skeleton from the wiring — a regression in either layer is grep-able.

## Decisions Made

- **D-04 (LOG_FORMAT default = "json"):** read once at `configure_logging()` time; renderer toggles between `JSONRenderer()` and `ConsoleRenderer(colors=True)`. No runtime toggle (D-05).
- **D-06 (session_hash = sha256, no HMAC):** pure function in `anonymity.py`; constant across days (D-07 documented divergence from Phase 12 REPORT-03 in module docstring).
- **D-13 (Sentry locked kwargs):** all four kwargs (`sample_rate=1.0`, `traces_sample_rate=0.0`, `send_default_pii=False`, `max_request_body_size="never"`) literally appear in `sentry.py`.
- **D-14 (recursive PII scrubber):** `_scrub()` builds new dicts/lists rather than mutating in place — Pitfall 8 regression test asserts non-mutation.
- **D-16 (OFFLINE_DEMO-safe Sentry):** `if not config.SENTRY_DSN: return` runs BEFORE any `sentry_sdk` import. Confirmed at runtime: `import backend.observability` with empty DSN emits one INFO log line and makes zero outbound calls.
- **D-17 (bounded Prometheus labels):** only `route`, `method`, `status_class`, `stage`. `_status_class(code)` returns `f"{code // 100}xx"`. `route` reads `scope.get("route").path` (templated form, NOT raw URL — Pitfall 4).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Idempotency test handler-rebind**
- **Found during:** Task 2, post-implementation `pytest` run.
- **Issue:** `test_configure_logging_idempotent` failed because each `configure_logging()` call rebuilds the root logger handlers via `dictConfig`, replacing the handler whose `stream` the fixture had pointed at the captured buffer. The second `configure_logging()` therefore re-pointed output to stderr; the buffer received nothing.
- **Fix:** After the double `configure_logging()` calls, re-bind every root-logger handler's `.stream` to the captured buffer before logging the test's probe message. The `json_capture` fixture's identical re-bind logic now also runs inline within the idempotency test.
- **Files modified:** `backend/tests/test_observability_logging.py`
- **Commit:** `3fbb2e8`
- **Why this is a Rule 1 fix, not a deviation from intent:** The test's stated goal in the plan body (`test_configure_logging_idempotent`) is "Second call must not raise". The plan's test snippet did not account for handler-replacement semantics of `dictConfig`. The fix preserves the test's stated invariant (no raise) AND extends it to verify post-double-config emission still produces parseable JSON — a strictly stronger contract.

**2. [Rule 1 - Bug] Module docstrings tripping `! grep -q "BaseHTTPMiddleware"` acceptance check**
- **Found during:** Task 2, acceptance criteria grep run.
- **Issue:** I had documented Pitfall 1 in module docstrings using the literal string "NOT BaseHTTPMiddleware" / "BaseHTTPMiddleware silently breaks contextvars". The plan's acceptance criteria assert `! grep -q "BaseHTTPMiddleware" backend/observability/middleware.py` exits 0 — i.e. the literal string MUST NOT appear anywhere in the file (defense against accidentally subclassing it). My docstrings broke that invariant.
- **Fix:** Rephrased docstrings in `middleware.py` and `metrics.py` to avoid the literal token while preserving the safety message ("Pure ASGI only — see RESEARCH Pitfall 1"; "Starlette's stdlib base-middleware silently breaks contextvars").
- **Files modified:** `backend/observability/middleware.py`, `backend/observability/metrics.py`
- **Commit:** `3fbb2e8`

### No deviations from plan-stated decisions, contracts, or interfaces.

The skeleton matches the plan's `<interfaces>` block exactly. All 15 tests pass with the test bodies copied verbatim from the plan (with the one isolated handler-rebind fix above).

## Authentication Gates

None encountered. Empty `SENTRY_DSN` is the OFFLINE_DEMO-safe path and was honored throughout.

## Deferred Issues

**Pre-existing test failure outside Phase 8 scope:**
- `backend/tests/test_debug_clusters.py::test_debug_clusters_empty_returns_envelope` asserts `body["threshold"] == 0.55` but `backend/config.py:21` defaults `CLUSTER_THRESHOLD` to `0.70`. This drift exists on the worktree base commit and is unrelated to Phase 8. Documented in `.planning/phases/08-observability-scaffolding/deferred-items.md`. Likely related to the `recalibrate-post-parent-flip.md` deferred item from v1.0 close.

## Known Stubs

None. All created code is production-shaped — Plan 08-02 imports and wires it without modification.

## Threat Flags

None. The plan's `<threat_model>` block (T-08-01 through T-08-05) covers every trust boundary introduced by these files. No new threat surface added.

## TDD Gate Compliance

Per the plan, both tasks are marked `tdd="true"`.

**Task 1 (config additions):** No business logic — verified by acceptance grep checks (RED before edit confirmed `LOG_FORMAT` absent; GREEN after edit confirmed all defaults import correctly). Config-only changes typically don't warrant a separate `test(...)` commit; the verification commands serve as the test gate. Single `feat(...)` commit `2fa3529`.

**Task 2 (observability module):** Test files were authored before implementation files within the same task. RED was confirmed by an explicit `pytest` run that failed with `ModuleNotFoundError: No module named 'backend.observability.anonymity'`. Implementation files were then created; GREEN was confirmed (15/15 tests pass). Per the plan's atomic-task structure, both RED and GREEN are bundled into a single `feat(...)` commit `3fbb2e8` for Task 2. Future plans (Plan 08-02 wiring, Plan 08-03 pipeline timing) can opt for separate `test(...)` and `feat(...)` commits if a stricter TDD audit trail is desired.

## Self-Check

### Created files exist

```
$ test -f backend/observability/__init__.py && echo FOUND || echo MISSING
FOUND
$ test -f backend/observability/anonymity.py && echo FOUND
FOUND
$ test -f backend/observability/logging_config.py && echo FOUND
FOUND
$ test -f backend/observability/sentry.py && echo FOUND
FOUND
$ test -f backend/observability/middleware.py && echo FOUND
FOUND
$ test -f backend/observability/metrics.py && echo FOUND
FOUND
$ test -f backend/tests/test_observability_anonymity.py && echo FOUND
FOUND
$ test -f backend/tests/test_observability_logging.py && echo FOUND
FOUND
```

### Commits exist

```
$ git log --oneline | grep -E "(2fa3529|3fbb2e8)"
3fbb2e8 feat(08-01): create observability module skeleton (anonymity, logging, sentry, middleware, metrics)
2fa3529 feat(08-01): add observability config env vars and library pins
```

## Self-Check: PASSED
