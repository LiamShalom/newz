# Phase 14: Recompile Montage on New Parent in Existing Cluster — Pattern Map

**Mapped:** 2026-04-30
**Approach:** Path B-lite (per RESEARCH.md § Decision Matrix — recommended)
**Files analyzed:** 4 (1 NEW test file + 3 MODIFIED source files)
**Analogs found:** 4 / 4 — every site has a clean in-codebase analog. No external pattern needed.

## Important Note on RESEARCH/CONTEXT Drift

The CONTEXT.md instructions reference a "Logfire span" at `compile.py:551`. **There is no Logfire in this codebase.** `grep -rn logfire backend/` returns zero hits. The actual observability primitives at that site are:

1. `events.broadcast({"type": "compile_started", ...})` at `compile.py:551-555` — SSE broadcast, not a tracing span.
2. `STAGE_DURATION.labels(stage="compile").time()` — Prometheus histogram (in `run.py:149-151`, not yet wrapped at the recompile call).
3. `log.info(...)` / `log.warning(...)` — stdlib logging bridged via `structlog.contextvars` at `run.py:83`.

**Pattern recommendation:** add a `recompile=True` field to the `compile_started` SSE event payload (cheapest correct-shape signal) AND a `log.info("recompile triggered cluster_id=%s", cluster_id)` at the `run.py` dispatch site. No Prometheus label change (per RESEARCH § Open Questions Q3 — avoid label-cardinality blowup, OBS-04).

The `12-CONTEXT.md` reference to `compile_count` Logfire span attribute should be re-read as "extra field on the existing `compile_started` event + structlog-bridged log line."

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/pipeline/run.py` (modify — add `_should_recompile` + branch) | pipeline orchestrator | event-driven (post-cluster-join dispatch) | `_should_compile()` in same file (run.py:42-53) | exact (sibling helper) |
| `backend/pipeline/compile.py` (modify — add `_RECOMPILE_COUNTS` dict + soft-warn) | pipeline service | event-driven | `_attempts` dict in `rate_limit.py:17` and `_cache` in `geocode.py:23` | role-match (in-process counter dict) |
| `backend/config.py` (modify — add 2 constants) | config | static | `MODERATION_MAX_BUDGET_S` at `config.py:75` | exact |
| `backend/tests/pipeline/test_recompile.py` (NEW) | test (integration) | request-response with mocks | `backend/tests/pipeline/test_moderate.py` | exact (same dir, same fixture style) |

---

## Pattern Assignments

### `backend/pipeline/run.py` — add `_should_recompile()` helper + elif-branch

**Analog:** `_should_compile()` at `backend/pipeline/run.py:42-53`, called at `backend/pipeline/run.py:149-151`.

**Existing gate body (verbatim, lines 42-53):**

```python
async def _should_compile(cluster_id: str) -> bool:
    """Pivot 2 gate (CMP-01 + CMP-09): compile only when cluster has >=2 distinct
    PARENT uploads. Solo-parent clusters NEVER compile, even with N children.

    The gate runs upstream of compile_segment so we never spend tokens / 60s
    wall-clock budget on a doomed compile. count_distinct_parents_in_cluster
    is the single source of truth — defensive against any stray child cluster_id.
    """
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    if parent_count < 2:
        return False
    return await db.set_compile_in_flight(cluster_id, True, ttl_seconds=30.0)
```

**Existing dispatch site (verbatim, lines 149-151):**

```python
        if await _should_compile(cluster_id):
            asyncio.create_task(compile_segment(cluster_id))
            log.info("compile triggered cluster_id=%s", cluster_id)
```

**What to copy:**
- Function signature shape: `async def _should_recompile(cluster_id: str, new_clip_id: str) -> bool:`
- Module-level docstring style with rationale + which contract enforces what
- Single-purpose return that bottoms out at `db.set_compile_in_flight(...)` so the CAS lock + TTL is reused (research-recommended, RESEARCH lines 134-139)
- Dispatch pattern: `elif await _should_recompile(...)` after the existing `if await _should_compile(...)` block; `asyncio.create_task(compile_segment(cluster_id))` is unchanged (idempotent at compile.py:664).

**What to adapt:**
- New helper takes a second arg `new_clip_id` (need to read `clip.parent_id` to skip child joins).
- `ttl_seconds=config.RECOMPILE_DEBOUNCE_S` instead of `30.0` (60s default; longer coalescing window for recompile path).
- Add four short-circuit conditions before the CAS call (per RESEARCH lines 116-136):
  1. `clip.parent_id is not None` → child of existing parent, no recompile.
  2. `db.get_segment_for_cluster(cluster_id) is None` → no segment yet, `_should_compile` owns first publish.
  3. `count_distinct_parents_in_cluster(cluster_id) < 2` → defensive (impossible if seg exists).
  4. Then `set_compile_in_flight(...ttl=RECOMPILE_DEBOUNCE_S)`.
- Gate the elif on `config.RECOMPILE_ON_NEW_PARENT` flag (per RESEARCH § Open Questions Q6 — feature-flag for gradual rollout).
- Add `log.info("recompile triggered cluster_id=%s parent_id=%s", cluster_id, new_clip_id)` after the dispatch (RESEARCH line 110).

**Also touch `_resume_pipeline` at run.py:196-198?** The `_resume_pipeline` path (admin clears unknown clip → re-enter pipeline) reuses the same dispatch pattern. Apply the same elif-branch there for consistency. The clip being resumed is a parent (only parents have moderate decisions — per the existing flow), so `_should_recompile` will short-circuit on the `parent_id is not None` check correctly when resumed clips happen to be children. Confirm the 1-line addition does not regress moderate-resume coverage.

---

### `backend/pipeline/compile.py` — add `_RECOMPILE_COUNTS` dict + soft-warn at threshold 5

**Analog 1 (best — module-level mutable dict, async-process-local):** `backend/rate_limit.py:7-19`

```python
"""In-memory per-session rate limiter for anonymous comments (Phase 01 feature track).

Single-process FastAPI + --workers 1 makes process-local state authoritative.
Resets on restart — acceptable at pilot scale; revisit if we move beyond one worker
or persist this layer.
"""
import asyncio
import time
from collections import defaultdict, deque

# (max_count, window_seconds)
COMMENT_LIMITS: list[tuple[int, int]] = [
    (5, 300),     # 5 per 5 minutes
    (10, 3600),   # 10 per hour
]

_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()
_LARGEST_WINDOW = max(w for _, w in COMMENT_LIMITS)
```

**Analog 2 (simpler — bounded module-level cache, no lock):** `backend/pipeline/geocode.py:18-23`

```python
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "Newz/1.0 (hyperlocal-news-demo)"
_DEFAULT = "Pasadena, CA"
_CACHE_MAX = 512

_cache: dict[tuple[float, float], str] = {}
```

**Analog 3 (in-tree, same module pattern):** `backend/pipeline/cluster.py:68-69`

```python
CLUSTERS: dict[str, ClusterCache] = {}
_LOCK: asyncio.Lock = asyncio.Lock()
```

**What to copy from rate_limit.py:**
- Single in-process dict scoped at module level — recompile counter only needs to survive within one Railway instance lifecycle (R4 in RESEARCH § Risk).
- The CLAUDE.md-style header docstring acknowledging "Resets on restart — acceptable at pilot scale; revisit if we move beyond one worker or persist this layer."
- Type-annotated declaration pattern: `_RECOMPILE_COUNTS: dict[str, int] = {}` (mirrors the `_attempts: dict[str, deque[float]] = defaultdict(deque)` shape).

**What to adapt:**
- No `asyncio.Lock` required — `dict.get()` + `dict[k] = v` are atomic at the asyncio scheduling boundary; the recompile counter is monotonic-incrementing and approximate-by-design (a missed increment under contention is fine; we only soft-warn at ≥5).
- Plain `dict[str, int]`, no defaultdict needed — `_RECOMPILE_COUNTS.get(cluster_id, 0) + 1` is idiomatic.

**Soft-warn pattern analog (`log.warning(...)` for budget-overrun-style warning):** `backend/pipeline/compile.py:430-434` (parent diversity guard) and `compile.py:610` (stitch timeout).

```python
# compile.py:430-434 (parent diversity guard) — the prototype to clone
log.warning(
    "parent diversity guard: angle-selector picked %d distinct parent(s) "
    "(cluster has %d). Augmenting with %d run(s): %s",
    len(picked_parents), len(cluster_parents), len(additions), additions,
)
```

```python
# compile.py:610 — short-form stitch timeout warning
log.warning("stitch TIMEOUT cluster_id=%s after 30s", cluster_id)
```

**What to copy:**
- `log.warning("...", ...)` printf-style formatting — never f-strings (the project uses stdlib logging printf for structlog bridge compatibility per WR-01 in run.py:75-81).
- Include `cluster_id=%s` as the first identifying field (matches every other log line in compile.py — searchable by cluster_id in production logs).

**What to adapt for `_RECOMPILE_COUNTS` soft-warn site (insert near top of `compile_segment`, after line 555 and before the LLM gather at 567):**

```python
# Approximate — clone diversity-guard log style; no defensive try/except needed.
seg_existing = await db.get_segment_for_cluster(cluster_id)
if seg_existing is not None:
    recompile_count = _RECOMPILE_COUNTS.get(cluster_id, 0) + 1
    _RECOMPILE_COUNTS[cluster_id] = recompile_count
    if recompile_count >= 5:
        log.warning(
            "compile recompile_count_high cluster_id=%s count=%d — investigate hot-event behavior",
            cluster_id, recompile_count,
        )
```

**`recompile=True` event-attribute analog:** `backend/pipeline/compile.py:551-555` (existing `compile_started` SSE broadcast).

```python
await events.broadcast({
    "type": "compile_started",
    "cluster_id": cluster_id,
    "started_at": started_at,
})
```

**What to copy:** the dict-literal shape and the `events.broadcast` call.

**What to adapt:** add a `"recompile": seg_existing is not None` boolean field. Existing SSE consumers ignore unknown fields (frontend `useEventSource` reads via discriminated union on `type`, not on field whitelist). Backwards-compatible. Mirrors RESEARCH line 80 ("Add `recompile=true` attribute to the existing Logfire `compile` span" — substitute SSE-event-field for span-attribute since Logfire doesn't exist).

---

### `backend/config.py` — add `RECOMPILE_DEBOUNCE_S` and `RECOMPILE_ON_NEW_PARENT`

**Analog (env-overridable float constant):** `backend/config.py:75` — `MODERATION_MAX_BUDGET_S`

```python
# Phase 11: Moderation gate (post-reconciliation D-24 — classifier-only CSAM detection)
# GEMINI_MODERATION_MODEL: separate from GEMINI_MODEL (L18) so the moderation
#   classifier model can iterate independently of the caption pipeline model.
GEMINI_MODERATION_MODEL: str = os.environ.get("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")
# MODERATION_MAX_BUDGET_S: absolute upper-bound on the gate (D-03). Default 20s.
#   Cancel-when-embed-finishes is the typical primitive (Marengo's elapsed time
#   bounds Gemini); this is the safety floor when both tasks exceed Marengo p99.
MODERATION_MAX_BUDGET_S: float = float(os.environ.get("MODERATION_MAX_BUDGET_S", "20.0"))
```

**Analog (env-overridable bool):** `backend/config.py:55`

```python
OFFLINE_DEMO: bool = os.environ.get("OFFLINE_DEMO", "false").strip().lower() == "true"
```

**What to copy:**
- Phase-prefixed comment header (`# Phase 14: Recompile gate (D-?? in 14-PLAN)`).
- Type annotation + `os.environ.get(..., "<default>")` + `float(...)` / lowercase-strip-equals-true pattern.
- Comment per-line documenting each constant's role and default-value rationale.

**What to add (verbatim block to insert at end of config.py):**

```python
# Phase 14: Recompile gate
# RECOMPILE_DEBOUNCE_S: cooldown window after a compile completes during which
#   subsequent new-parent joins do not trigger a fresh recompile. 60s coalesces
#   typical 4-parent burst from a single hot event into one recompile while
#   keeping per-cluster recompile rate ≤60/hr at steady state. Distinct from
#   the 30s first-publish TTL in set_compile_in_flight.
RECOMPILE_DEBOUNCE_S: float = float(os.environ.get("RECOMPILE_DEBOUNCE_S", "60.0"))
# RECOMPILE_ON_NEW_PARENT: feature flag for gradual rollout. When False, the
#   _should_recompile gate short-circuits and the legacy v1.0 behavior (compile
#   fires only on first ≥2-parent threshold cross) is preserved. Cheap rollback
#   if recompile-storm scenarios manifest in pilot traffic.
RECOMPILE_ON_NEW_PARENT: bool = os.environ.get("RECOMPILE_ON_NEW_PARENT", "true").strip().lower() == "true"
```

---

### `backend/tests/pipeline/test_recompile.py` — NEW integration test file (6 tests)

**Analog (closest in repo — same directory, same fixture style, same Phase-N integration shape):** `backend/tests/pipeline/test_moderate.py`

**Imports block to copy verbatim (test_moderate.py:1-26):**

```python
"""Phase 11 moderate.py unit + behavioral tests.

Covers MOD-01..06, MOD-09, MOD-10, PRIV-03 (see RESEARCH.md § "Phase Requirements → Test Map").
The cancel-when-embed-finishes test uses asyncio.Event for deterministic ordering
(no real timing dependence). The hard-block test verifies the reported_csam preservation
row is written BEFORE cleanup_blocked_clip is called (statutory ordering per § 2258A).

NO real Gemini calls. NO real CSAM corpus (statutorily protected). All tests use
patched module-level helpers + synthetic verdict JSON.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
```

**Adapt for Phase 14:** drop `httpx` (no outbound classifier calls in recompile path), drop `json`/`time` if not used, keep `AsyncMock`. Add a single-line module docstring naming the 6 tests by short title.

**Fixture pattern to copy (test_moderate.py:44-108) — `patched_moderate` style:**

```python
@pytest.fixture
def patched_moderate(monkeypatch):
    """Patch _fetch_clip_bytes + db writers + embed_worker + cleanup at module scope.

    Yields a SimpleNamespace of the AsyncMocks/MagicMocks so tests can assert
    against call_args.
    """
    import types as _types
    from backend.pipeline import moderate as mod

    monkeypatch.setenv("OFFLINE_DEMO", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    # ... (env-set + importlib.reload + monkeypatch.setattr chain) ...

    write_decision = AsyncMock(return_value="dec_id_1")
    monkeypatch.setattr(mod.db, "write_moderation_decision", write_decision)
    # ... etc ...

    ns = _types.SimpleNamespace(
        mod=mod,
        write_moderation_decision=write_decision,
        # ...
    )
    yield ns
```

**What to copy:**
- `_types.SimpleNamespace` return shape — gives tests `pm.compile_segment.assert_awaited_once()`-style ergonomics.
- `monkeypatch.setenv(...)` + `importlib.reload(backend.config)` to make new `RECOMPILE_DEBOUNCE_S` / `RECOMPILE_ON_NEW_PARENT` env vars visible.
- `AsyncMock(return_value=...)` for DB writers.
- `monkeypatch.setattr(<mod_handle>, <name>, <mock>)` for hooking pipeline internals.

**What to adapt for Phase 14 fixtures:**

- New fixture `multi_parent_compiled_cluster` (per RESEARCH line 267) — sets up 2-parent cluster with already-published `segments` row. Uses the `fresh_db` Postgres fixture in `conftest.py:17-41` if `DATABASE_URL` is set; otherwise uses pure mocks (`db.get_segment_for_cluster = AsyncMock(return_value={...})`).
- Mock `compile_segment` call counter via `unittest.mock.AsyncMock(wraps=...)` so we can assert `mock_compile.await_count == 2` on the recompile fire (RESEARCH line 268).
- Reuse the existing `gemini_moderation_mock` fixture from `conftest.py:88-131` for the `test_recompile_does_not_bypass_moderation_block` test (verifies blocked clips don't reach cluster_worker).

**Full async test body to copy (test_moderate.py:165-192) — Test 2: happy-path skeleton:**

```python
@pytest.mark.asyncio
async def test_moderate_pass_happy_path(patched_moderate):
    """Happy path: classifier all-pass → decision='passed' provider='gemini_flash_lite'."""
    pm = patched_moderate

    result = await pm.mod.moderate_clip("clip_abc")

    assert result.decision == "passed"
    assert result.provider == "gemini_flash_lite"
    assert result.reason is None
    assert result.soft_flag_categories == []
    assert result.embed_result is not None  # parent_clip_id, parent_vec tuple

    # Exactly one moderation_decisions row written with provider gemini_flash_lite.
    pm.write_moderation_decision.assert_awaited_once()
    kwargs = pm.write_moderation_decision.await_args.kwargs
    assert kwargs["clip_id"] == "clip_abc"
    assert kwargs["provider"] == "gemini_flash_lite"
    assert kwargs["decision"] == "passed"
    assert kwargs["reason"] is None
    assert kwargs["prompt_version"] == pm.mod.PROMPT_VERSION
    assert isinstance(kwargs["latency_ms"], int) and kwargs["latency_ms"] >= 0

    # Hard-block side effects must NOT have fired.
    pm.write_reported_csam.assert_not_awaited()
    pm.cleanup_blocked_clip.assert_not_awaited()
    pm.set_clip_hidden.assert_not_awaited()
```

**What to copy:**
- `@pytest.mark.asyncio` decorator (already enabled via `pytest-asyncio` per `conftest.py:13`).
- `pm = <fixture_name>` aliasing for terse mock assertions.
- Single-line docstring naming the precise behavior asserted.
- `assert_awaited_once()` / `assert_not_awaited()` polarity.
- `kwargs = <mock>.await_args.kwargs` extraction pattern.

**What to adapt:** swap `moderate_clip` for `_should_recompile` + `compile_segment`. The 6 test names from RESEARCH § Required Tests:

1. `test_recompile_fires_on_new_distinct_parent` — happy path: 2 parents → compile fires → 3rd parent joins → `compile_segment` await count = 2.
2. `test_recompile_debounce_coalesces_burst` — 3 parents within `RECOMPILE_DEBOUNCE_S` → exactly 1 recompile.
3. `test_recompile_skipped_for_child_of_existing_parent` — `clip.parent_id != None` → `_should_recompile` returns False.
4. `test_recompile_offline_demo_e2e` — `OFFLINE_DEMO=true`, 3-parent flow, assert no httpx via `respx`.
5. `test_recompile_preserves_per_clip_moderation` — 3rd parent has `hate.verdict=flag` → re-emitted segment row has `soft_flag=true`.
6. `test_recompile_does_not_bypass_moderation_block` — 3rd parent gets `decision='blocked'` from `gemini_moderation_mock` → cluster_worker never sees the clip → no recompile.

**Test 4 (OFFLINE_DEMO) extra pattern to copy — test_moderate.py:115-159:** the `respx_mock.post(...).respond(...)` route pattern + `assert <route>.call_count == 0` assertion is the gold-standard for "no outbound traffic" verification (MOD-10).

```python
upload_route = respx_mock.post(
    "https://generativelanguage.googleapis.com/upload/v1beta/files"
).respond(json={})
# ...
assert upload_route.call_count == 0, "OFFLINE_DEMO=true must not hit Gemini Files (MOD-10 violation)"
```

---

## Shared Patterns

### structlog contextvars binding (apply at every async-task entry point)

**Source:** `backend/pipeline/run.py:5,83-84,156-157`

```python
from structlog.contextvars import bind_contextvars, unbind_contextvars

# at function entry:
bind_contextvars(clip_id=clip_id)
try:
    # ... pipeline work ...
finally:
    unbind_contextvars("clip_id")
```

**Apply to:** none of Phase 14's new code adds a top-level async task — `compile_segment` already binds via `_should_compile` upstream context. **No new bind site needed.** Document this as a non-action.

### Idempotent CAS lock via `set_compile_in_flight`

**Source:** `backend/db_postgres.py:590-612`

```python
async def set_compile_in_flight(cluster_id: str, value: bool, ttl_seconds: float = 30.0) -> bool:
    """Atomic compare-and-set. Returns True if lock acquired/cleared, False if already held."""
    now = time.time()
    pool = get_pool()
    if value:
        tag = await pool.execute(
            """UPDATE clusters
               SET compile_in_flight = 1, last_compile_at = $1
               WHERE id = $2
                 AND (compile_in_flight = 0 OR last_compile_at < $3)""",
            now, cluster_id, now - ttl_seconds,
        )
        return tag.endswith(" 1")
    else:
        await pool.execute(
            "UPDATE clusters SET compile_in_flight = 0 WHERE id = $1",
            cluster_id,
        )
        return True
```

**Apply to:** `_should_recompile()` reuses this verbatim — pass `ttl_seconds=config.RECOMPILE_DEBOUNCE_S` (60.0 default) instead of 30.0. **No DB-helper change required.** This is the single most important "no new code" win: the existing CAS clause `WHERE compile_in_flight = 0 OR last_compile_at < $3` already implements both first-publish and recompile debouncing — only the TTL changes per call site.

### printf-style logging (never f-strings)

**Source:** every `log.info(...)` / `log.warning(...)` site in `backend/pipeline/`

```python
log.info("compile triggered cluster_id=%s", cluster_id)        # run.py:151
log.warning("stitch TIMEOUT cluster_id=%s after 30s", cluster_id)  # compile.py:610
```

**Apply to:** every new log line in run.py and compile.py changes. Reason: structlog bridge in `observability/logging_config.py` re-formats printf args structurally; f-strings flatten to a single message field and lose searchability.

### `events.broadcast` SSE event payload shape

**Source:** `backend/pipeline/compile.py:551-555, 690-694`

```python
await events.broadcast({
    "type": "compile_started",
    "cluster_id": cluster_id,
    "started_at": started_at,
})
# ...
await events.broadcast({
    "type": "segment_published",
    "cluster_id": cluster_id,
    "segment_id": segment_id,
})
```

**Apply to:** Phase 14 reuses `segment_published` verbatim (RESEARCH § Decision Matrix — "no new event type"). Optional additive enhancement: include `"recompile": True` on the `compile_started` payload when `seg_existing is not None`.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | Every new pattern in Phase 14 has a clean in-codebase analog. Path B-lite was chosen specifically because it requires zero novel patterns. |

---

## Metadata

**Analog search scope:** `backend/pipeline/`, `backend/tests/`, `backend/tests/pipeline/`, `backend/`, `backend/observability/`
**Files scanned:** ~30 (run.py, compile.py, cluster.py, moderate.py, rate_limit.py, geocode.py, config.py, db_postgres.py, all `tests/test_*.py` and `tests/pipeline/test_*.py`)
**Pattern extraction date:** 2026-04-30
**Cross-checks performed:**
- Confirmed no Logfire dependency exists — `grep -rn logfire backend/` returns 0 hits. RESEARCH/CONTEXT references to "Logfire span" remapped to existing SSE-event-field + structlog-log-line pattern.
- Confirmed `_attempts` dict in `rate_limit.py` is the closest "in-process counter dict, resets on restart" analog for `_RECOMPILE_COUNTS`.
- Confirmed `test_moderate.py` is the closest test analog (same dir, integration shape, Phase-N labelled, uses `respx`/`monkeypatch`/`AsyncMock`).
- Confirmed `set_compile_in_flight`'s CAS clause already supports the variable-TTL recompile-debouncing pattern with no DB-helper change.

## PATTERN MAPPING COMPLETE
