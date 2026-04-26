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

## Mocking + offline

Two env flags double as testing levers — both default to `false`, both are read in `backend/config.py`:

- **`USE_MOCK_EMBEDDINGS=true`** — `backend/pipeline/embed.py` returns deterministic random unit vectors instead of calling Twelve Labs Marengo. Used by:
  - `make backend` target (avoids burning API credits during local dev)
  - Backend integration tests (no network in test env)
- **`OFFLINE_DEMO=true`** — Serves cached embeddings + cached compile output from `backend/seed/`. No external API calls. The hackathon-WiFi-died fallback (Pitfall #6).

**Demo seed** — `backend/seed/seed_demo.py` uploads 3-4 staged clips from `backend/seed/demo/clip-*.mp4` to a running backend at hardcoded Caltech coords (`34.1377, -118.1253`). Run against a clean DB to reproduce the canonical demo flow:

```bash
python -m backend.seed.seed_demo --base-url http://localhost:8000
```

The seed script is what judges' live clips will displace — it exists so the demo is never empty.

## Manual smoke tests

Two manual gates carry weight that automated tests do not:

1. **iPhone Safari hardware gate** — see [`docs/IPHONE-GATE.md`](IPHONE-GATE.md). 13-row matrix covering record, retake, post, denied permissions, 30s auto-stop, and persistence across refresh. **MUST be PASS on a real iPhone (not DevTools emulator) before any embedding work.** Closes Pitfall #3.
2. **Demo replay** — Start backend with `OFFLINE_DEMO=true`, run `seed_demo.py`, and confirm the feed renders 3-4 clustered clips with a compiled segment caption within 30s. This is the Tier-5 fallback for the live demo.

The calibration notebook (`backend/notebooks/calibration.ipynb`) is a manual-execution Phase 3 deliverable — it tunes the composite-score threshold against a staged dataset. Not part of `pytest`, but failure to re-run it after clustering changes will silently regress demo quality.

## What's NOT tested (by design)

This is a 60-second 4-clip hackathon demo, not a product. The following are intentionally absent:

- **Load tests** — single-process FastAPI, expected concurrent users ≈ 4 judges.
- **Full E2E browser tests** — no Playwright/Cypress; iPhone Safari gate (`IPHONE-GATE.md`) covers what matters.
- **Coverage thresholds** — no `pytest-cov` config, no `vitest --coverage` gate. Don't ship a coverage badge.
- **Cross-browser matrix** — iOS Safari is the only target; other browsers are not regression-tested.
- **CI integration** — no `.github/workflows/` test job. Tests run locally before commits.
- **Twelve Labs Marengo live-call tests** — covered by `USE_MOCK_EMBEDDINGS`; live calls are reserved for the demo itself.
- **Claude Agent SDK live-call tests** — `test_compile_timeout.py` mocks `query` and `_run_agents`; full subagent runs are a manual gate.

If a hackathon-scope change requires one of the above, it's likely a sign the change is out of scope (see `.planning/PROJECT.md` "Out of Scope").
