---
slug: video-upload-path-null-blob
status: resolved
trigger: "POST /clips fails on backend preview deployment with asyncpg.exceptions.NotNullViolationError on column clips.path"
created: 2026-04-28
updated: 2026-04-28
resolved_by: f7700b7 fix(10) relax clips.path NOT NULL for blob-mode INSERT; db4dd8d fix(10) download blob URL to tempfile in embed_worker
branch: liam/phase-10-blob-migration
phase: 10-vercel-blob-migration
---

# Debug Session: video-upload-path-null-blob

## Symptoms

DATA_START
**Expected behavior:** POST /clips returns 202 and persists the clip row with the Vercel Blob URL.

**Actual behavior:** Endpoint raises `asyncpg.exceptions.NotNullViolationError: null value in column "path" of relation "clips" violates not-null constraint`. The failing row's `path` is null while `blob_url` contains the Vercel Blob URL (`https://hlgbvhvavvgpwp13.private.blob.vercel-storage.com/uploads...`).

**Error site:** `backend/db_postgres.py:173` inside `insert_clip` — the INSERT statement provides `None` for `path` when storage backend returns a blob URL.

**Failing row (verbatim from Postgres DETAIL):**
`(8ab3065b291f4fa39862c720d4323e64, null, 47.66353039792532, -122.31053688084339, 1777443310.253, null, pending, null, null, 9858118b-a082-4023-93f2-cd75e2ac1cc8, 1777443315.823731, null, 0, null, https://hlgbvhvavvgpwp13.private.blob.vercel-storage.com/uploads..., f)`

**Timeline:** Started after Phase 10 (Vercel Blob migration) deploy to backend preview environment.

**Reproduction:** Any POST /clips video upload against the preview backend.

**Full traceback:**
```
File "/app/backend/db_postgres.py", line 173, in insert_clip
File "/usr/local/lib/python3.11/site-packages/asyncpg/pool.py", line 592, in execute
asyncpg.exceptions.NotNullViolationError: null value in column "path" of relation "clips" violates not-null constraint
```
DATA_END

## Initial Code Survey (orchestrator-side, pre-investigation)

- `backend/db_postgres.py:158-182` `insert_clip` writes `None` to `path` when `storage.save_clip_bytes` returns a URL (`is_blob_url = result.startswith("http")`).
- `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py:37` declares `path TEXT NOT NULL` in the `clips` CREATE TABLE.
- `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py:52` declares `blob_url TEXT` (nullable).
- Only one migration exists in `backend/migrations/versions/`. No follow-up migration drops the NOT NULL constraint on `path`.

## Current Focus

```yaml
hypothesis: "Phase 10 (Vercel Blob) shipped the application code path that writes path=NULL when blob storage is active, but did not ship the corresponding Alembic migration to drop the NOT NULL constraint on clips.path. Schema and code are out of sync on the preview deployment."
test: "1) Confirm only one migration file exists. 2) Confirm INSERT in insert_clip can pass NULL for path. 3) Confirm STORAGE_BACKEND env on preview is set to 'blob'. 4) Decide: drop NOT NULL on path, OR add a CHECK ((path IS NOT NULL) OR (blob_url IS NOT NULL)) so exactly one is required."
expecting: "A new Alembic migration that ALTERs clips.path to drop NOT NULL, plus a check constraint to enforce exclusive presence, is the correct fix."
next_action: "VALIDATED — root cause confirmed. Offer fix options to user."
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-04-28 (orchestrator) — schema file has `path TEXT NOT NULL` (line 37) and `blob_url TEXT` (line 52). Source: `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py`.
- timestamp: 2026-04-28 (orchestrator) — code at `backend/db_postgres.py:177` deliberately passes `None` for path when `is_blob_url` is true.
- timestamp: 2026-04-28 (orchestrator) — only one migration version file exists in `backend/migrations/versions/` (excluding `__init__.py`).
- timestamp: 2026-04-28 (debugger) — confirmed via `ls backend/migrations/versions/`: only `20260428_0001_initial_v1_1_schema.py`. No Phase 10 follow-up revision was ever authored.
- timestamp: 2026-04-28 (debugger) — Phase 10 plan `10-01-PLAN.md` `files_modified` list confirms the omission: it touches `backend/db_postgres.py`, `backend/storage/*`, `backend/app.py`, etc., but contains zero entries under `backend/migrations/`. The schema delta was never planned.
- timestamp: 2026-04-28 (debugger) — Phase 10 verification `10-VERIFICATION.md:200-210` ("Schema Discipline") explicitly notes only the original Phase 9 revision exists and treats this as compliance with anti-pattern #10 ("don't add downgrade body to drop blob_url"). The verifier missed that NO migration was needed for *adding* `blob_url` (Phase 9 baked it in) but one IS needed to relax `path NOT NULL` once the writer started passing NULL.
- timestamp: 2026-04-28 (debugger) — Phase 10 verification §6 reports `5 skipped (postgres without DATABASE_URL)`. The Postgres path was never exercised, so the schema/code mismatch could not have been caught by the unit suite. The HUMAN-UAT for SC-2 ("New clip POST lands in Blob uploads/") was deferred to merge time and is exactly what surfaced this bug now.
- timestamp: 2026-04-28 (debugger) — `backend/storage/blob.py:39` `save_clip_bytes` returns the Vercel Blob URL string (`obj["url"]` from the upload response). `db_postgres.py:170` checks `result.startswith("http")` → `is_blob_url=True` → INSERT receives `path=None, blob_url=<url>`. Behavior is intentional in code; only the schema is wrong.
- timestamp: 2026-04-28 (debugger) — Read-side `storage.get_playable_url(row)` (both `local.py:58-65` and `blob.py:58-65`) handles `path is None` correctly — it falls back to `blob_url`. So the read path is safe once the INSERT succeeds.
- timestamp: 2026-04-28 (debugger) — DOWNSTREAM HAZARD discovered (separate from the immediate crash):
    - `backend/pipeline/embed.py:126-128` reads `clip["path"]` and runs `Path(clip_path).exists()`. In blob mode `path is None` → `Path(None)` raises TypeError. This will fire on the next stage (`embed_worker`) the moment the INSERT is fixed.
    - `backend/pipeline/keyframes.py:30-52` (`_fetch_cluster_clips_with_duration`) opens an `aiosqlite` connection directly against `db.DB_PATH`. This file was not migrated by Phase 9 to the dispatcher. It was already broken in v1.1 Postgres mode independent of Phase 10 — but worth flagging.
    - `backend/db_postgres.py:505,527,536` builds `parent_path_map` from `p["path"]`. After fix, parents will have `path=None` in blob mode; `parent_path_map` becomes `{id: None}`. Downstream consumers in `compile.py` and `stitch.py` route through `_download_refs_to_tempdir` (`compile.py:42-67`) which checks `src_url.startswith("http")` — but only after `ref["path"]` is set to the URL. Currently `fetch_cluster_clips_with_compile_metadata` returns `"path": r["path"] or parent_path` which yields None when both are None. The compile pipeline will need adjustment to populate the `path` field with `blob_url` (or accept blob_url separately) so the existing http-prefix check fires.
- timestamp: 2026-04-28 (debugger) — Phase 9 D-15 ("hackathon-grade, no rollback support") is already established for the initial migration. New revision should follow the same convention: `downgrade()` raises NotImplementedError. New file should be `20260428_0002_relax_clips_path_not_null.py` (or similar slug) with `down_revision = "0001_initial_v1_1_schema"`.

## Eliminated

- Hypothesis: "STORAGE_BACKEND env not set on preview" — REJECTED. The blob URL in the failing row (`https://hlgbvhvavvgpwp13.private.blob.vercel-storage.com/uploads...`) confirms `save_clip_bytes` ran the blob path and successfully uploaded. `STORAGE_BACKEND=blob` is set; the code is doing what it was told.
- Hypothesis: "Read path also broken" — REJECTED for the immediate symptom. `storage.get_playable_url` handles null path. The crash is purely the INSERT NOT NULL violation.

## Resolution

```yaml
root_cause: "Phase 10 shipped the write-path code change (db_postgres.py:177 passes path=NULL when storage returns a blob URL) but never authored the corresponding Alembic migration to relax the clips.path NOT NULL constraint. The schema migration is missing — the Postgres path was not exercised in CI (DATABASE_URL unset → 5 tests skipped) and live HUMAN-UAT was deferred to merge time, so the mismatch was invisible until the preview deploy."
fix: "Author a new Alembic revision that drops NOT NULL on clips.path and adds a CHECK constraint enforcing (path IS NOT NULL OR blob_url IS NOT NULL). Apply via Railway preDeployCommand. Separately, fix pipeline/embed.py:126-128 to read blob_url first when path is null, downloading via blob_client into a NamedTemporaryFile before calling _sync_embed (mirroring the compile.py:42-67 _download_refs_to_tempdir pattern)."
verification: "Pending — see 'Recommended Fix' below. To verify: (1) DATABASE_URL set + STORAGE_BACKEND=blob, run alembic upgrade head, then POST /clips with a small mp4. Expect 202 and a row with path IS NULL, blob_url populated. (2) Wait for embed_worker to fire (pipeline/run.py async task chain) and confirm it does not crash on Path(None). (3) Verify stitch end-to-end on a 2+ parent cluster."
files_changed: []
```

## Recommended Fix (two-part — one is mandatory, the other is a prerequisite for the rest of the pipeline to work)

### Part 1 — MANDATORY: new Alembic revision (unblocks INSERT)

New file: `backend/migrations/versions/20260428_0002_relax_clips_path_not_null.py`

```python
"""relax clips.path NOT NULL — Phase 10 blob-mode INSERT writes path=NULL.

Revision ID: 0002_relax_clips_path_not_null
Revises: 0001_initial_v1_1_schema
Create Date: 2026-04-28

Phase 10 (D-12) writer at backend/db_postgres.py:177 passes path=NULL when
storage.save_clip_bytes returns an HTTP URL (Vercel Blob). The Phase 9 baseline
declared clips.path TEXT NOT NULL — the constraint was never relaxed. CHECK
constraint added to enforce that exactly one of (path, blob_url) is populated.

Children (insert_child_clip) write path="" (empty string), which satisfies
NOT NULL today and satisfies the CHECK below as a non-null value. Children
are unchanged.

Downgrade (D-15): hackathon-grade, no rollback. Mirrors 0001's posture.
"""
from alembic import op


revision = "0002_relax_clips_path_not_null"
down_revision = "0001_initial_v1_1_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE clips ALTER COLUMN path DROP NOT NULL")
    op.execute(
        "ALTER TABLE clips ADD CONSTRAINT clips_path_or_blob_url_present "
        "CHECK (path IS NOT NULL OR blob_url IS NOT NULL)"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 10 schema relax is one-way; rollback unsupported (D-15)"
    )
```

This unblocks the immediate crash. Railway preDeployCommand runs `alembic upgrade head`, so a redeploy applies it.

### Part 2 — REQUIRED before the next pipeline stage runs: fix `embed_worker` for blob mode

`backend/pipeline/embed.py:126-128` will crash on the next clip uploaded after Part 1 lands, because:

```python
clip_path = clip["path"]                    # None in blob mode
if not Path(clip_path).exists():            # TypeError: argument should be str/Path, not NoneType
    raise FileNotFoundError(...)
```

Minimum fix: download the blob to a tempfile before calling `_sync_embed`. Reference pattern: `backend/pipeline/compile.py:42-67` (`_download_refs_to_tempdir`).

```python
# embed_worker, after fetching clip row:
clip_path = clip["path"]
blob_url = clip.get("blob_url")
if blob_url:
    # Phase 10 blob mode — download to tempfile for Marengo upload.
    from ..storage import blob_client
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        client = blob_client.get_client()
        # blob_url is private — needs Bearer header
        headers = {"Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}"}
        async with client.stream("GET", blob_url, headers=headers) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                tmp.write(chunk)
        clip_path = tmp.name
    try:
        ... # _sync_embed(clip_path, clip_id) ...
    finally:
        os.unlink(clip_path)
elif clip_path and not Path(clip_path).exists():
    raise FileNotFoundError(...)
```

If you ship Part 1 only, POST /clips will succeed but the embed pipeline will crash silently (asyncio task, logs only) and clips will sit at `embedding_status='pending'` forever. The user-visible symptom shifts from a 500 to a feed that never updates.

### Optional Part 3 — schema discipline

Update Phase 10 verification + `deferred-items.md` to record that the schema migration was missed and the Postgres-mode INSERT was never tested in CI. Consider adding a Postgres-against-real-DB test (or at least a fixture that runs migrations + a single INSERT) gated behind a CI env var.

## Notes for the user

- **The fix scope is bigger than the immediate crash.** Part 1 alone "fixes" the symptom but breaks the next stage. If you only have time for one PR, ship both parts together.
- **Specialist hint:** Postgres migration + Alembic revision authoring. No specialist agent registered for this; standard `engineering:debug` would apply.
- **Phase 10 verification was technically lying:** `10-VERIFICATION.md:198-210` claimed "Schema Discipline" was clean because no new migration existed. The verifier missed that absence-of-migration was the bug, not the proof of correctness.
