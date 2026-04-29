# Phase 8: Observability Scaffolding - Pattern Map

**Mapped:** 2026-04-28
**Files analyzed:** 11 (6 new + 5 modified) + 4 new test files
**Analogs found:** 9 / 11 strong matches; 2 new patterns (no analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/observability/__init__.py` | bootstrap/init | startup-time | `backend/app.py:39-55` (`_pre_warm_sdk` env-gated init) + `backend/config.py` (module-import side effects) | role-match (env-gated SDK init pattern) |
| `backend/observability/logging_config.py` | config helper | startup-time | `backend/app.py:19` (`logging.basicConfig` call) | replacement target — direct |
| `backend/observability/sentry.py` | bootstrap/init | startup-time, gated | `backend/app.py:39-55` (`_pre_warm_sdk`) | role-match (env-gated, optional, INFO-log on skip) |
| `backend/observability/metrics.py` | utility (module globals + factory) | request-response + event-driven | (no existing analog — new pattern) | NO ANALOG |
| `backend/observability/anonymity.py` | pure-function helper | transform | `backend/app.py:120-126` (`_haversine_m` pure-function helper) | role-match (pure function, no state) |
| `backend/observability/middleware.py` | middleware (pure ASGI) | request-response | `backend/app.py:74-80` (`CORSMiddleware` registration) — registration pattern only; pure-ASGI implementation has no in-tree analog | partial (registration only) |
| `backend/app.py` (modify) | controller + bootstrap | request-response | self — same file | exact (in-place edit) |
| `backend/config.py` (modify) | config | env-var load | `backend/config.py:11,17,35` (existing env-var lines) | exact (extend pattern) |
| `backend/requirements.txt` (modify) | manifest | n/a | self | exact (append pinned versions) |
| `backend/.env.example` (modify) | docs | n/a | self | exact (append documented vars) |
| `backend/tests/test_observability_anonymity.py` | test (pure unit) | n/a | `backend/tests/test_events_sse.py` (smallest pure-unit pytest file) | exact |
| `backend/tests/test_observability_middleware.py` | test (TestClient + monkeypatch) | request-response | `backend/tests/test_feed_segments.py` (TestClient + monkeypatch + lifespan-skip) | exact |
| `backend/tests/test_observability_metrics.py` | test (TestClient + token auth) | request-response | `backend/tests/test_feed_segments.py` (TestClient pattern) | role-match |
| `backend/tests/test_observability_sentry.py` | test (pure unit, dict scrubber) | transform | `backend/tests/test_events_sse.py` (pure-unit pytest) | role-match |

---

## Pattern Assignments

### `backend/observability/__init__.py` (bootstrap, startup-time)

**Analog:** `backend/app.py:39-55` (`_pre_warm_sdk`) for env-gated init posture; `backend/config.py:1-5` for module-import side effects.

**Env-gated init pattern** (`backend/app.py:39-48`):
```python
async def _pre_warm_sdk() -> None:
    """Pre-warm Claude Agent SDK connection. Parallel with Marengo pre-warm.
    Skipped when ANTHROPIC_API_KEY not set (log + degrade gracefully).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning(
            "ANTHROPIC_API_KEY not set — compile pipeline will be unavailable. "
            "Set the key to enable."
        )
        return
```

**Apply to Sentry init:** Mirror this exact shape — empty `SENTRY_DSN` → log INFO ("sentry disabled (SENTRY_DSN unset)") and `return` without calling `sentry_sdk.init()`. This keeps OFFLINE_DEMO=true firewalled (D-16).

**Module-import side-effect pattern** (`backend/config.py:1-5`):
```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
```

**Apply:** `backend/observability/__init__.py` runs `configure_logging()` and `init_sentry()` at module-import time (top-level statements), NOT inside `lifespan`. This matches `config.py`'s "side effects fire on first import" idiom and ensures pre-warm log lines are JSON (Pitfall 6 fix).

---

### `backend/observability/logging_config.py` (config helper)

**Analog:** `backend/app.py:19` — the line being replaced.

**Current (to be replaced):**
```python
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
```

**Replacement contract:**
- Single function `configure_logging() -> None`
- Reads `config.LOG_FORMAT` exactly once (D-05)
- Uses `logging.config.dictConfig` with `disable_existing_loggers: False` (preserves the 12 existing `log = logging.getLogger(__name__)` references — `app.py:20`, `events.py:5`, `db.py:13`, `pipeline/run.py:9`, `pipeline/embed.py:29`, `pipeline/cluster.py:38`, `pipeline/compile.py:40`, `pipeline/compile_tools.py:17`, `pipeline/caption_pipeline.py:32`, `pipeline/keyframes.py:22`, `pipeline/frames.py:15`, `pipeline/stitch.py:27`)
- Idempotent: safe to call twice, but called exactly once at module-import of `backend/observability/__init__.py`
- Full snippet to copy verbatim: see `08-RESEARCH.md` §1 (lines 332-400+) — the dictConfig keystone snippet

---

### `backend/observability/sentry.py` (bootstrap, gated)

**Analog:** `backend/app.py:39-55` (`_pre_warm_sdk`) — env-gated optional SDK init.

**Pattern to mirror** (env-gated init + INFO log on skip + try/except non-fatal):
```python
# from app.py:39-55
async def _pre_warm_sdk() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set — compile pipeline will be unavailable. ...")
        return
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
        async for _ in query(prompt="ok", options=ClaudeAgentOptions(model="sonnet", max_turns=1)):
            break
        log.info("Claude SDK pre-warm complete")
    except Exception as exc:
        log.warning("Claude SDK pre-warm failed (non-fatal): %s", exc)
```

**Apply to `init_sentry()`** (sync, not async; runs at module import, not inside lifespan):
- Read `config.SENTRY_DSN`
- If empty → `log.info("sentry disabled (SENTRY_DSN unset)")` and return (D-16)
- Else `sentry_sdk.init(dsn=SENTRY_DSN, sample_rate=1.0, traces_sample_rate=0.0, send_default_pii=False, max_request_body_size="never", before_send=before_send_scrub, environment=config.SENTRY_ENVIRONMENT or None, integrations=[FastApiIntegration()])` per D-13
- `before_send_scrub` imported from `observability/anonymity.py` (D-14)
- No try/except needed at init — Sentry's own init is robust; failure should surface

---

### `backend/observability/metrics.py` (utility — module globals + factory)

**Analog:** NO direct analog. Module-level globals reused across requests is a new pattern in this codebase.

**Closest existing in-tree precedent:** `backend/pipeline/cluster.py:CLUSTERS` (module-level dict) — module-level mutable state that survives across requests. Confirms the codebase tolerates module-level state under `--workers 1`.

**Patterns to copy from RESEARCH.md §Pattern 4 (lines 242-247):**
- `REQUEST_COUNT = Counter(...)`, `REQUEST_DURATION = Histogram(...)`, `STAGE_DURATION = Histogram(...)` defined ONCE at module top
- Label keys per D-17: `route`, `method`, `status_class` for request metrics; `stage` for pipeline metrics
- `metrics_middleware` is pure ASGI (NOT BaseHTTPMiddleware — same landmine as Pitfall 1)
- `metrics_endpoint(token: str)` returns a route handler that returns `Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)`

**Token-auth pattern for `/metrics` route — verbatim from `/admin/reset` (`backend/app.py:347-368`):**
```python
@app.post("/admin/reset", include_in_schema=False)
async def admin_reset(
    mode: str = Query("all", pattern="^(all|last|since)$"),
    count: int | None = Query(None, ge=1, le=10000),
    seconds: float | None = Query(None, gt=0),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    expected = config.ADMIN_TOKEN
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="invalid admin token")
```

**Apply to `/metrics` route in `backend/app.py`** (D-09, D-10) — identical scheme:
- Header alias: `X-Admin-Token` (NOT `Authorization: Bearer` — match the existing `/admin/reset` exactly per D-10)
- 503 if `config.ADMIN_TOKEN` empty
- 401 if missing or mismatched
- `include_in_schema=False` to keep it out of the public OpenAPI spec (admin-only convention)

---

### `backend/observability/anonymity.py` (pure-function helper)

**Analog:** `backend/app.py:120-126` (`_haversine_m`) — single-purpose pure function with no state.

**Reference excerpt** (`backend/app.py:120-126`):
```python
def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

**Apply:**
- `def session_hash(uuid: str) -> str` — `hashlib.sha256(uuid.encode("utf-8")).hexdigest()` per D-06/D-08. Pure, no state, constant across time.
- `def before_send_scrub(event: dict, hint: dict) -> dict | None` — list-driven recursive walker (D-14). REDACT_KEYS = `{"session_uuid", "gps_lat", "gps_lng", "blob_url"}` (extensible — Phase 11/12 will append). Implementation guidance from RESEARCH.md Pitfall 8 (lines 324-328): iterate `list(d.items())` to avoid mutation-during-iteration; rebuild dicts/lists rather than `.pop()` in place.

---

### `backend/observability/middleware.py` (pure ASGI middleware)

**Analog (registration only):** `backend/app.py:74-80` (`CORSMiddleware` registration).

**Existing middleware registration** (`backend/app.py:74-80`):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Critical — implementation has NO in-tree analog.** RESEARCH.md Pitfall 1 (lines 278-283) is non-negotiable: `BaseHTTPMiddleware` BREAKS PRIV-02 silently because contextvars bound in `dispatch()` don't propagate to the route handler. Use pure ASGI (class with `__init__(self, app)` + `async def __call__(self, scope, receive, send)`).

**Apply two pure-ASGI classes:**
1. `XFFStrip` — mutates `scope["headers"]` to drop `x-forwarded-for`, `x-real-ip`, `forwarded`, `true-client-ip` (PRIV-01)
2. `RequestIDAndContextvarsBind` — generates UUID4 (D-11; do NOT trust upstream `X-Request-ID`); reads `X-Session-Id` if present, computes `session_hash` via `anonymity.session_hash()`; `clear_contextvars()` → `bind_contextvars(...)` → `await app(scope, receive, send)` → `clear_contextvars()` in `finally:` (RESEARCH.md Pattern 3)

**Registration order in `backend/app.py` (D-12) — outermost first, but FastAPI applies middleware in reverse-add-order (last added = outermost):**

```python
# Order in code (top-to-bottom = innermost-to-outermost after FastAPI reverses):
app.add_middleware(CORSMiddleware, ...)               # innermost (existing)
app.add_middleware(RequestIDAndContextvarsBind)       # middle (NEW)
app.add_middleware(XFFStrip)                          # outermost (NEW) — runs first
```

Effective execution order: `XFFStrip → RequestIDAndContextvarsBind → CORSMiddleware → routes`. XFF stripped before any code can log it.

---

### `backend/app.py` (modify)

**Analog:** self.

**Required modifications:**

1. **First import** — replace lines 1-19 prologue. `from .observability import configure_logging, init_sentry; configure_logging(); init_sentry()` MUST execute before `from . import config, db, events` (Pitfall 6, RESEARCH.md lines 312-316).

2. **Delete `logging.basicConfig(...)` at line 19** — replaced by `configure_logging()`.

3. **Keep `log = logging.getLogger(__name__)` at line 20** — the bridge approach (D-01) means existing call sites work unchanged.

4. **Insert middleware registrations** between `app = FastAPI(...)` (line 72) and the existing `CORSMiddleware` block (lines 74-80) — but registered AFTER `CORSMiddleware` in code order so they wrap it (FastAPI reverses order). Concrete order in `app.py`:
   ```python
   app.add_middleware(CORSMiddleware, ...)        # existing — keep at top
   app.add_middleware(RequestIDAndContextvarsBind)
   app.add_middleware(XFFStrip)
   app.add_middleware(metrics_middleware)         # if metrics_middleware is class-based; else register separately
   ```

5. **Add `/metrics` route** — copy the `/admin/reset` auth pattern verbatim (see metrics.py section above for the excerpt). Place after `/admin/reset` definition (after line 408).

---

### `backend/config.py` (modify)

**Analog:** self — extend the existing pattern.

**Existing env-var lines to mirror:**

```python
# config.py:11
TWELVELABS_API_KEY: str = os.environ.get("TWELVELABS_API_KEY", "").strip()

# config.py:17
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# config.py:35
ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", "").strip()
```

**Apply — append three lines below ADMIN_TOKEN:**

```python
# Phase 8: Observability
LOG_FORMAT: str = os.environ.get("LOG_FORMAT", "json").strip()
SENTRY_DSN: str = os.environ.get("SENTRY_DSN", "").strip()
SENTRY_ENVIRONMENT: str = os.environ.get("SENTRY_ENVIRONMENT", "").strip()
```

Default-empty + `.strip()` matches the `ADMIN_TOKEN` and `TWELVELABS_API_KEY` convention exactly.

---

### `backend/requirements.txt` (modify)

**Analog:** self — append pinned versions matching v1.0 pin discipline (D-15).

**Existing pinned-version pattern** (`backend/requirements.txt:1-9`):
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.18
pydantic==2.10.3
python-dotenv==1.0.1
aiosqlite==0.20.0
twelvelabs==1.2.3
```

**Append** (versions verified in RESEARCH.md §Standard Stack lines 102-128):
```
structlog==25.5.0
sentry-sdk[fastapi]==2.53.0
prometheus-client==0.25.0
```

---

### `backend/.env.example` (modify)

**Existing pattern** (verbatim):
```
# Local dev defaults. Copy to backend/.env before running. Never commit .env.
FRONTEND_URL=http://localhost:5173
DATA_DIR=./data

# Phase 2: Marengo embeddings
TWELVELABS_API_KEY=your_key_here
PRE_WARM_CLIP_PATH=seed/prewarm.mp4

# Phase 3+
# CLUSTER_THRESHOLD=0.55
# ANTHROPIC_API_KEY=
```

**Append (commented vars use `#` prefix to keep them opt-in, matching the existing Phase 3+ block):**
```
# Phase 8: Observability
# LOG_FORMAT=console        # default: json. set to console for human-readable local dev
# SENTRY_DSN=               # empty = Sentry disabled (OFFLINE_DEMO-safe)
# SENTRY_ENVIRONMENT=       # optional, e.g. "production" / "staging"
# ADMIN_TOKEN already documented above; reused by /metrics endpoint
```

---

### `backend/tests/test_observability_anonymity.py` (NEW — pure unit tests)

**Analog:** `backend/tests/test_events_sse.py` (smallest, purest pytest file in the suite).

**Reference excerpt** (`backend/tests/test_events_sse.py:1-26`):
```python
"""
Tests for backend/events.py — subscribe/unsubscribe/broadcast lifecycle.
"""
import asyncio

import pytest

from backend import events


@pytest.fixture(autouse=True)
def clear_subscribers():
    """Isolate tests by clearing _subscribers before each test."""
    events._subscribers.clear()
    yield
    events._subscribers.clear()


@pytest.mark.asyncio
async def test_subscribe_returns_queue_and_adds_to_subscribers():
    """subscribe() returns a Queue and adds it to _subscribers."""
    assert len(events._subscribers) == 0
    q = await events.subscribe()
```

**Apply — synchronous tests (no `@pytest.mark.asyncio` needed for pure functions):**
- `test_session_hash_is_sha256_hex` — assert output is 64-char hex
- `test_session_hash_is_constant` — same input → same output across calls (D-06)
- `test_session_hash_distinct_inputs_diverge`
- `test_before_send_scrub_redacts_top_level_keys` — `{"session_uuid": "abc"}` → key removed/redacted
- `test_before_send_scrub_redacts_nested_keys` — `{"request": {"data": {"gps_lat": 34.1}}}` → recursively cleaned
- `test_before_send_scrub_handles_lists` — `{"breadcrumbs": [{"data": {"blob_url": "..."}}]}`
- `test_before_send_scrub_no_mutation_during_iteration` — Pitfall 8 regression

---

### `backend/tests/test_observability_middleware.py` (NEW — TestClient + monkeypatch)

**Analog:** `backend/tests/test_feed_segments.py` — established pattern for `TestClient` with mocked lifespan.

**Reference excerpt** (`backend/tests/test_feed_segments.py:65-86`):
```python
# Patch lifespan to skip real startup side-effects
with patch("backend.app.db.init", new_callable=AsyncMock), \
     patch("backend.app.db.fetch_recent_segments",
           new_callable=AsyncMock,
           return_value=await db.fetch_recent_segments(limit=50)), \
     patch("backend.pipeline.cluster.rebuild_cache", new_callable=AsyncMock), \
     patch("backend.app._pre_warm_marengo", new_callable=AsyncMock), \
     patch("backend.app._pre_warm_sdk", new_callable=AsyncMock):

    from backend.app import app
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/feed")
```

**Apply — middleware tests:**
- `test_xff_stripped_before_route_handler` — set `X-Forwarded-For: 1.2.3.4` on request; route echoes `request.headers` → assert XFF absent (PRIV-01)
- `test_request_id_bound_in_context` — log a captured message inside a test route; assert JSON contains `request_id` UUID (PRIV-02 + D-11)
- `test_session_hash_bound_when_x_session_id_header_present` — set `X-Session-Id`; log inside route; assert `session_hash` present and is sha256 of header value
- `test_session_uuid_never_appears_in_logs` — set `X-Session-Id: known-uuid`; assert raw value NEVER in captured log output (PRIV-02 anonymity invariant)
- `test_contextvars_cleared_after_request` — make 2 requests; assert no leakage between them

Use `monkeypatch.setattr(config, "LOG_FORMAT", "json")` and `caplog`/captured-stream to inspect emitted JSON.

---

### `backend/tests/test_observability_metrics.py` (NEW — TestClient + token auth)

**Analog:** `backend/tests/test_feed_segments.py` (TestClient pattern) + `backend/app.py:347-368` (auth pattern under test).

**Apply:**
- `test_metrics_returns_503_when_admin_token_unset` — `monkeypatch.setattr(config, "ADMIN_TOKEN", "")`; GET `/metrics` → 503
- `test_metrics_returns_401_without_token` — set ADMIN_TOKEN; GET `/metrics` (no header) → 401
- `test_metrics_returns_401_with_wrong_token` — wrong `X-Admin-Token` → 401
- `test_metrics_returns_prometheus_text_format` — correct `X-Admin-Token` → 200, `Content-Type` starts with `text/plain; version=0.0.4`
- `test_metrics_labels_use_route_template_not_raw_path` — POST a few requests with IDs in path; scrape `/metrics`; assert `route="/clips/{clip_id}"` template form, NOT raw IDs (D-17 + Pitfall 4)
- `test_metrics_no_forbidden_labels` — assert none of `clip_id`, `session_uuid`, `session_hash` appear as label values (D-17)

---

### `backend/tests/test_observability_sentry.py` (NEW — pure unit, dict scrubber)

**Analog:** `backend/tests/test_events_sse.py` (pure unit, no I/O).

**Apply — direct unit tests of `before_send_scrub`** (no Sentry SDK round-trip needed; the scrubber is a pure function):
- `test_scrub_redacts_session_uuid_top_level`
- `test_scrub_redacts_gps_lat_nested_in_extra`
- `test_scrub_redacts_blob_url_in_breadcrumbs`
- `test_scrub_returns_event_unchanged_when_no_redactable_keys`
- `test_scrub_handles_none_values`
- `test_scrub_idempotent` — running twice gives the same result

Each test passes a hand-built `event` dict mimicking Sentry's nested shape (RESEARCH.md "Don't Hand-Roll" row 3 for shape examples) → calls `before_send_scrub(event, {})` → asserts shape.

---

## Shared Patterns

### Pattern A: Env-Gated Optional SDK Init (OFFLINE_DEMO-safe)

**Source:** `backend/app.py:39-48` (`_pre_warm_sdk`)
**Apply to:** `observability/sentry.py:init_sentry()`

```python
# from app.py:39-48
if not os.environ.get("ANTHROPIC_API_KEY"):
    log.warning(
        "ANTHROPIC_API_KEY not set — compile pipeline will be unavailable. "
        "Set the key to enable."
    )
    return
```

**Why:** Three project invariants depend on this — OFFLINE_DEMO end-to-end (CLAUDE.md), no outbound calls when DSN empty (D-16), graceful degrade (CLAUDE.md). Same exact shape: env-var check → log → early return.

---

### Pattern B: Empty-Token-Disables-Endpoint (503)

**Source:** `backend/app.py:347-368` (`/admin/reset`)
**Apply to:** `/metrics` route (D-09)

```python
# from app.py:364-368 — VERBATIM PATTERN
expected = config.ADMIN_TOKEN
if not expected:
    raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
if not x_admin_token or x_admin_token != expected:
    raise HTTPException(status_code=401, detail="invalid admin token")
```

**Why:** D-09/D-10 explicitly state `/metrics` reuses the same env var, same status codes, same header alias. No new auth scheme.

---

### Pattern C: Pinned-Version Discipline

**Source:** `backend/requirements.txt:1-9`
**Apply to:** all 3 new deps (D-15)

All v1.0 deps use `==` for prod libs (`fastapi==0.115.6`, `pydantic==2.10.3`). Match exactly: `structlog==25.5.0`, `sentry-sdk[fastapi]==2.53.0`, `prometheus-client==0.25.0`.

---

### Pattern D: Default-Empty + .strip() Env Vars

**Source:** `backend/config.py:11,17,35`
**Apply to:** `LOG_FORMAT`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`

```python
# config.py:11
TWELVELABS_API_KEY: str = os.environ.get("TWELVELABS_API_KEY", "").strip()
# config.py:35
ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", "").strip()
```

**Why:** Empty string is the universal "feature disabled" signal in this codebase — Sentry init checks `if config.SENTRY_DSN:`, just like admin endpoints check `if not expected:`.

---

### Pattern E: TestClient + Lifespan Mock

**Source:** `backend/tests/test_feed_segments.py:69-78`
**Apply to:** `test_observability_middleware.py`, `test_observability_metrics.py`

```python
with patch("backend.app.db.init", new_callable=AsyncMock), \
     patch("backend.pipeline.cluster.rebuild_cache", new_callable=AsyncMock), \
     patch("backend.app._pre_warm_marengo", new_callable=AsyncMock), \
     patch("backend.app._pre_warm_sdk", new_callable=AsyncMock):

    from backend.app import app
    client = TestClient(app, raise_server_exceptions=True)
```

**Why:** Standard recipe across `test_feed_segments.py`, `test_pipeline_integration.py` etc. for booting the FastAPI app under test without real DB/SDK warmup.

---

### Pattern F: tmp_db Fixture with monkeypatch

**Source:** `backend/tests/test_feed_segments.py:22-31` and `test_cluster.py:30-39`
**Apply to:** any new test that touches DB or DATA_DIR

```python
@pytest_asyncio.fixture
async def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    new_db_path = tmp_path / "newz.db"
    monkeypatch.setattr(db, "DB_PATH", new_db_path)
    monkeypatch.setattr(db, "CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    await db.init()
    return tmp_path
```

**Why:** Phase 8 doesn't touch DB directly, but `/metrics` route tests boot the app, which lazily touches DB. Use this fixture if any flake surfaces.

---

## No Analog Found

| File | Role | Reason | Source for Pattern |
|------|------|--------|---------------------|
| `backend/observability/middleware.py` (pure ASGI implementation, not registration) | middleware | All existing middleware in tree is `CORSMiddleware` from Starlette — no in-tree pure-ASGI class implementation | RESEARCH.md §Code Examples §3, §4 (lines 226-232 + Pitfall 1 lines 278-283) — non-negotiable: must be pure ASGI, not BaseHTTPMiddleware |
| `backend/observability/metrics.py` (Counter/Histogram module globals + middleware + endpoint factory) | utility | First Prometheus integration in codebase | RESEARCH.md §Pattern 4 (lines 242-247) + §"Don't Hand-Roll" row 5 (line 271) |

For both files, the planner MUST reference `08-RESEARCH.md` Code Examples sections directly — the codebase has no precedent.

---

## Critical Sequencing Constraints (carry into PLAN.md)

1. **Import order in `backend/app.py`** — `from .observability import configure_logging, init_sentry; configure_logging(); init_sentry()` MUST be the FIRST executable statement, before `from . import config, db, events` (RESEARCH.md Pitfall 6, lines 312-316). Otherwise pre-warm/DB-init log lines emit as plain text.

2. **Middleware registration order** — In `app.py`, register in this code order (FastAPI reverses for execution): `CORSMiddleware` first (existing line 74), then `RequestIDAndContextvarsBind`, then `XFFStrip` last. Effective request flow: `XFFStrip → RequestID → CORS → routes` (D-12).

3. **Pure ASGI, NOT BaseHTTPMiddleware** — `XFFStrip`, `RequestIDAndContextvarsBind`, `metrics_middleware` all use `__init__(self, app) + async def __call__(self, scope, receive, send)`. Tests must verify contextvars survive into route handlers (Pitfall 1).

4. **Module-level metric globals only** — `REQUEST_COUNT`, `REQUEST_DURATION`, `STAGE_DURATION` defined once at module top of `metrics.py`. Defining inside a function → `ValueError: Duplicated timeseries` on the second request (Pitfall 3).

5. **Route template, not raw URL** — Prometheus `route` label reads `request.scope.get("route").path` with `"<unmatched>"` fallback (Pitfall 4 + D-17).

---

## Metadata

**Analog search scope:** `/Users/liamshalom/Hacktech/backend/` (app.py, config.py, events.py, db.py, pipeline/, tests/)
**Files scanned:** 13 source files + 17 test files
**Logger acquisition sites confirmed:** 12 modules (verified via `grep -n "logging.getLogger"`)
**Pattern extraction date:** 2026-04-28
