# Phase 10: Vercel Blob Migration — Pattern Map

**Mapped:** 2026-04-29
**Files analyzed:** 15 (5 new + 10 modified)
**Analogs found:** 15 / 15 (every new/modified file has a strong in-repo analog)

## Phase 8 / Phase 9 inheritance summary (apply to ALL new/modified backend files)

| Inherited Pattern | Source | What Phase 10 must respect |
|---|---|---|
| Middleware order | `backend/app.py:140-147` (Phase 8 D-12) | Do NOT reorder. New `app.py` lines (httpx init, conditional `/media` mount) sit between middleware add and route declarations — never between middleware. |
| structlog contextvars whitelist | Phase 8 PRIV-02 (D-08) | Blob URLs / signed-URL tokens / `pathname` are kwargs only (`log.info("blob_op", op="upload", pathname=p, latency_ms=ms)`). Never `bind_contextvars`. |
| Sentry `before_send` redacts `blob_url` | Phase 8 D-14 | Free PII safety; do NOT bypass it by stringifying URLs into `extra` payloads under fresh keys. |
| Graceful-degrade on empty config | `backend/db.py:16-24`, `backend/observability/sentry.py:25` | Empty `BLOB_READ_WRITE_TOKEN` is fine when `OFFLINE_DEMO=true` → forces local. |
| Fail-loud on missing config | `backend/db_postgres.py:98-104` | Empty `BLOB_READ_WRITE_TOKEN` when `STORAGE_BACKEND=blob` AND `OFFLINE_DEMO=false` → raise at lifespan startup. |
| Single Uvicorn worker | Phase 9 L-02 (`backend/db_postgres.py:8-10, 64`) | Module-level `httpx.AsyncClient` singleton in `blob_client.py` is process-wide; no inter-process coordination. |
| OFFLINE_DEMO hard-override | Phase 9 D-11 (`backend/db.py:19-21`) | `OFFLINE_DEMO=true` forces `local` regardless of `STORAGE_BACKEND` — same shape, log line `storage_backend=local (forced by OFFLINE_DEMO=true)`. |
| Async wrappers around `_sync_*` | `backend/pipeline/stitch.py:90-109, 166-176` | Keep `async def stitch_clips` / `trim_window` shape unchanged. Signed-URL minting + tempdir setup happens BEFORE the `loop.run_in_executor` call, not inside `_sync_*`. |
| Atomic-rename ffmpeg outputs | `backend/pipeline/stitch.py:63-79, 132-155` | Preserve `.part-{ts}-{pid}` → `os.replace(...)` sequence. Upload happens AFTER `os.replace`, in the async wrapper. |
| Failure-fallback pattern | `backend/pipeline/stitch.py:101-109, 167-176` (returns source path on failure) | Maintain semantics: on upload failure, return the source signed URL (frontend can still play). |
| `bind_contextvars(clip_id=...)` survives `asyncio.create_task` | `backend/app.py:191` (Phase 8 D-08) | Storage logs auto-inherit `clip_id`. Do NOT re-bind. |
| Module-import-time backend selection | `backend/db.py:16-24` | Same `if/elif/else` shape with `from .blob import *` / `from .local import *`. No per-request branching. |
| Single module-level client init in lifespan | `backend/app.py:96-97`, `db_postgres.py:71-115` | Init httpx client in `lifespan()` startup, close in shutdown. Order: asyncpg pool → blob client → keepalive → pre-warms. |

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| **NEW** `backend/storage/__init__.py` | dispatcher | request-response | `backend/db.py:1-24` | exact (mirror Phase 9 D-08) |
| **NEW** `backend/storage/local.py` | service (file I/O) | file-I/O | `backend/db_sqlite.py:159-180, 191-211` | role-match (lift-and-shift) |
| **NEW** `backend/storage/blob.py` | service (HTTP) | request-response | `backend/db_postgres.py:158-205` (signature parity) + `backend/storage/local.py` (peer interface) | role-match |
| **NEW** `backend/storage/blob_client.py` | utility (HTTP wrapper) | request-response | `backend/db_postgres.py:64-124` (asyncpg pool lifecycle pattern) | role-match |
| **NEW** `backend/scripts/seed_demo_to_blob.py` (optional) | script | batch | `backend/scripts/sqlite_to_postgres.py:1-60` | role-match |
| **MOD** `backend/app.py` | controller (lifespan + route) | request-response | self (Phase 9 lifespan additions) | exact |
| **MOD** `backend/db_sqlite.py` | service (DB) | CRUD | self | exact |
| **MOD** `backend/db_postgres.py` | service (DB) | CRUD | self (mirror sqlite changes) | exact |
| **MOD** `backend/pipeline/stitch.py` | service (ffmpeg) | streaming | self | exact |
| **MOD** `backend/pipeline/compile.py` | service (orchestration) | streaming | self | exact |
| **MOD** `backend/config.py` | config | n/a | `backend/config.py:42-56` (Phase 9 var block) | exact |
| **MOD** `backend/.env.example` | config | n/a | `backend/.env.example:18-26` (Phase 9 block) | exact |
| **MOD** `backend/requirements.txt` | config | n/a | self | exact |
| **MOD** `backend/tests/conftest.py` | test fixture | n/a | `backend/tests/conftest.py:19-40` (Phase 9 D-10 fixture) | exact |
| **MOD** `frontend/src/api.ts` | controller (HTTP) | request-response | self (lines 27-33) | exact |
| **MOD** `frontend/src/types.ts` | model (doc-string only) | n/a | self | exact |
| **MOD** `frontend/src/components/SegmentCard.test.tsx` | test fixture | n/a | self (lines 35-49) | exact |

---

## Pattern Assignments — NEW files

### `backend/storage/__init__.py` (dispatcher, request-response)

**Analog:** `backend/db.py:1-24` (Phase 9 D-08 dispatcher).

**Conventions to preserve:**
- Module-docstring header that names the locked decision (e.g., "Phase 10 (D-12, D-13): STORAGE_BACKEND dispatcher — module-import-time selection.")
- Bare `import logging` + `log = logging.getLogger(__name__)` (NOT structlog directly — stdlib bridge in observability does the JSON conversion).
- Three-arm `if/elif/else` mirroring `db.py:16-24`. The `OFFLINE_DEMO=true` arm logs `(forced by OFFLINE_DEMO=true; D-18)`.
- `from .blob import *  # noqa: F401, F403` and `from .local import *  # noqa: F401, F403` — no per-name re-export, no `__all__` at the dispatcher level.

**Excerpt to clone (`backend/db.py:10-24`):**
```python
import logging

from . import config

log = logging.getLogger(__name__)

if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO:
    from .db_postgres import *  # noqa: F401, F403
    log.info("metadata_backend=postgres")
elif config.METADATA_BACKEND == "postgres" and config.OFFLINE_DEMO:
    from .db_sqlite import *  # noqa: F401, F403
    log.info("metadata_backend=sqlite (forced by OFFLINE_DEMO=true; D-11)")
else:
    from .db_sqlite import *  # noqa: F401, F403
    log.info("metadata_backend=sqlite")
```

**Phase 8/9 inheritance:** Phase 9 D-08 module-split, Phase 9 D-11 OFFLINE_DEMO override, Phase 8 stdlib-logger style.

---

### `backend/storage/local.py` (service, file-I/O)

**Analog:** `backend/db_sqlite.py:159-180` (the `path.write_bytes(contents)` body) and `backend/db_sqlite.py:191-211` (the `f"/media/{filename}"` URL builder).

**Public surface (D-12):** `save_clip_bytes(clip_id, ext, contents) -> str`, `delete_clip(path_or_url) -> None`, `get_playable_url(row) -> str`.

**Conventions to preserve:**
- `__all__` list at the top mirroring `db_sqlite.py:18-42` style.
- Top-of-file `CLIPS_DIR = config.DATA_DIR / "clips"` constant (currently `db_sqlite.py:16`).
- `log.info("save_clip ... bytes=%d", ...)` keyword style — same as `insert_clip` line 179.
- `path.write_bytes(contents)` synchronously (Python's `Path.write_bytes` is sync but the surrounding function is `async def` — matches `db_sqlite.py:170` exactly).
- Return value: when called from local mode, return the `str(path)` so DB rows store the same shape as v1.0.
- `get_playable_url(row)`: return `f"/media/{Path(row['path']).name}"` for legacy rows; return `row["blob_url"]` if populated (forward-compat for mixed-mode rollback windows).

**Excerpt to lift (`backend/db_sqlite.py:165-180`):**
```python
clip_id = uuid.uuid4().hex
ext = ext_from_mime(file.content_type)
path = CLIPS_DIR / f"{clip_id}.{ext}"
contents = await file.read()
path.write_bytes(contents)
```
That five-line block becomes the body of `storage.local.save_clip_bytes(clip_id, ext, contents)`. The `uuid.uuid4().hex` and `ext_from_mime` calls stay in `db_sqlite.insert_clip` / `db_postgres.insert_clip` (storage doesn't own clip identity).

**URL-builder excerpt to lift (`backend/db_sqlite.py:202-205`):**
```python
filename = Path(r["path"]).name
out.append({
    "id": r["id"],
    "url": f"/media/{filename}",
```
Becomes `get_playable_url(row)` returning `f"/media/{Path(row['path']).name}"`.

**Phase 8/9 inheritance:** Same `log = logging.getLogger(__name__)` style. No structlog kwargs needed at this layer (callers are already inside `bind_contextvars(clip_id=...)`).

---

### `backend/storage/blob.py` (service, request-response over HTTP)

**Analog:** `backend/db_postgres.py:158-205` for shape parity (signature parity with `local.py`); `backend/storage/local.py` for the peer interface contract.

**Public surface (D-12, D-25 — identical signatures to `local.py`):**
- `async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str` — uploads to `uploads/{clip_id}.{ext}` (private), returns absolute Blob URL.
- `async def delete_clip(path_or_url: str) -> None` — extracts `pathname` from the URL, calls `blob_client.delete(pathname)`. Idempotent (no raise on 404).
- `def get_playable_url(row) -> str` — for `runs/` returns `row["blob_url"]` directly (public CDN). For `uploads/` reads (ffmpeg trim source) callers use `mint_signed_url` directly via the wrapper, NOT this function.
- `async def cleanup_blocked_clip(clip_id: str) -> None` — D-20 BLOB-08 hook. Looks up row, calls `delete_clip`, no-ops if already deleted.

**Conventions to preserve:**
- Module-docstring matches `db_postgres.py:1-14` style: cite D-numbers, name the dispatcher contract, name the locked decisions.
- Defer to `blob_client` for HTTP — `blob.py` is the storage interface, never imports `httpx` directly (D-25).
- Structured log line on every operation: `log.info("blob_op op=%s pathname=%s latency_ms=%d bytes=%d", ...)` (D-28). For the structlog stdlib bridge to emit them as JSON kwargs, prefer:
  ```python
  log.info("blob_op", extra={"op": "upload", "pathname": pathname, "latency_ms": ms, "bytes": n})
  ```
  Match Phase 8 / observability style; no signed-URL tokens in logs.
- Errors propagate as exceptions from `blob_client`; do NOT swallow them here (the async wrappers in `pipeline/stitch.py` own the failure-fallback semantics).

**Excerpt to clone for shape (`backend/db_postgres.py:158-178`):**
```python
async def insert_clip(
    file: UploadFile,
    lat: float,
    lng: float,
    ts: float,
    session_id: str | None,
) -> str:
    clip_id = uuid.uuid4().hex
    ext = ext_from_mime(file.content_type)
    path = CLIPS_DIR / f"{clip_id}.{ext}"
    contents = await file.read()
    path.write_bytes(contents)
    ...
```
Storage signatures are SHORTER (no DB work) but follow the same docstring-then-code shape.

**Phase 8/9 inheritance:** structlog kwargs whitelist (PRIV-02 — only `op`, `pathname`, `latency_ms`, `bytes`); single-process singleton (L-08 / D-02); fail-loud on missing token (D-19, mirror of `db_postgres.py:98-104`).

---

### `backend/storage/blob_client.py` (utility, HTTP wrapper)

**Analog:** `backend/db_postgres.py:64-124` (asyncpg pool init/close lifecycle) is the closest behavioral analog. The retry shape uses `tenacity` (already in requirements; D-24).

**Public surface (D-03 locked):**
- Module-level `_client: httpx.AsyncClient | None = None`, `def get_client() -> httpx.AsyncClient` (mirror of `db_postgres.get_pool`).
- `async def init_client() -> None` (mirror of `init_pool`).
- `async def close_client() -> None` (mirror of `close_pool`).
- `async def upload(prefix: str, key: str, body: bytes | AsyncIterator[bytes], *, content_type: str, access: Literal["public", "private"]) -> BlobObject`
- `async def mint_signed_url(pathname: str, *, ttl_seconds: int = 900) -> str`
- `async def delete(pathname: str) -> None`
- `async def head(pathname: str) -> BlobObject | None`

**Conventions to preserve (mirror `db_postgres.py:71-124` exactly):**
- `RuntimeError("httpx blob client not initialized — backend.app.lifespan must call init_client() first")` — verbatim shape of `db_postgres.py:77-79`.
- Idempotent `init_client` (warn-and-return on second call, like `init_pool` line 96).
- Fail-loud body for missing `BLOB_READ_WRITE_TOKEN` mirror `db_postgres.py:98-104`:
  ```python
  if not config.BLOB_READ_WRITE_TOKEN:
      raise RuntimeError(
          "BLOB_READ_WRITE_TOKEN is empty but STORAGE_BACKEND=blob and OFFLINE_DEMO=false. "
          "Set BLOB_READ_WRITE_TOKEN or flip STORAGE_BACKEND=local to use the local-FS path."
      )
  ```
- Sanitize on init failure: `log.error("blob client init failed: %s (token redacted)", type(exc).__name__)` — mirror of line 114 (DSN→token swap).
- Module-level singleton + `--workers 1` justification in docstring (mirror `db_postgres.py:8-10, 63`).
- `tenacity` retry: only on transient 5xx + network errors. 4xx and 401/403 fail-loud immediately (D-24).

**Excerpt to clone (`backend/db_postgres.py:71-124`):**
```python
def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError(
            "asyncpg pool not initialized — backend.app.lifespan must call init_pool() first"
        )
    return _pool


async def init_pool() -> None:
    global _pool
    if _pool is not None:
        log.warning("init_pool called twice; ignoring second call")
        return
    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is empty but METADATA_BACKEND=postgres and OFFLINE_DEMO=false. ..."
        )
    try:
        _pool = await asyncpg.create_pool(...)
        log.info("asyncpg pool created min=1 max=10")
    except Exception as exc:
        log.error("asyncpg pool init failed: %s (DSN redacted)", type(exc).__name__)
        raise
```

**Phase 8/9 inheritance:** Phase 9 D-16 (lifespan-managed pool/client), L-08 (single-process singleton), Phase 8 D-14 (Sentry redacts blob_url/token; never log token), Phase 8 D-17 (no high-cardinality Prometheus labels — only `op` if metrics added).

---

### `backend/scripts/seed_demo_to_blob.py` (optional, batch script)

**Analog:** `backend/scripts/sqlite_to_postgres.py:1-60`.

**Conventions to preserve:**
- Module-docstring with `Usage:` block, `Pre-requisites:`, `Idempotency:`, `Security:` sections (mirror `sqlite_to_postgres.py:1-17`).
- Read secrets from environment, NEVER from `argparse` (Security action item from `sqlite_to_postgres.py:16-17`).
- `python -m backend.scripts.seed_demo_to_blob` invocation form (relative imports — `from .. import config`).
- Idempotent: skip clip if `/clips` returns 409, or pre-call `POST /admin/reset` once at the top.
- `argparse` for `--force` flag in the Phase 9 script style if needed.

**Phase 8/9 inheritance:** Logging style; secrets discipline; `python -m` invocation.

**Open mapping question:** ship this script in Phase 10 as code, or as a doc-snippet in `10-PLAN.md`? Defer to planner.

---

## Pattern Assignments — MODIFIED files

| Modified File | What Changes | Conventions to Preserve |
|---|---|---|
| `backend/app.py:88-127` (`lifespan`) | Add `await blob_client.init_client()` (after asyncpg pool init, before keepalive task). Add `await blob_client.close_client()` in `finally` (after pool close). Conditional on `config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO`. | Mirror Phase 9 `init_pool` placement (line 96-97). Use `hasattr`-style branch — but here a config check is simpler. Keep order: pool → blob client → rebuild_cache → keepalive → pre-warms (per CONTEXT line 201). |
| `backend/app.py:149-151` (`/media` mount) | Wrap in `if config.STORAGE_BACKEND == "local" or config.OFFLINE_DEMO:` per D-16. | Keep `mkdir(parents=True, exist_ok=True)` calls (always safe; cheap). Don't move them inside the conditional — `DATA_DIR` is still used by sqlite/Alembic/etc. |
| `backend/db_sqlite.py:166-180` (`insert_clip`) | Replace `path = CLIPS_DIR / ...; path.write_bytes(contents)` with `result = await storage.save_clip_bytes(clip_id, ext, contents)`. INSERT writes `result` into `clips.blob_url` if it starts with `http`, else `clips.path` (D-14). | Keep `uuid.uuid4().hex` and `ext_from_mime` calls in this function. Keep `log.info("insert_clip id=%s bytes=%d", ...)` line. SCHEMA_SQL stays unchanged (blob_url column is added by Phase 9 Alembic for postgres; sqlite still has v1.0 schema and stores in `path` — graceful split). |
| `backend/db_sqlite.py:202-205` (`fetch_recent_clips` URL builder) | Replace inline `f"/media/{filename}"` with `storage.get_playable_url(r)`. | Keep the dict shape `{"id": ..., "url": ..., "lat": ..., ...}`. |
| `backend/db_sqlite.py:374-379` (`fetch_recent_segments._url`) | Same replacement: `storage.get_playable_url(...)` for clip rows; `_run_*` IDs build via `storage` too (Phase 10 uploads runs to Blob, so `f"/media/{clip_id}.mp4"` becomes the absolute Blob URL stored in segment row `video_url`). | Keep the inner `def _url(clip_id)` helper. The "_run_" branch returns `seg.video_url` from Blob (set at compile-time) when populated; falls back gracefully. |
| `backend/db_sqlite.py:597-613, 666-695` (admin reset path collection) | `paths_to_delete` may contain absolute Blob URLs in blob mode. Either: (a) leave the cleanup to `storage.delete_clip()` called from `app.py:_delete_files` shim, or (b) skip URL-shaped entries in the local `_delete_files` helper (`app.py:420-430`). | Plan B is simpler and matches the failure-tolerant style at `app.py:420-430` (already swallows exceptions per-path). |
| `backend/db_postgres.py:165-178, 196-205, 367-383, 612, 695` | Mirror every change in `db_sqlite.py` 1:1 — signature parity is the dispatcher contract (`db_postgres.py:5`). | Preserve `pool.execute` / `pool.fetch` / `pool.fetchrow` style. Preserve `ANY($1::text[])` over `IN (...)` placeholders. |
| `backend/pipeline/stitch.py:30-87` (`_sync_stitch`) | UNCHANGED internals — operates on local file paths. The CALLER (in `compile.py`) is responsible for downloading sources into a tempdir and rewriting `ref["path"]` to local paths first. | Preserve the W=720, H=1280, FPS=30 constants and the normalize-and-concat filter graph — those are calibration-locked (lessons-carried-forward in CLAUDE.md). |
| `backend/pipeline/stitch.py:112-163` (`_sync_trim`) | `ref["path"]` may now be a signed-URL string (D-08). ffmpeg-python passes URLs through to ffmpeg's libavformat which handles HTTP Range natively. `-c copy` continues to work with HTTP inputs. NO code change inside `_sync_trim` itself. | Preserve atomic-rename `.part-{ts}-{pid}` → `os.replace`. Preserve `loglevel error` global arg. |
| `backend/pipeline/stitch.py:90-109, 166-176` (async wrappers) | `trim_window`: after `_sync_trim` writes the local temp .mp4, **upload it to Blob** under `runs/` and return the absolute URL. On upload failure, return `ref["path"]` (the source signed URL — frontend can play it; existing fallback semantics extend cleanly). | Preserve the `try/except` + `log.warning("trim FAILED — falling back to source path: %s", exc)` shape. **NEW:** the upload step lives in the async wrapper, not `_sync_trim` (D-10 sequential). |
| `backend/pipeline/compile.py:194-217` (`_resolve_run_ids_to_stitch_refs`) | `r.parent_path` becomes `await storage.mint_signed_url(parent_pathname, ttl_seconds=900)` when `STORAGE_BACKEND=blob` (D-06, D-08). For local mode, it stays a filesystem path. | Preserve `member_child_ids == []` → `end=None` semantics. Preserve the dict shape `{"path", "start_offset_sec", "end_offset_sec"}`. |
| `backend/pipeline/compile.py:312-359` (`_stitch_segment_runs`) | `output_path = str(config.DATA_DIR / "clips" / f"{run_id}.mp4")` becomes a `tempfile.NamedTemporaryFile(suffix='.mp4')` path. After `trim_window` succeeds and writes to it, upload to `runs/{run_id}.mp4` (public). Return absolute Blob URL into segment row's `video_url`. | Preserve `asyncio.gather` parallelism. Preserve `log.info("trim ok run_id=%s elapsed_ms=%d", ...)` style. The "_run_*.mp4" filename convention stays — it's still the Blob `pathname`. |
| `backend/pipeline/compile.py:425, 439, 462` (URL string construction) | Replace any inline `/media/{run_id}.mp4` with the absolute Blob URL from the upload step. | Preserve `video_urls = [_url(cid) for cid in ids]` array shape. |
| `backend/config.py` | Add: `STORAGE_BACKEND: str = os.environ.get("STORAGE_BACKEND", "local").strip().lower()` and `BLOB_READ_WRITE_TOKEN: str = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()`. | Mirror Phase 9 block (`backend/config.py:42-56`) — section comment header `# Phase 10: Vercel Blob migration (D-12, D-19, D-23)`, multi-line per-var docstring with the D-numbers, fail-loud justification. |
| `backend/.env.example` | Append a new section after the Phase 9 block (line 26): mirror its style — section comment, per-var comment with the locked-decision justification, default value. `STORAGE_BACKEND=local` and `BLOB_READ_WRITE_TOKEN=` (empty default). | Mirror the comment-block density of lines 18-26: one `#` line of justification per var, then `KEY=value`. |
| `backend/requirements.txt` | Verify `httpx` is pinned. FastAPI `0.115.6` (line 1) pulls `httpx` transitively via `starlette`'s `TestClient` extras, but a deploy-time pin is safer. Add `httpx>=0.27.0,<0.29.0` if not already present. | Preserve trailing-newline + alphabetical-ish style. `tenacity` (line 8) already present — re-used per D-24. |
| `backend/tests/conftest.py:19-40` | Extend `metadata_backend` fixture into a 2x2 matrix or add a sibling `storage_backend` fixture parametrized `["local", "blob"]`. Cells with `storage_backend=blob` use a recorded-tape httpx mock (pytest-vcr or hand-rolled) — never hit real Vercel Blob from CI (D-21). Cell `local + sqlite` is the OFFLINE_DEMO firewalled path (DEMO-02). | Preserve `monkeypatch.setenv` + `importlib.reload` pattern (lines 31-39). Preserve `pytest.skip("...")` shape for missing creds (line 30). |
| `frontend/src/api.ts:27-33` | Audit per D-17. The current `${API_BASE}${s.video_url}` template will produce `http://localhost:8000https://blob.../...` if `s.video_url` is absolute — visibly broken (404). Add a one-line guard: `s.video_url.startsWith('http') ? s.video_url : \`${API_BASE}${s.video_url}\``. Apply same guard to `video_urls.map(...)`. | Preserve the `(s) => ({ ...s, url: ..., video_urls: ... })` shape. Preserve null-handling. |
| `frontend/src/types.ts:7-9, 69-72` | Update doc-string comments to acknowledge absolute Blob URLs. Line 7-9 (`Clip.url`): "Absolute URL (Vercel Blob `runs/`) or relative path (`/media/...` in local rollback mode)." Line 69-70 (`Segment.video_url`): same. | Preserve TypeScript JSDoc style (`/**` block above each field). No type change — `string \| null` already covers both shapes. |
| `frontend/src/components/SegmentCard.test.tsx:35-49` | Add a parallel test fixture with `video_url: "https://example.public.blob.vercel-storage.com/runs/seg-1.mp4"`. Assert that `SegmentCard` doesn't double-prefix it (the assertion lives in the api.ts unit test ideally; this test just renders both shapes). | Preserve the `const segment: Segment & { url: string \| null } = { ... }` literal style (line 35). Preserve the `playMock` / `pauseMock` / `act(...)` test machinery. |

---

## Shared Patterns

### Backend dispatcher (Phase 9 D-08 → Phase 10 D-13)
**Source:** `backend/db.py:16-24`
**Apply to:** `backend/storage/__init__.py`
**Excerpt:** see "Pattern Assignments — `backend/storage/__init__.py`" above. Verbatim three-arm shape with OFFLINE_DEMO override arm logging "(forced by OFFLINE_DEMO=true; D-18)".

### Lifespan-managed singleton (Phase 9 D-16 → Phase 10 D-02)
**Source:** `backend/db_postgres.py:64-124`, called from `backend/app.py:96-97, 126-127`
**Apply to:** `backend/storage/blob_client.py` + `backend/app.py:lifespan`
**Excerpt:** see "Pattern Assignments — `backend/storage/blob_client.py`" above.

### Fail-loud on missing config (Phase 9 → Phase 10 D-19)
**Source:** `backend/db_postgres.py:98-104`
**Apply to:** `backend/storage/blob_client.py:init_client()`
**Excerpt:**
```python
if not config.DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is empty but METADATA_BACKEND=postgres and OFFLINE_DEMO=false. "
        "Set DATABASE_URL or flip METADATA_BACKEND=sqlite to use the SQLite path."
    )
```

### Async wrapper around `_sync_*` (preserve)
**Source:** `backend/pipeline/stitch.py:90-109, 166-176`
**Apply to:** preserved unchanged in `_sync_stitch` / `_sync_trim`. Phase 10's signed-URL minting and blob-upload sequencing happen INSIDE the async wrapper, AROUND the `loop.run_in_executor` call — never inside `_sync_*` itself.
**Excerpt:**
```python
async def trim_window(ref: dict, output_path: str) -> str:
    if not ref:
        return ""
    fallback_path = ref["path"]
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_trim, ref, output_path)
    except Exception as exc:
        log.warning("trim FAILED — falling back to source path: %s", exc)
        return fallback_path
```
Phase 10 inserts the blob-upload step between the `loop.run_in_executor` line and `return`. On upload failure, return `ref["path"]` (the source signed URL).

### Atomic-rename ffmpeg outputs (preserve)
**Source:** `backend/pipeline/stitch.py:63-79, 132-155`
**Apply to:** unchanged. Upload happens AFTER `os.replace` succeeds — atomic-rename guarantees the local temp file is fully written before we touch the network.

### structlog kwargs whitelist (Phase 8 PRIV-02)
**Source:** Phase 8 D-08 contextvars whitelist (`clip_id`, `request_id`, `session_hash` only).
**Apply to:** all new `backend/storage/*.py` log lines.
**Rule:** Blob URLs, signed-URL tokens, `pathname` are **kwargs only** (pass via `extra={...}` in stdlib log call, or as positional `%s` args). Never `bind_contextvars`. CONTEXT line 44 (L-07) is explicit.

### Configurable env-var section header (Phase 8/9 style)
**Source:** `backend/config.py:42-56`, `backend/.env.example:18-26`
**Apply to:** `backend/config.py` (new vars) and `backend/.env.example` (new vars).
**Excerpt (config.py:42-56):**
```python
# Phase 9: Postgres migration (D-06, D-08, D-11, D-17)
# DATABASE_URL: Neon DIRECT endpoint connection string (NOT -pooler — RESEARCH Pitfall 1).
#   Stock Neon URL works as-is; asyncpg parses sslmode=require natively (RESEARCH D-18 resolution).
#   Empty when METADATA_BACKEND=postgres + OFFLINE_DEMO=false should fail-loud at pool init.
DATABASE_URL: str = os.environ.get("DATABASE_URL", "").strip()
```
Mirror density and citation style for `STORAGE_BACKEND` and `BLOB_READ_WRITE_TOKEN`.

### Test parametrize fixture (Phase 9 D-10 → Phase 10 D-21)
**Source:** `backend/tests/conftest.py:19-40`
**Apply to:** extend with second axis or sibling fixture for `STORAGE_BACKEND`.
**Excerpt:**
```python
@pytest.fixture(params=["sqlite", "postgres"], ids=["sqlite", "postgres"])
def metadata_backend(request, monkeypatch):
    backend = request.param
    if backend == "postgres" and not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; postgres path skipped")
    monkeypatch.setenv("METADATA_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    import backend.config
    import backend.db
    importlib.reload(backend.config)
    importlib.reload(backend.db)
    yield backend
```
Phase 10 sibling: `params=["local", "blob"]`, `pytest.skip` when `BLOB_READ_WRITE_TOKEN` empty AND no recorded-tape fixture. Don't forget to `importlib.reload(backend.storage)`.

### Frontend test fixture (preserve)
**Source:** `frontend/src/components/SegmentCard.test.tsx:35-49`
**Apply to:** add a second `const blobSegment` fixture in the same file with absolute Blob URL.
**Excerpt:**
```tsx
const segment: Segment & { url: string | null } = {
  id: "seg-1",
  cluster_id: "cluster-1",
  ordered_clip_ids: ["clip-1"],
  title: "Test Title",
  caption: "Test caption",
  location: "Pasadena, CA",
  source_count: 1,
  created_at: Math.floor(Date.now() / 1000),
  centroid_lat: null,
  centroid_lng: null,
  video_url: "/media/test.mp4",
  video_urls: ["/media/test.mp4"],
  url: "/media/test.mp4",
};
```
The Blob fixture differs only on `video_url`, `video_urls`, and `url` strings. Keep the same `Segment & { url: string | null }` type ascription.

---

## Anti-patterns to avoid

| Anti-pattern | Why it's wrong | Source-of-fact |
|---|---|---|
| **Per-request branching on `STORAGE_BACKEND`** | The dispatcher is a module-import-time selection. Per-request `if config.STORAGE_BACKEND == ...` inside `insert_clip` reintroduces the branching cost and undermines the lift-and-shift contract. | Phase 9 D-08; Phase 10 D-13; CONTEXT line 75-83 |
| **Importing `httpx` from `backend/storage/blob.py`** | D-25 isolates HTTP details to `blob_client.py`. Importing `httpx` in `blob.py` couples the storage interface to the transport library. | D-25; CONTEXT line 112 |
| **Logging signed URLs verbatim** | The signed URL contains the bearer-style query token. Sentry's `before_send` redacts `blob_url` keys but a raw signed URL stored under a different key would leak. Log `pathname` only. | L-06, L-07; D-28; PRIV-02 |
| **Adding `blob_url` or `pathname` as a structlog contextvar** | PRIV-02 contextvars whitelist is `clip_id`, `request_id`, `session_hash` only. Per-call values are kwargs. | L-07; PRIV-02 |
| **Pre-warming Blob on startup** | D-27 explicitly rejects this. Vercel Blob has no Marengo-style cold start, and a warm-up call would open a network connection under `OFFLINE_DEMO=true`, violating the firewalled-CI invariant. | D-27 |
| **In-process signed-URL caching** | D-06 explicitly says mint-fresh-per-call. Caching introduces cache-coherence bugs at signed-URL TTL boundaries and during recompiles after BLOB-08 cleanup. | D-06 |
| **Direct browser PUT to Blob (Vercel client-upload tokens)** | Permanently rejected — skips moderation gate. L-02. | L-02; REQUIREMENTS Out of Scope |
| **Streaming trim output through a pipe directly to Blob** | Breaks atomic-rename + failure-fallback contract in `_sync_trim`. D-10 explicitly chose sequential trim → local temp → upload over streaming. | D-10; specifics line 221 |
| **Cluster-level tempdir reuse / cross-recompile cache** | D-09 explicitly defers — adds cache-coherence concerns mid-migration. v1.2 candidate. | D-09; specifics line 222 |
| **Adding a downgrade body to the Alembic migration to drop `blob_url`** | The initial v1.1 migration is one-way (lines 144-149 raise NotImplementedError). Phase 10 uses NO new migration — the column already exists. | L-04; migration line 144-149 |
| **`cat << 'EOF'` / heredoc in scripts that write secrets** | `sqlite_to_postgres.py:16-17` pattern: secrets read from environment, never CLI args (avoids shell-history capture). | sqlite_to_postgres.py:16-17 |
| **Re-mounting `/media` unconditionally** | D-16: when `STORAGE_BACKEND=blob` and not `OFFLINE_DEMO`, the mount must NOT register (BLOB-05). | D-16; BLOB-05 |
| **Adding `pathname` as a Prometheus label** | Phase 8 D-17 caps label cardinality. `pathname` is high-cardinality (one per upload). Use `op` (upload\|delete\|sign) as the label dimension if metrics get added. | Phase 8 D-17 |
| **Reading `clips.path` as a Path in blob mode** | In blob mode, `clips.path` may be empty or unused; `clips.blob_url` carries the URL. `Path("https://...").name` works accidentally but is a code-smell. Always go through `storage.get_playable_url(row)`. | D-14 |
| **Dropping the `try/except` failure-fallback in `trim_window` / `stitch_clips`** | The "return source on failure" pattern is what keeps the demo alive when ffmpeg or Blob fails. D-10 says "return the source signed URL on upload failure" — preserves the contract. | stitch.py:101-109, 167-176; D-10 |

---

## What NOT to copy

- **`db_sqlite.py:170` `path.write_bytes(contents)`** — keep this exact line in `storage/local.py:save_clip_bytes`, but **do not** keep the `str(path)` insertion-into-DB line at `db_sqlite.py:176` literally. The DB call site moves to whatever-storage-returned. Storage owns the bytes-on-disk; DB owns the row.
- **`db_sqlite.py:374-379` `_url` helper inline** — do NOT copy this inline into `storage/local.py`. Move it BEHIND `storage.get_playable_url(row)` so both `db_sqlite.py` and `db_postgres.py` go through one function.
- **`db_postgres.py:60-61` `CLIPS_DIR: Path = config.DATA_DIR / "clips"`** — `storage/blob.py` does NOT need this constant. It's a `local.py` concern.
- **`backend/scripts/sqlite_to_postgres.py:34` `TABLES_IN_ORDER`** — not relevant to a seed script (only relevant to row-count parity).
- **Anthropic/OpenAI-style middleware decorators** — Newz uses bare FastAPI middleware classes (Phase 8 `XFFStrip`, `RequestIDAndContextvarsBind`). Do not introduce decorator-based middleware for blob ops.

---

## Open mapping questions for the planner

1. **Where does `cleanup_blocked_clip(clip_id)` live?** D-20 says "Phase 10 ships only the cleanup hook function." Most natural home is `backend/storage/blob.py` (next to `delete_clip`). Local mode would no-op or call `storage.local.delete_clip`. Confirm in `10-PLAN.md`.

2. **`storage/local.py` delete contract for v1.0-leftover absolute paths.** Phase 9 cutover preserved `clips.path` strings as absolute filesystem paths. Phase 10's `storage.local.delete_clip(path_or_url)` must accept either; the `app.py:_delete_files` shim already handles `try: Path(...).unlink()`. Spec the function signature carefully.

3. **`get_playable_url` for `_run_*` segment IDs in mixed-mode.** During a hypothetical `STORAGE_BACKEND` rollback window, runs compiled under `blob` mode would have absolute Blob URLs in `segments.video_url` while runs from before/after would have `/media/...`. The `_url(clip_id)` helper at `db_sqlite.py:374-379` and `db_postgres.py:375-383` needs to handle both. Recommend: prefer `seg.video_url` directly when present (it's already absolute or already relative — both work end-to-end), fall back to constructing only when null.

4. **`backend/scripts/seed_demo_to_blob.py`: ship code or doc-snippet?** D-15 leaves this to planner. If shipped as code, lift `sqlite_to_postgres.py` docstring shape; if doc-snippet, embed a 10-line `curl`/`httpx` example in `10-PLAN.md`.

5. **httpx pin in requirements.txt.** Verify whether `httpx` already pinned transitively via `fastapi[all]` or `sentry-sdk[fastapi]`. If not pinned, add `httpx>=0.27.0,<0.29.0`. Confirm in plan-check / smoke step.

6. **Test-fixture axis combinatorics.** D-21 says "2x2 = 4 cells." Two fixture options: (a) cross-parametrize a single fixture `params=[(s, m) for s in ["local","blob"] for m in ["sqlite","postgres"]]`, or (b) two sibling parametrize fixtures (more pytest-idiomatic, but `pytest_asyncio` may surprise on the cross-product). Recommend (a) for cell-skip granularity; planner picks.

7. **Blob `pathname` extraction from a stored URL.** When `delete_clip(url)` is called with `https://...vercel-storage.com/uploads/abc.mp4`, we need to parse `pathname=uploads/abc.mp4` for the Blob DELETE call. Document the URL-parsing helper inside `blob_client.py` (probably `_pathname_of(url)` private helper).

---

## Metadata

**Analog search scope:** `backend/`, `frontend/src/`, `.planning/phases/0[8,9]-*/`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/PROJECT.md`, `.planning/STATE.md`.
**Files scanned:** 14 (CONTEXT, app.py, db.py, db_sqlite.py, db_postgres.py, config.py, .env.example, requirements.txt, pipeline/stitch.py, pipeline/compile.py, tests/conftest.py, migrations/0001, frontend api.ts/types.ts/SegmentCard.test.tsx, plus scripts/ index).
**Pattern extraction date:** 2026-04-29.

## PATTERNS COMPLETE
