# Deferred Items — Phase 09

Items discovered during execution but out of scope per the plan that triggered them. Logged here for later triage.

## 09-04 (Wave 3)

### Pre-existing test isolation issues in backend/tests/

**Discovered:** During verification of Task 2 (`/debug/dbstate` guard).

**Symptom:** Several tests fail when the persistent `data/newz.db` file accumulates rows across runs:

- `backend/tests/test_db_clusters.py` — `test_upsert_then_get_all_clusters_roundtrip`, `test_upsert_idempotent_updates_existing_row`, `test_assign_clip_to_cluster_sets_column`, `test_get_all_clusters_empty_returns_empty_list`
- `backend/tests/test_debug_clusters.py` — `test_debug_clusters_empty_returns_envelope`
- `backend/tests/test_pipeline_integration.py` — `test_lifespan_rebuilds_cache_from_sqlite`, `test_solo_parent_cluster_does_not_trigger_compile`
- `backend/tests/test_segments_db.py` — `test_insert_segment_round_trip`, `test_insert_segment_conflict_updates_existing`

**Root cause:** `db_sqlite.DB_PATH` is bound at module import from `config.DATA_DIR / "newz.db"`. The test fixture `tmp_db` creates a tmp path but the production module reference still points to the persistent file when tests don't fully monkeypatch `db_sqlite.DB_PATH` everywhere it's read.

**Reproduction:** Reproduces on the v1.0 baseline (HEAD~1, before 09-04) — confirmed pre-existing, not caused by the dispatcher or `/debug/dbstate` guard.

**Verification of 09-04 scope:** Tests touched directly by 09-04 (dispatcher routing, `/debug/dbstate` 200/503) all pass — see the task verification logs.

**Recommended owner:** A future hygiene pass on test fixtures (likely Phase 10 or its own follow-up). Switching `DB_PATH` to a `contextvar`-bound override or `monkeypatch.setattr(db_sqlite, 'DB_PATH', ...)` in the fixture would resolve.
