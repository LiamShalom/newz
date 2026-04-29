<!-- generated-by: gsd-doc-writer -->

# Testing

Newz is a hackathon MVP — tests are deliberately scoped to the load-bearing pipeline (embed → cluster → compile → SSE) and to iOS Safari capture quirks. Demo correctness is verified by manual smoke tests, not browser E2E.

## Test stack

| App | Framework | Config | Environment |
| --- | --- | --- | --- |
| Backend | `pytest>=8.0.0` + `pytest-asyncio>=0.23.0` | none (defaults) | Python 3.11 venv |
| Frontend | `vitest@^2.1.0` + `@vitest/ui` | `frontend/vitest.config.ts` | jsdom |

Backend test deps live in `backend/requirements-dev.txt` (NOT in `requirements.txt` — production install does not pull them). Frontend test deps are devDependencies in `frontend/package.json`.

## Running tests

**Backend** (from repo root, after `make install`):

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Run a single file or test:

```bash
.venv/bin/pytest tests/test_cluster.py
.venv/bin/pytest tests/test_cluster.py::test_haversine_zero_distance
```

**Frontend** (from `frontend/`):

```bash
pnpm test          # one-shot run (vitest run)
pnpm test:watch    # watch mode (vitest)
```

Both apps' test commands are also wired into the project's CI-friendly defaults — `pnpm test` exits non-zero on failure.

## Test structure

**Backend** — `backend/tests/*.py`, one file per module under test:

| File | Covers |
| --- | --- |
| `test_cluster.py` | `haversine_m`, `score_against`, `update_centroid`, `cluster_worker` create/join paths |
| `test_pipeline_integration.py` | `run_pipeline` chains `embed_worker → cluster_worker`; `lifespan` rebuilds `CLUSTERS` cache from SQLite |
| `test_compile.py` | Phase 4 multi-agent compile happy path |
| `test_compile_timeout.py` | 30s hard cap → `_save_fallback_segment` + `segment_published` broadcast |
| `test_segments_db.py` | `insert_segment`, `set_compile_in_flight` (CAS), `fetch_cluster_clips` ordering |
| `test_db_clusters.py` | Cluster persistence + rebuild |
| `test_feed_segments.py` | `/feed` endpoint segment serialization |
| `test_events_sse.py` | `events.subscribe / unsubscribe / broadcast` queue lifecycle |
| `test_debug_clusters.py` | Debug overlay endpoints (Phase 3 score breakdown) |

Fixtures use `tmp_path` + `monkeypatch` to isolate the SQLite `DB_PATH` and `CLIPS_DIR` per test (see `test_pipeline_integration.py::tmp_db`). The `clear_clusters` autouse fixture resets in-memory `CLUSTERS` between tests.

**Frontend** — colocated `*.test.{ts,tsx}` next to the source:

| File | Covers |
| --- | --- |
| `src/components/RecordButton.test.tsx` | RecordButton render states (idle / recording / canStop), tap handler |
| `src/lib/mimeLadder.test.ts` | `MIME_CANDIDATES` order + `pickMimeType` Safari preference path |
| `src/lib/getPositionWithTimeout.test.ts` | Geolocation timeout + error fallback paths |

The MIME-ladder tests are the unit-test mirror of Pitfall #3 (iOS Safari MediaRecorder) — they pin the candidate list ordering so a refactor cannot silently break the Safari path.

## Mocking the embed call

Backend integration tests stub `backend.pipeline.embed._call_marengo` directly via `monkeypatch.setattr` so no Twelve Labs network call happens during `pytest`. See `_stub_call_marengo` in `backend/tests/test_pipeline_integration.py` for the deterministic-vector helper.

## Manual smoke test

The iPhone Safari hardware gate ([`docs/IPHONE-GATE.md`](IPHONE-GATE.md)) is the load-bearing manual check — 13-row matrix covering record, retake, post, denied permissions, 30s auto-stop, and persistence across refresh. **MUST be PASS on a real iPhone (not DevTools emulator) before any embedding work.**

The calibration notebook (`backend/notebooks/calibration.ipynb`) is a manual-execution deliverable — it tunes the composite-score threshold against a staged dataset. Not part of `pytest`, but failure to re-run it after clustering changes will silently regress demo quality.

## What's NOT tested (by design)

This is a 60-second 4-clip hackathon demo, not a product. The following are intentionally absent:

- **Load tests** — single-process FastAPI, expected concurrent users ≈ 4 judges.
- **Full E2E browser tests** — no Playwright/Cypress; iPhone Safari gate (`IPHONE-GATE.md`) covers what matters.
- **Coverage thresholds** — no `pytest-cov` config, no `vitest --coverage` gate. Don't ship a coverage badge.
- **Cross-browser matrix** — iOS Safari is the only target; other browsers are not regression-tested.
- **CI integration** — no `.github/workflows/` test job. Tests run locally before commits.
- **Twelve Labs Marengo live-call tests** — `_call_marengo` is stubbed in tests; live calls are reserved for runtime.
- **Claude Agent SDK live-call tests** — `test_compile_timeout.py` mocks `query` and `_run_agents`; full subagent runs are a manual gate.

If a hackathon-scope change requires one of the above, it's likely a sign the change is out of scope (see `.planning/PROJECT.md` "Out of Scope").
