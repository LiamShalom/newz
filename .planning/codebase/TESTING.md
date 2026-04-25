# Testing Patterns

**Analysis Date:** 2026-04-24
**Status:** Pre-implementation — testing patterns derived from CLAUDE.md, research docs, and planned stack. No test files exist yet. These are prescriptive standards to follow when writing tests.

---

## Test Framework

**Backend runner:**
- `pytest` with `pytest-asyncio` for async coroutine tests
- Config: `backend/pytest.ini` or `pyproject.toml [tool.pytest.ini_options]`
- No specific version pinned yet; use latest stable compatible with Python 3.11

**Frontend runner:**
- `vitest` (bundled with the Vite `react-ts` template)
- Config: `frontend/vitest.config.ts` (shares `vite.config.ts` plugins)

**Assertion library:**
- Python: `pytest` built-in `assert` — no `unittest` assertions
- TypeScript: `vitest` built-in `expect` (Chai-compatible API)

**Run commands:**
```bash
# Backend
cd backend
pytest                          # run all tests
pytest -v                       # verbose
pytest tests/pipeline/          # pipeline tests only
pytest -k "test_cluster"        # filter by name

# Frontend
cd frontend
pnpm test                       # watch mode
pnpm test --run                 # single run (CI mode)
pnpm coverage                   # coverage report
```

---

## Test File Organization

**Location:**
- Backend: `backend/tests/` directory, mirroring the module structure
- Frontend: co-located with source files OR in `frontend/src/__tests__/`
- Calibration notebook: `backend/notebooks/calibration.ipynb` — checked into repo, NOT a pytest file

**Naming:**
- Python: `test_{module_name}.py` — e.g., `test_cluster.py`, `test_embed.py`, `test_compile.py`
- TypeScript: `{ComponentName}.test.tsx` or `{module}.test.ts`

**Structure:**
```
backend/
├── tests/
│   ├── conftest.py              # shared fixtures (db, mock embeddings)
│   ├── test_app.py              # HTTP route tests (ingest, feed, events)
│   ├── test_cluster.py          # clustering algorithm + composite score
│   ├── test_embed.py            # embed wrapper (mock Marengo)
│   ├── test_compile.py          # compile pipeline (mock Agent SDK)
│   └── test_db.py               # SQLite schema + helpers
├── notebooks/
│   └── calibration.ipynb        # empirical threshold calibration — REQUIRED Phase 3 deliverable
frontend/
└── src/
    ├── __tests__/
    │   ├── Feed.test.tsx
    │   ├── Recorder.test.tsx
    │   └── sse.test.ts
    └── ...
```

---

## Test Structure

**Python suite organization:**
```python
# backend/tests/test_cluster.py

import pytest
import numpy as np
from backend.pipeline.cluster import composite, visual_score, gps_score, time_score

class TestCompositeScore:
    def test_same_event_clips_score_above_threshold(self):
        # same-event embeddings should produce composite >= 0.55
        ...

    def test_adversarial_same_location_different_event_below_threshold(self):
        # two unrelated clips at same GPS + time should NOT cluster
        # REQUIRED: CLU-08 adversarial test
        ...

    def test_gps_weight_collapses_to_zero_when_unavailable(self):
        # CLU-06: GPS missing → only Marengo + time contribute
        ...
```

**TypeScript suite organization:**
```typescript
// frontend/src/__tests__/Recorder.test.tsx

import { describe, it, expect, vi } from 'vitest'

describe('Recorder', () => {
  describe('MIME type ladder', () => {
    it('falls back to no mimeType when nothing is supported', () => {
      // iOS Safari safety test — critical for demo
    })
    it('prefers mp4;avc1 on Safari', () => {
      ...
    })
  })
})
```

**Patterns:**
- `conftest.py` in `backend/tests/` provides shared fixtures — never duplicate fixture setup in test files
- `beforeEach`/`afterEach` in Vitest for DOM cleanup
- Group related assertions in one test — clustering tests assert visual, gps, time, and composite in one shot for readability

---

## Mocking

**Framework (Python):** `unittest.mock` (`MagicMock`, `AsyncMock`, `patch`) — no additional mock library needed

**Framework (TypeScript):** `vitest` built-in `vi.fn()`, `vi.mock()`, `vi.spyOn()`

**Critical mocks:**

**Marengo (Twelve Labs) — mock always in unit tests:**
```python
# backend/tests/conftest.py
import pytest
from unittest.mock import AsyncMock, patch
import numpy as np

@pytest.fixture
def mock_embed():
    """Returns deterministic 512-d vectors keyed by clip_id.
    Mirrors the USE_MOCK_EMBEDDINGS=true behavior from config.py."""
    def _fake_embed(clip_id: str) -> np.ndarray:
        rng = np.random.default_rng(seed=hash(clip_id) & 0xFFFF)
        vec = rng.standard_normal(512).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec
    return _fake_embed
```

**Claude Agent SDK — mock always in unit tests:**
```python
@pytest.fixture
def mock_compile():
    """Returns a canned segment without invoking the Agent SDK."""
    with patch("backend.pipeline.compile.query") as mock_query:
        async def fake_query(*args, **kwargs):
            yield type("Msg", (), {"result": "segment saved"})()
        mock_query.side_effect = fake_query
        yield mock_query
```

**SQLite — use in-memory DB for all tests:**
```python
@pytest.fixture
async def db():
    """Ephemeral in-memory SQLite. Rebuilt for every test function."""
    import aiosqlite
    async with aiosqlite.connect(":memory:") as conn:
        await setup_schema(conn)  # from backend/db.py
        yield conn
```

**Browser APIs (TypeScript):**
```typescript
// vi.mock for MediaRecorder, navigator.geolocation, EventSource
vi.mock('navigator.geolocation', () => ({
  getCurrentPosition: vi.fn((success) =>
    success({ coords: { latitude: 34.1377, longitude: -118.1253 } })
  ),
}))
```

**What to mock:**
- All external API calls (Twelve Labs, Anthropic)
- SQLite in unit tests (use `:memory:`)
- `asyncio.create_task` when testing HTTP route handlers in isolation
- `navigator.geolocation`, `MediaRecorder`, `EventSource` in frontend unit tests

**What NOT to mock:**
- The clustering math in `cluster.py` — test it with real `numpy` operations
- Pydantic model validation — let it run; it catches contract bugs
- SQLite schema in integration tests — use a real on-disk test DB

---

## Fixtures and Factories

**Staged demo clips fixture (critical — Phase 3 deliverable):**
```python
# backend/tests/conftest.py

STAGED_CLIP_EMBEDDINGS = {
    "demo_angle_1": np.load("tests/fixtures/demo_angle_1.npy"),
    "demo_angle_2": np.load("tests/fixtures/demo_angle_2.npy"),
    "demo_angle_3": np.load("tests/fixtures/demo_angle_3.npy"),
    "adversarial_unrelated": np.load("tests/fixtures/adversarial_unrelated.npy"),
}
```

**Clip factory:**
```python
def make_clip(
    clip_id: str = "test-clip-001",
    lat: float = 34.1377,
    lng: float = -118.1253,
    ts: float = 1745500000.0,
    embedding_status: str = "done",
) -> dict:
    return {
        "id": clip_id,
        "lat": lat,
        "lng": lng,
        "ts": ts,
        "embedding_status": embedding_status,
    }
```

**Cluster factory:**
```python
def make_cluster(n_clips: int = 2, centroid_vec=None) -> dict:
    if centroid_vec is None:
        centroid_vec = np.zeros(512, dtype=np.float32)
    return {
        "id": f"cluster-{n_clips}",
        "centroid_vec": centroid_vec,
        "centroid_lat": 34.1377,
        "centroid_lng": -118.1253,
        "median_ts": 1745500000.0,
        "member_clip_ids": [f"clip-{i}" for i in range(n_clips)],
        "compile_in_flight": 0,
        "segment_id": None,
    }
```

**Location:**
- Fixture data (pre-computed embeddings): `backend/tests/fixtures/`
- Factory functions: `backend/tests/conftest.py`
- Calibration notebook (not pytest): `backend/notebooks/calibration.ipynb`

---

## Coverage

**Requirements:**
- No formal coverage threshold enforced for hackathon
- Pipeline modules (`embed.py`, `cluster.py`, `compile.py`) must have tests — these are the demo-critical paths
- Adversarial clustering test (CLU-08) is a hard gate before Phase 3 is considered done

**View coverage:**
```bash
cd backend
pytest --cov=backend --cov-report=term-missing
```

---

## Test Types

**Unit tests:**
- Scope: individual functions in `pipeline/` modules, Pydantic model validation, composite score math
- Do NOT touch the network or filesystem
- All external dependencies mocked
- Examples: `test_cluster.py::test_composite_score`, `test_embed.py::test_mock_embed_returns_512d`

**Integration tests:**
- Scope: full HTTP route → SQLite → pipeline trigger flow with in-memory DB
- Mock only external APIs (Marengo, Agent SDK); let SQLite and asyncio run real
- Examples: `test_app.py::test_post_clips_returns_202`, `test_app.py::test_feed_returns_published_segments`

**Calibration notebook (special — not pytest):**
- Scope: empirical validation of clustering thresholds against real staged demo clips
- Location: `backend/notebooks/calibration.ipynb`
- Required outputs: pairwise cosine similarity matrix heatmap, composite score distribution, threshold decision
- MUST be committed with outputs before Phase 3 is marked complete

**E2E tests:**
- Not used — hackathon scope
- Manual E2E gate: "iOS Safari on real iPhone records a clip, feed updates" is a required checkpoint (FND-03, Checkpoint 1)

---

## Common Patterns

**Async test pattern (Python):**
```python
import pytest

@pytest.mark.asyncio
async def test_assign_or_create_creates_new_cluster_when_no_match():
    from backend.pipeline.cluster import assign_or_create
    # arrange
    active_clusters = []
    fake_embedding = np.random.randn(512).astype(np.float32)
    fake_embedding /= np.linalg.norm(fake_embedding)
    # act
    cluster_id, breakdown = await assign_or_create(
        "clip-001", fake_embedding, (34.1377, -118.1253), 1745500000.0,
        active_clusters=active_clusters
    )
    # assert
    assert cluster_id is not None
    assert breakdown is None  # None when a new cluster is created
    assert len(active_clusters) == 1
```

**Adversarial clustering test (CLU-08 — required gate):**
```python
def test_adversarial_clips_do_not_cluster():
    """Two unrelated clips at the same GPS + timestamp must NOT cluster.
    Requirement CLU-08. This test gates Phase 3 completion."""
    from backend.pipeline.cluster import composite
    # Embeddings from different visual contexts — expect low cosine similarity
    e_event_a = STAGED_CLIP_EMBEDDINGS["demo_angle_1"]
    e_unrelated = STAGED_CLIP_EMBEDDINGS["adversarial_unrelated"]
    cluster = make_cluster(n_clips=1, centroid_vec=e_event_a)
    breakdown = composite(
        e_new=e_unrelated,
        gps_new=(34.1377, -118.1253),   # same location
        ts_new=1745500000.0,             # same time
        cluster=cluster,
    )
    assert breakdown.composite < 0.55, (
        f"Adversarial clip scored {breakdown.composite:.3f} — "
        "threshold may be too loose or GPS+time weights too high"
    )
```

**Error testing (Python):**
```python
@pytest.mark.asyncio
async def test_pipeline_broadcasts_error_on_embed_failure(mock_embed_raises):
    """Pipeline must broadcast pipeline_error event, never silently fail."""
    events_received = []
    # ... wire up mock event bus
    await run_pipeline("clip-fail")
    assert any(e["type"] == "pipeline_error" for e in events_received)
```

**Compile timeout test:**
```python
@pytest.mark.asyncio
async def test_compile_fallback_on_timeout():
    """30-second hard cap must produce a fallback segment, not raise."""
    with patch("backend.pipeline.compile.query", side_effect=asyncio.TimeoutError):
        segment = await compile.run("cluster-001")
    assert segment is not None
    assert "generic" in segment.caption.lower() or segment.caption != ""
```

**Frontend SSE hook test:**
```typescript
it('closes EventSource on unmount', () => {
  const closeSpy = vi.fn()
  vi.spyOn(window, 'EventSource').mockImplementation(() => ({
    onmessage: null,
    close: closeSpy,
  } as unknown as EventSource))

  const { unmount } = render(<Feed />)
  unmount()

  expect(closeSpy).toHaveBeenCalledOnce()
})
```

---

## Calibration Notebook (Phase 3 Gate)

The calibration notebook at `backend/notebooks/calibration.ipynb` is a **required deliverable**, not optional polish. It must:

1. Load the 3-4 staged demo clips' pre-computed embeddings
2. Compute a pairwise cosine similarity matrix and render as a heatmap
3. Compute composite scores for every clip pair under the proposed weights
4. Plot the composite score distribution and mark the `THRESHOLD = 0.55` line
5. Include one adversarial pair (same location + time, different event) and verify it falls below threshold
6. Conclude with a written "threshold decision" cell: "We set THRESHOLD=X because..."

This notebook is the empirical proof that the demo will cluster correctly. It cannot be skipped.

---

*Testing analysis: 2026-04-24*
