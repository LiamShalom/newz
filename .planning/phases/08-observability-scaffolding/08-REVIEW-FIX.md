---
phase: 08-observability-scaffolding
fixed_at: 2026-04-28T00:00:00Z
review_path: .planning/phases/08-observability-scaffolding/08-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 8: Code Review Fix Report

**Fixed at:** 2026-04-28
**Source review:** `.planning/phases/08-observability-scaffolding/08-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (1 critical + 4 warnings)
- Fixed: 5
- Skipped: 0
- Tests: 44/44 observability tests pass after every fix

## Fixed Issues

### CR-01: `/metrics` and `/admin/reset` use non-constant-time token comparison

**Files modified:** `backend/app.py`, `backend/observability/metrics.py`
**Commit:** `ccfdc7e`
**Applied fix:** Replaced `x_admin_token != admin_token` with `hmac.compare_digest(x_admin_token, admin_token)` in both `/metrics` (observability/metrics.py) and `/admin/reset` (app.py). Added `import hmac` to both files. The mirror property between the two endpoints is preserved verbatim — both now use constant-time comparison and read `config.ADMIN_TOKEN` per-request. Comment cross-references each fix-site.

### WR-01: `clip_id` contextvar binding contract documented but never implemented

**Files modified:** `backend/app.py`, `backend/pipeline/run.py`, `backend/observability/middleware.py`
**Commit:** `ccb228e`
**Applied fix:** Added `bind_contextvars(clip_id=clip_id)` immediately after `db.insert_clip` in POST `/clips` (app.py). In `run_pipeline` (pipeline/run.py), wrapped the body in `try/finally` with `bind_contextvars(clip_id=clip_id)` at entry and `unbind_contextvars("clip_id")` in `finally` — necessary because `run_pipeline` runs in its own `asyncio.create_task` context, so the request-scoped contextvar set in app.py does not propagate. Removed redundant `clip_id=%s` from existing `%s` log f-strings in run.py since clip_id now appears as a top-level structured field (JSON consumers can filter by field equality, not substring match). Updated `RequestIDAndContextvarsBind` docstring in middleware.py to reflect the now-implemented binding sites.

### WR-02: `_scrub` only redacts ONE of four broadcastable secrets

**Files modified:** `backend/pipeline/run.py`
**Commit:** `28248f7`
**Applied fix:** Replaced the single-secret check with iteration over a tuple of all configured secrets: `TWELVELABS_API_KEY`, `GEMINI_API_KEY`, `ADMIN_TOKEN`, `SENTRY_DSN`, plus `os.environ.get("ANTHROPIC_API_KEY", "")` (since Anthropic key is read directly from env, not centralized in `config.py` — IN-02 territory, deferred). Added `import os`. Docstring enumerates each secret and why it can plausibly appear in a stack trace.

### WR-03: `make_metrics_endpoint` captures `ADMIN_TOKEN` at import time

**Files modified:** `backend/app.py`, `backend/observability/metrics.py`
**Commit:** `ccfdc7e` (combined with CR-01 — both touch the same auth code path)
**Applied fix:** Changed `make_metrics_endpoint(admin_token: str)` to `make_metrics_endpoint()` (no argument). The route handler now reads `config.ADMIN_TOKEN` per-request inside the `metrics()` body, mirroring `/admin/reset`'s `expected = config.ADMIN_TOKEN` pattern. Updated the call site in app.py to drop the argument: `make_metrics_endpoint()`. The `importlib.reload` dance in `test_observability_metrics.py:_boot_app` is now technically unnecessary, but left in place — removing it is a test-only cleanup not in scope for this review.

### WR-04: `MetricsMiddleware` mislabels unhandled ASGI exceptions as 5xx

**Files modified:** `backend/observability/metrics.py`
**Commit:** `cee3f85`
**Applied fix:** Added `try/except/finally` block: catches escaping exceptions, sets `exception_escaped = True`, re-raises so Starlette's outer exception handlers still convert to 500. In the `finally` block, picks `status_class = "exception"` when `exception_escaped` is True, otherwise the existing `_status_class(status_holder["code"])` ("2xx"/"3xx"/"4xx"/"5xx"). Added detailed docstring on `MetricsMiddleware` documenting the semantic distinction so dashboard consumers don't conflate real 500s with escaped ASGI exceptions when computing availability SLOs. Cardinality stays bounded — only one new label value (`"exception"`) added to the existing four.

## Skipped Issues

None — all in-scope findings (CR-01, WR-01, WR-02, WR-03, WR-04) were fixed and verified.

## Verification

After each fix:
- Tier 1: Re-read modified file section, confirmed fix text + surrounding code intact.
- Tier 2: Ran `python -c "import ast; ast.parse(...)"` — all files parse cleanly.
- Tier 3: Ran `backend/.venv/bin/pytest -q backend/tests/test_observability_*.py` — all 44 tests pass after every commit.

Pre-existing failure in `backend/tests/test_debug_clusters.py::test_debug_clusters_empty_returns_envelope` (asserts `gps_radius_m == 200.0` but config has `50.0`) was confirmed to exist BEFORE any phase-8 fix by stashing changes and re-running. Out of scope for this phase 8 review-fix session.

## Out of scope (Info findings — fix_scope=critical_warning)

IN-01 through IN-05 not addressed in this iteration (info severity, fix_scope was critical_warning).

---

_Fixed: 2026-04-28_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
