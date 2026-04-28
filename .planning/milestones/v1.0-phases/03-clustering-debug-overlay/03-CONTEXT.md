# Phase 3: Clustering + Debug Overlay — Context

**Gathered:** 2026-04-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement composite-score clustering (Marengo cosine + GPS proximity + timestamp proximity) wired into run_pipeline. Staged demo clips commit to repo and seed via POST /clips. Calibration notebook in repo proves staged clips cluster correctly. Debug overlay deferred to later if time permits — backend /debug JSON endpoint is sufficient for calibration.

</domain>

<decisions>
## Implementation Decisions

### Staged demo clips
- **D-01:** 3-4 short MP4s committed to `backend/seed/demo/`. A seed script uploads them through `POST /clips` with hardcoded Caltech GPS coords so they flow through the identical pipeline as live clips.
- **D-02:** Both live capture and uploaded video are first-class. Staged clips test the same code path judges will see.

### Clustering algorithm
- **D-03:** Centroid strategy — new clip scores against the **average embedding** of all clips in the cluster. Centroid vector updated on every insert.
- **D-04:** Composite formula locked: `0.55 × Marengo cosine + 0.30 × GPS proximity + 0.15 × timestamp proximity` (CLU-02)
- **D-05:** GPS proximity normalized over 200m radius; timestamp proximity over 600s window (CLU-03, CLU-04)
- **D-06:** GPS weight collapses to 0 when lat/lng unavailable — formula becomes `0.55 × Marengo + 0.15 × timestamp` (CLU-06)
- **D-07:** Threshold 0.55 exposed as `CLUSTER_THRESHOLD` env var, already in config.py (CLU-05)
- **D-08:** In-memory cluster store (dict keyed by cluster_id), rebuilt from SQLite on startup (CLU-10)

### Debug overlay
- **D-09:** Deferred frontend panel. Phase 3 delivers a `GET /debug/clusters` JSON endpoint showing score breakdown per cluster. Frontend debug view added later if time permits.

### Calibration notebook
- **D-10:** Jupyter notebook at `backend/notebooks/calibration.ipynb`. Proves staged clips cluster together (CLU-07) and adversarial test passes (CLU-08).

### Claude's Discretion
- In-memory cluster data structure shape (dict of dataclass vs dict of dict)
- Exact centroid update math (running mean vs recompute from stored embeddings)
- Seed script CLI interface
- Notebook cell layout

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — CLU-01 through CLU-10, RTM-04 (all Phase 3 requirements)

### Architecture
- `.planning/research/ARCHITECTURE.md` — clustering composite score, hot path description
- `CLAUDE.md` — composite score weights, threshold, GPS fallback, stack constraints

### Existing code integration points
- `backend/pipeline/run.py` — cluster_worker wires in after embed_worker (Phase 3 TODOs already noted)
- `backend/db.py` — `clusters` table already in schema (centroid BLOB, member_count, updated_at)
- `backend/config.py` — `CLUSTER_THRESHOLD` already defined
- `backend/events.py` — SSE broadcast for cluster_assigned events

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/db.py`: `clusters` table already in schema with `centroid BLOB`, `centroid_lat`, `centroid_lng`, `median_ts`, `member_count`, `created_at`, `updated_at`
- `backend/db.py`: `clips.cluster_id` column already present
- `backend/config.py`: `CLUSTER_THRESHOLD = 0.55` already defined
- `backend/events.py`: `broadcast()` ready for cluster events
- `backend/pipeline/run.py`: `# Phase 3 wires in: cluster_id = await cluster_worker(clip_id, vec)` comment already in place
- `backend/pipeline/embed.py`: `embed_worker(clip_id)` returns 512-d numpy array — cluster_worker receives this

### Established Patterns
- Per-operation aiosqlite connections (open/close per call) — match this in cluster helpers
- Relative imports: `from .. import config, db, events` — all pipeline modules use this
- `asyncio.create_task` for fire-and-forget, never `await` from routes
- `run_in_executor` for any sync CPU work (numpy cosine is fast enough inline for <1000 vectors)

### Integration Points
- `backend/pipeline/run.py` → `cluster_worker(clip_id, vec)` after embed completes
- `backend/db.py` → add `get_all_clusters()`, `upsert_cluster()`, `assign_clip_to_cluster()` helpers
- `backend/app.py` → rebuild in-memory cluster store on lifespan startup (CLU-10)
- `GET /debug/clusters` → new route in app.py returning cluster state + score breakdown

</code_context>

<specifics>
## Specific Ideas

- Seed script should accept `--mock` flag to use deterministic embeddings (no API key needed for calibration dev)
- Calibration notebook must be runnable standalone — `pip install -r requirements.txt && jupyter nbconvert --to notebook --execute calibration.ipynb`

</specifics>

<deferred>
## Deferred Ideas

- Frontend debug panel (floating overlay or /debug React page) — add in Phase 5 demo hardening if time permits
- RTM-04 (live SSE updates to debug overlay) — partially covered by cluster_assigned SSE event; full live panel is deferred

</deferred>

---
*Phase: 03-clustering-debug-overlay*
*Context gathered: 2026-04-25*
