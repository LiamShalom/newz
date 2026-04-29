---
phase: 08-observability-scaffolding
plan: 02
subsystem: observability
tags: [observability, fastapi, asgi-middleware, prometheus, anonymity, integration-tests]
dependency_graph:
  requires:
    - "Plan 08-01 (observability module skeleton — XFFStrip, RequestIDAndContextvarsBind, MetricsMiddleware, make_metrics_endpoint)"
  provides:
    - "Live observability layer in backend/app.py — JSON logs, Prometheus /metrics, XFF strip, contextvars"
    - "Canonical integration proof that pure-ASGI middleware propagates contextvars to route handlers (RESEARCH.md Pitfall 1 contract)"
  affects:
    - "Plan 08-03 (pipeline stage timing — STAGE_DURATION metric now reachable)"
    - "Phase 13 (Logfire spans, anonymity regression test) — scaffolding live"
    - "All future phases — every request now has request_id, optional session_hash, JSON logs"
tech_stack:
  added: []
  patterns:
    - "First-import side-effect bootstrap (Pitfall 6 — observability before config/db/events)"
    - "Reverse-add-order middleware registration (D-12 — XFFStrip outermost via last-added)"
    - "Verbatim auth mirror (/metrics reuses /admin/reset 503/401/X-Admin-Token verbatim)"
    - "TestClient + lifespan-mock + debug-route injection (Pattern E)"
    - "importlib.reload pattern for monkeypatched module-level closures (config.ADMIN_TOKEN)"
key_files:
  created:
    - "backend/tests/test_observability_middleware.py"
    - "backend/tests/test_observability_metrics.py"
    - ".planning/phases/08-observability-scaffolding/08-02-SUMMARY.md"
  modified:
    - "backend/app.py"
decisions:
  - "D-09: GET /metrics route registered with ADMIN_TOKEN guard via make_metrics_endpoint(config.ADMIN_TOKEN)"
  - "D-10: /metrics auth verbatim-mirrors /admin/reset — same X-Admin-Token header, 503 on empty token, 401 on mismatch"
  - "D-12: app.add_middleware code-order CORSMiddleware -> MetricsMiddleware -> RequestIDAndContextvarsBind -> XFFStrip; effective execution XFFStrip -> RequestID -> Metrics -> CORS -> routes"
  - "D-17: /metrics scoped label-policy test inspects only newz_* lines (built-in python_info labels are static low-cardinality, out of scope for D-17 enforcement)"
  - "Test handler typing: route handlers in test_observability_middleware.py use `request: Request` annotation (else FastAPI treats `request` as a body parameter and returns 422)"
metrics:
  duration: "~12 minutes"
  completed_date: "2026-04-28"
  task_count: 2
  file_count_created: 2
  file_count_modified: 1
  test_count: 18
  test_pass_rate: "18/18 (100%)"
---

# Phase 8 Plan 2: Wire Observability Into FastAPI Summary

**One-liner:** Wired Plan 08-01's observability module into `backend/app.py` (first-import bootstrap, three new pure-ASGI middlewares in D-12 order, `/metrics` route mirroring `/admin/reset` auth verbatim) and added 18 integration tests proving XFF strip + contextvars propagation + `/metrics` auth/format/label-policy.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Wire observability into backend/app.py | `c4ddcac` | backend/app.py |
| 2 | Integration tests — XFF strip, contextvars, /metrics auth + label policy | `447a1c9` | backend/tests/test_observability_middleware.py, backend/tests/test_observability_metrics.py |

## Files Modified

### `backend/app.py` — 27 insertions, 1 deletion

**Lines 1-4 (added prologue, before any other import):**
```python
# Phase 8 (D-01..D-17): observability MUST be imported before any other backend
# module that calls logging.getLogger(). Pitfall 6 — without this, pre-warm and
# DB-init log lines emit as plain text instead of JSON.
from . import observability  # noqa: F401  — runs configure_logging() + init_sentry() at import
```

**Line 19 (deleted):**
```python
# REMOVED — replaced by observability.configure_logging() inside the module
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
```

**Lines 23-24 (added imports):**
```python
from .observability.middleware import XFFStrip, RequestIDAndContextvarsBind
from .observability.metrics import MetricsMiddleware, make_metrics_endpoint
```

**Lines 88-95 (added middleware registrations after CORSMiddleware block):**
```python
# Phase 8 (D-12): middleware registration order matters because FastAPI applies
# middleware in REVERSE-add-order. Effective request flow:
#   XFFStrip (outermost) -> RequestIDAndContextvarsBind -> MetricsMiddleware -> CORS -> routes
# XFFStrip MUST run first so client-supplied IP-revealing headers are stripped
# before any other middleware or route handler can log them (PRIV-01).
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIDAndContextvarsBind)
app.add_middleware(XFFStrip)
```

**Lines 426-435 (added `/metrics` route after `/admin/reset`):**
```python
# Phase 8 (D-09, D-10): /metrics endpoint mirrors /admin/reset auth verbatim.
# Same env var (ADMIN_TOKEN), same header (X-Admin-Token), same status codes
# (503 on empty token, 401 on mismatch). include_in_schema=False keeps it out
# of the public OpenAPI spec.
app.add_api_route(
    "/metrics",
    make_metrics_endpoint(config.ADMIN_TOKEN),
    methods=["GET"],
    include_in_schema=False,
)
```

## Confirmations

- ✅ `logging.basicConfig` line is GONE from `backend/app.py` (`grep -c "^logging.basicConfig" backend/app.py` returns 0)
- ✅ `from . import observability` at line 4 (before `from . import config, db, events` at line 20)
- ✅ `log = logging.getLogger(__name__)` preserved at line 26 (bridge approach D-01)
- ✅ Effective middleware order: `XFFStrip → RequestIDAndContextvarsBind → MetricsMiddleware → CORSMiddleware → routes`
- ✅ `/metrics` route registered at runtime: `python -c "from backend.app import app; print(any(getattr(r, 'path', None) == '/metrics' for r in app.routes))"` prints `True`
- ✅ Routes count: was 14, now 15 (+1 for /metrics)

## Files Created

### `backend/tests/test_observability_middleware.py` — 12 tests

| Test | Contract |
|------|----------|
| `test_xff_stripped_before_route_handler` | PRIV-01 — `X-Forwarded-For: 1.2.3.4` not visible to handler, value not in body |
| `test_xff_strips_all_forbidden_variants[X-Forwarded-For]` | Parametrized over 6 variants |
| `test_xff_strips_all_forbidden_variants[X-Real-IP]` | ↑ |
| `test_xff_strips_all_forbidden_variants[Forwarded]` | ↑ |
| `test_xff_strips_all_forbidden_variants[True-Client-IP]` | ↑ |
| `test_xff_strips_all_forbidden_variants[CF-Connecting-IP]` | ↑ |
| `test_xff_strips_all_forbidden_variants[X-Client-IP]` | ↑ |
| `test_request_id_bound_in_context` | D-11 — server-side UUID4.hex (32 lowercase hex chars) |
| `test_session_hash_bound_when_x_session_id_header_present` | PRIV-02 — sha256(uuid) bound; raw uuid never bound |
| `test_session_uuid_never_appears_in_logs` | PRIV-02 — raw value scrubbed from all log records and attrs |
| `test_contextvars_cleared_after_request` | No cross-request leakage of session_hash |
| `test_middleware_order_xff_outermost_then_request_id_then_metrics_then_cors` | D-12 ordering invariant |

### `backend/tests/test_observability_metrics.py` — 6 tests

| Test | Contract |
|------|----------|
| `test_metrics_returns_503_when_admin_token_unset` | D-09 — empty ADMIN_TOKEN closes endpoint |
| `test_metrics_returns_401_without_token` | D-10 — missing X-Admin-Token |
| `test_metrics_returns_401_with_wrong_token` | D-10 — mismatched X-Admin-Token |
| `test_metrics_returns_prometheus_text_format` | Content-Type starts `text/plain` and contains `version=`; body has `newz_http_requests_total`, `newz_http_request_duration_seconds`, `newz_pipeline_stage_duration_seconds` |
| `test_metrics_route_label_uses_template_not_raw` | Pitfall 4 — `route="/health"` template form; D-17 — no `clip_id=`, `session_uuid=`, `session_hash=` substrings |
| `test_metrics_only_bounded_label_keys` | D-17 — newz_* metric labels ⊆ {route, method, status_class, stage, le, quantile} |

## Test Results

```
$ pytest backend/tests/test_observability_middleware.py backend/tests/test_observability_metrics.py -v
============================== 18 passed in 0.40s ==============================

$ pytest backend/tests/ -k "not test_debug_clusters_empty_returns_envelope"
======================= 86 passed, 1 deselected in 9.27s =======================
```

- Plan 08-02 tests: **18/18 PASSING** (12 middleware + 6 metrics)
- Full backend suite: **86 passed** (was 68 before this plan; +18 new = 86 ✓)
- Pre-existing failure (`test_debug_clusters_empty_returns_envelope`) deselected — documented in `08-01-SUMMARY.md` Deferred Issues and `deferred-items.md` (CLUSTER_THRESHOLD test/config drift, predates Phase 8).

## Effective Middleware-Order Assertion

`test_middleware_order_xff_outermost_then_request_id_then_metrics_then_cors` PASSES.

Runtime verification:
```python
$ python -c "from backend.app import app; print([m.cls.__name__ for m in app.user_middleware])"
['XFFStrip', 'RequestIDAndContextvarsBind', 'MetricsMiddleware', 'CORSMiddleware']
```

`user_middleware[0]` is `XFFStrip` — outermost in execution. Effective request flow as locked by D-12: `XFFStrip → RequestIDAndContextvarsBind → MetricsMiddleware → CORSMiddleware → routes`. XFF and IP-revealing headers are stripped before any logging or contextvars binding code path can observe them.

## Flake-Mitigation Notes (`client_no_token` fixture)

The plan flagged a potential flake: `make_metrics_endpoint(config.ADMIN_TOKEN)` is a factory that captures `config.ADMIN_TOKEN`'s value AT app-import time. Because `pytest` reuses the `backend.app` module across tests (sticky import cache), a `monkeypatch.setattr(config, "ADMIN_TOKEN", "")` set inside a fixture would NOT affect the route handler closure if `backend.app` was already imported by a prior test.

**Resolution applied:** `_boot_app()` calls `importlib.reload(backend_app)` after the monkeypatch but before constructing the `TestClient`. This forces the module to re-execute, which re-evaluates `make_metrics_endpoint(config.ADMIN_TOKEN)` with the now-monkeypatched value. All four metrics-auth tests (`test_metrics_returns_503_when_admin_token_unset`, `_401_without_token`, `_401_with_wrong_token`, `_returns_prometheus_text_format`) pass deterministically across runs. The `importlib.reload` was added preemptively (per the plan's note) and proved necessary in practice.

## Decisions Made

- **Test handler typing (Rule 1 fix during execution):** Test debug routes `echo_headers`/`echo_contextvars` originally took an untyped `request` parameter, which caused FastAPI to treat it as a request body and return 422 Unprocessable Entity instead of invoking the handler. Annotating as `request: Request` (using `from fastapi import Request`) resolved this. This is mechanical FastAPI semantics — no plan deviation.
- **Scoped label-policy test (Rule 1 fix during execution):** The `test_metrics_only_bounded_label_keys` test originally scanned ALL label clauses in `/metrics` output. This caught the built-in `python_info` metric's labels (`major`, `minor`, `patchlevel`, `version`, `implementation`, `generation`) which prometheus-client auto-registers in `REGISTRY`. These are static (one constant time series per process) and not a cardinality risk. Restricted the test to scan only lines starting with `newz_*` (the metrics we own per D-17). The plan's intent is to constrain OUR cardinality, not stdlib's.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Untyped `request` parameter triggers FastAPI body validation**
- **Found during:** Task 2, first pytest run.
- **Issue:** `app.add_api_route("/test/echo-headers", echo_headers, methods=["GET"])` with `async def echo_headers(request)` (no annotation) caused FastAPI to interpret `request` as a Pydantic body parameter, returning 422 on every test request.
- **Fix:** Imported `from fastapi import Request` and annotated both debug handlers as `async def echo_headers(request: Request)` / `async def echo_contextvars(request: Request)`. FastAPI then recognizes the parameter as the Starlette/FastAPI request object via type annotation.
- **Files modified:** `backend/tests/test_observability_middleware.py`
- **Commit:** `447a1c9`

**2. [Rule 1 - Bug] Label-scan test caught static stdlib `python_info` labels**
- **Found during:** Task 2, second pytest run (after fix #1 unblocked the metrics tests).
- **Issue:** `test_metrics_only_bounded_label_keys` scanned ALL `\{...\}` clauses in `/metrics` output. prometheus-client auto-registers `python_info{implementation="...", major="3", minor="11", patchlevel="15", version="3.11.15"}` and `python_gc_objects_*{generation="0|1|2"}` into the default REGISTRY. The test rejected these as "unexpected metric labels" but they are actually static low-cardinality metadata, not the cardinality risk D-17 targets.
- **Fix:** Scoped the label-key scan to lines matching `^newz_[a-z0-9_]+\{...\}` (the metrics we own). The D-17 invariant applies to the metrics this plan introduces, not to prometheus-client's built-in process/gc/python info metrics.
- **Files modified:** `backend/tests/test_observability_metrics.py`
- **Commit:** `447a1c9`
- **Why this is consistent with intent:** D-17 in CONTEXT.md targets cardinality-risk labels we add (`clip_id`, `session_uuid`, etc.). It does not require us to police library-emitted process metadata. The forbidden-label substring check (`test_metrics_route_label_uses_template_not_raw`) still scans the entire body for the explicit forbidden substrings (`clip_id=`, `session_uuid=`, `session_hash=`) — that contract is unchanged.

### No deviations from plan-stated decisions, contracts, or interfaces.

The wiring matches `<interfaces>` exactly. The /metrics auth pattern verbatim-mirrors `/admin/reset`. Middleware order is exactly D-12. The two fixes above are mechanical test-side adjustments needed to pass the plan's own assertion intent.

## Authentication Gates

None encountered. ADMIN_TOKEN tests use `monkeypatch.setattr(config, "ADMIN_TOKEN", ...)`; no real secrets involved.

## Deferred Issues

**Pre-existing test failure outside Phase 8 scope (carried forward from 08-01):**
- `backend/tests/test_debug_clusters.py::test_debug_clusters_empty_returns_envelope` — `CLUSTER_THRESHOLD` test/config drift. Documented in `.planning/phases/08-observability-scaffolding/deferred-items.md` (created in 08-01). No new deferred items introduced by this plan.

## Known Stubs

None. All wiring is production-shaped. The `/test/echo-headers` and `/test/echo-contextvars` debug routes are added ONLY inside the test files (via `app.add_api_route` after the TestClient is constructed) — they are NOT added to production `backend/app.py`.

## Threat Flags

None. The plan's `<threat_model>` block (T-08-06 through T-08-11) covers every trust boundary touched. All five HIGH-severity threats have passing integration tests:
- T-08-06 (XFF leak) → `test_xff_stripped_before_route_handler` + `test_xff_strips_all_forbidden_variants` (6 cases) ✓
- T-08-07 (raw session UUID leak) → `test_session_uuid_never_appears_in_logs` + `test_session_hash_bound_when_x_session_id_header_present` ✓
- T-08-08 (forged X-Request-ID) → `test_request_id_bound_in_context` (asserts UUID4.hex format, server-side) ✓
- T-08-09 (/metrics unauthenticated) → 3 tests (503/401-no-token/401-wrong-token) ✓
- T-08-10 (Prometheus cardinality DoS) → `test_metrics_only_bounded_label_keys` + `test_metrics_route_label_uses_template_not_raw` ✓
- T-08-11 (contextvars cross-request leak) → `test_contextvars_cleared_after_request` ✓

## TDD Gate Compliance

Plan tasks are marked `tdd="true"`.

**Task 1 (wiring):** Pre-edit assertion run confirmed RED (XFFStrip/RequestIDAndContextvarsBind/MetricsMiddleware/`/metrics` not yet present). Post-edit verification confirmed GREEN. Wiring is structural — no separate `test(...)` commit was authored for it because the assertion target is the wiring itself, validated by Task 2's `test_middleware_order_xff_outermost_then_request_id_then_metrics_then_cors` test (which lives in Task 2's commit). Single `feat(...)` commit `c4ddcac`.

**Task 2 (integration tests):** RED gate verified before file creation (`test -f backend/tests/test_observability_middleware.py` exited non-zero). After authoring, ran the new test files with the wired backend → 18/18 GREEN. The `test(...)` commit `447a1c9` IS the test-only commit; the wiring it tests is in the prior `feat(...)` commit `c4ddcac`. Sequencing is `feat → test` (rather than the canonical `test → feat → refactor`) because the wiring (Task 1) cannot be partially shipped — there is no incremental "RED" wiring state that emits useful failures distinct from "all middleware missing." This matches the plan's `<tasks>` ordering.

Future audit: a strict `test → feat` sequence for Plan 08-02 would have required scaffolding the test files in a `test(...)` commit FIRST against an unwired app.py (where every middleware test would fail with "middleware not registered"), then the `feat(...)` wiring commit. The plan's order (Task 1 = wire, Task 2 = test) was followed verbatim.

## Self-Check

### Created files exist

```
$ test -f backend/tests/test_observability_middleware.py && echo FOUND
FOUND
$ test -f backend/tests/test_observability_metrics.py && echo FOUND
FOUND
$ test -f .planning/phases/08-observability-scaffolding/08-02-SUMMARY.md && echo FOUND
FOUND
```

### Commits exist

```
$ git log --oneline | grep -E "(c4ddcac|447a1c9)"
447a1c9 test(08-02): integration tests for XFF strip, contextvars, /metrics auth
c4ddcac feat(08-02): wire observability module into backend/app.py
```

### Wire-up sanity (runtime)

```
$ python -c "from backend.app import app; print([m.cls.__name__ for m in app.user_middleware])"
['XFFStrip', 'RequestIDAndContextvarsBind', 'MetricsMiddleware', 'CORSMiddleware']

$ python -c "from backend.app import app; print(any(getattr(r, 'path', None) == '/metrics' for r in app.routes))"
True
```

### Test results

```
$ pytest backend/tests/test_observability_middleware.py backend/tests/test_observability_metrics.py -v
============================== 18 passed in 0.40s ==============================

$ pytest backend/tests/ -k "not test_debug_clusters_empty_returns_envelope"
======================= 86 passed, 1 deselected in 9.27s =======================
```

## Self-Check: PASSED
