# Phase 10 Deferred Items

Out-of-scope discoveries during execution.

## Pre-existing test fixture bug — test_db_clusters.py

The `tmp_db` fixture monkey-patches `db.DB_PATH` (the dispatcher re-export)
but `db_sqlite.upsert_cluster` / `get_all_clusters` / etc. resolve `DB_PATH`
from their own module (`db_sqlite.DB_PATH`), so the patch is a no-op. Tests
in `test_db_clusters.py` write to and read from the actual production DB at
`data/newz.db`, leaking state across runs. Symptoms:

- `test_upsert_then_get_all_clusters_roundtrip` and
  `test_upsert_idempotent_updates_existing_row` accumulate rows in
  `data/newz.db` and fail because `len(rows) > 1`.

Pre-existing in stashed (pre-Phase-10) state — confirmed by running stashed
tests against the same DB. NOT caused by Phase 10 changes.

Fix scope: rewrite the fixture to monkeypatch `db_sqlite.DB_PATH` directly,
or migrate to the Phase 9 `fresh_db` fixture pattern. Out of scope for
Phase 10.
