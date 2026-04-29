# Phase 10: Vercel Blob Migration - Context

**Gathered:** 2026-04-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Retire Railway local-FS clip storage. Uploads land in Vercel Blob via a server-mediated path (browser → FastAPI → Blob); direct browser PUT is rejected. ffmpeg reads source clips from Blob (signed-URL byte-range trim, tempdir-download stitch). Compiled run-segments land in Blob CDN under `runs/`. The `/media` StaticFiles mount is removed. `STORAGE_BACKEND` flag mirrors Phase 9's `METADATA_BACKEND` for migration-window rollback.

**In scope (from REQUIREMENTS.md):**
- Server-mediated upload to Blob `uploads/{clip_id}.{ext}` (BLOB-01)
- Compiled segments to Blob `runs/{run_id}.mp4` (BLOB-02)
- ffmpeg `_sync_trim` reads source from signed Blob URL via `-c copy` byte-range (BLOB-03)
- ffmpeg `_sync_stitch` pre-downloads sources into `tempfile.TemporaryDirectory()` (BLOB-04)
- Frontend renders absolute Blob URLs; `/media` StaticFiles mount removed (BLOB-05)
- `STORAGE_BACKEND` runtime feature flag for local-FS rollback (BLOB-06)
- Clip media survives Railway redeploy; backend never reads `/data/clips/` post-cutover (BLOB-07)
- Blob-cleanup hook for moderation-blocked clips (BLOB-08; called by Phase 11)

**Out of scope (deferred):**
- Inline moderation classifier wiring (Phase 11) — Phase 10 ships only the cleanup hook function; Phase 11 is the caller
- `moderation_status` column shape and writes (Phase 11)
- Reactive reporting flow (Phase 12)
- Logfire span tracing on the new ffmpeg-from-Blob path (Phase 13 OBS-05)
- Cloudflare R2 (explicitly rejected for v1.1 per REQUIREMENTS.md "Out of Scope" — re-evaluate v1.2 if egress becomes material)
- Direct browser → Blob upload via Vercel client-tokens (permanently rejected per REQUIREMENTS.md — skips moderation gate)
- Cluster-level tempdir reuse / cross-recompile source-clip cache (deferred — scope creep)
- `db_sqlite.py` deletion (v1.2; matches Phase 9 D-09)
- Backfill of v1.0 SQLite-rows-with-legacy-path (resolved as N/A — see D-15)

</domain>

<decisions>
## Implementation Decisions

### Inherited (locked elsewhere; do NOT re-litigate)
- **L-01:** Vercel Blob committed; no Cloudflare R2 in v1.1 — STATE.md `Locked Decisions`, PROJECT.md.
- **L-02:** Server-mediated upload only; direct browser PUT permanently rejected — STATE.md `Locked Decisions`, REQUIREMENTS.md "Out of Scope".
- **L-03:** `OFFLINE_DEMO=true` hard-overrides every external dependency to local stubs — STATE.md, REQ-DEMO-01. Phase 10 mirrors Phase 9 D-11: `OFFLINE_DEMO=true` forces `storage_local` regardless of `STORAGE_BACKEND`.
- **L-04:** `clips.blob_url TEXT` is already nullable in the initial Alembic migration (Phase 9 D-05; `migrations/versions/20260428_0001_initial_v1_1_schema.py:52`). Phase 10 populates it; no `ALTER` needed.
- **L-05:** `clips.is_hidden BOOLEAN NOT NULL DEFAULT FALSE` is already in the initial migration (Phase 9 D-05). Phase 11 owns the writes; Phase 10's cleanup hook reads it.
- **L-06:** Sentry `before_send` already redacts `blob_url` from event payloads (Phase 8 D-14). New Blob URLs flowing through logs/errors are PII-safe by construction.
- **L-07:** structlog contextvars whitelist allows `clip_id`, `request_id`, `session_hash` (Phase 8 PRIV-02). Phase 10 must NOT add Blob URLs as contextvars — they're per-call values, log them as kwargs only.
- **L-08:** Single Uvicorn worker (`--workers 1`); asyncpg pool max_size=10 (Phase 9 L-02). Phase 10's httpx client is also process-singleton.
- **L-09:** No SQLAlchemy ORM at runtime (REQUIREMENTS.md "Out of Scope"). New storage code is hand-written async.

### Vercel Blob client (D-01..04)
- **D-01:** **Raw httpx async wrapper** — NOT the `vercel_blob` Python SDK. Resolves the STATE.md "Pending Todo" about the bleeding-edge `AsyncBlobClient @0.5.8` by avoiding the SDK entirely. ~150 LOC of typed async wrapper over the Blob REST API covers our four touch points (PUT upload, signed-URL mint, DELETE cleanup, optional HEAD). Async-native fit with Phase 9's asyncpg / structlog stack.
- **D-02:** **Single module-level httpx.AsyncClient** initialized in FastAPI `lifespan()` startup hook (eager, fail-loud on missing `BLOB_READ_WRITE_TOKEN` when `STORAGE_BACKEND=blob` and not `OFFLINE_DEMO`). Closed in `lifespan()` shutdown. Mirrors Phase 9 D-16 asyncpg pool pattern.
- **D-03:** **Operations the wrapper exposes** (locked surface):
  - `async upload(prefix: str, key: str, body: bytes | AsyncIterator[bytes], *, content_type: str, access: Literal["public", "private"]) -> BlobObject` — returns `{ url, pathname, content_type, size }`
  - `async mint_signed_url(pathname: str, *, ttl_seconds: int = 900) -> str` — for `uploads/` reads (private)
  - `async delete(pathname: str) -> None` — for BLOB-08 cleanup
  - `async head(pathname: str) -> BlobObject | None` — health check / smoke test
- **D-04:** **Token discipline** — `BLOB_READ_WRITE_TOKEN` env var (Vercel-issued). Empty when `OFFLINE_DEMO=true`; loaded once via `python-dotenv` (Phase 8/9 pattern). Never logged. Token is the only auth signal — the wrapper does NOT issue client-upload tokens to the browser (L-02).

### Blob URL access policy (D-05..07)
- **D-05:** **Split access mode** — `uploads/` is **private**; `runs/` is **public**.
  - Private `uploads/`: every read (ffmpeg trim source, ffmpeg stitch source, future Phase 11 moderation classifier source) mints a fresh signed URL.
  - Public `runs/`: compiled segments are CDN-cacheable; frontend renders the absolute URL directly. No signed-URL refresh logic in `frontend/src/api.ts`.
- **D-06:** **Signed URL TTL = 900 seconds (15 minutes)** for `uploads/` reads. Far longer than any single trim or moderation call (each <2s typical). Short enough that a leaked URL rots quickly. Mint **fresh per call site** — no in-process URL caching across calls. Cost is one round-trip to Vercel Blob's signed-URL endpoint per ffmpeg invocation; acceptable.
- **D-07:** **Leak-decay rationale for split access:** Phase 11 will mark moderation-blocked clips and call BLOB-08 cleanup, which DELETEs the blob. Between block-decision and DELETE there is a window. Private + 15-min TTL bounds the window for `uploads/`. Public `runs/` is the post-moderation publish artifact — leaks here are bounded by `is_hidden` filtering at the DB layer (Phase 11/12 owns).

### ffmpeg + Blob integration (D-08..11)
- **D-08:** **`_sync_trim` (BLOB-03):** ffmpeg ingests Blob signed URLs directly via `ffmpeg.input(signed_url)`. Vercel Blob's signed URL is query-param-token format, so no `-headers` flag needed. The existing `-c copy` stream-copy + `-ss` / `-to` flags continue to work — ffmpeg issues HTTP Range requests automatically. **No source-clip download to local disk for trim.** Output still writes to a local temp .mp4 (atomic-rename pattern preserved), then uploads to `runs/` (public).
- **D-09:** **`_sync_stitch` (BLOB-04):** Single `tempfile.TemporaryDirectory()` context manager per `_sync_stitch` call. Inside: `asyncio.gather`-parallel download all N source clips via the httpx wrapper (using freshly-minted signed URLs), then invoke the existing libx264 normalize-and-concat filter graph with file-path inputs. Auto-cleanup on context exit. **No cluster-level cache or cross-recompile reuse** (deferred to v1.2 if the cost matters at scale).
- **D-10:** **Run-segment upload sequencing:** sequential — trim → write to local temp → upload to `runs/{run_id}.mp4` (public) → return absolute Blob URL → write into `segments.video_url`. Simpler than streaming through a pipe; the temp .mp4 is small (typically <few MB per run). Failure-fallback semantics in `trim_window` / `stitch_clips` async wrappers preserve "return-source-on-failure" pattern (returns the source signed URL on upload failure, which the frontend can still play).
- **D-11:** **Order in compile pipeline:** `_resolve_run_ids_to_stitch_refs` (compile.py:194) currently builds `path` keys pointing at local `/data/clips/...`. Post-Phase 10 those become signed Blob URLs minted at resolve-time. Stitch refs schema unchanged: `{path, start_offset_sec, end_offset_sec}` — `path` just holds an HTTPS URL instead of a filesystem path.

### Storage dispatcher shape (D-12..14)
- **D-12:** **Module split mirrors Phase 9 D-07.** New layout:
  - `backend/storage/__init__.py` — thin selector. Imports based on `config.STORAGE_BACKEND` + `OFFLINE_DEMO`.
  - `backend/storage/local.py` — lift-and-shift of the v1.0 local-FS code (the `CLIPS_DIR.write_bytes` path currently embedded in `db_sqlite.py:168` and `db_postgres.py:167`). Public functions: `save_clip_bytes`, `delete_clip`, `get_playable_url`.
  - `backend/storage/blob.py` — Vercel Blob implementation with **identical function signatures** to `local.py`. Implements via the D-01 httpx wrapper.
- **D-13:** **Selection happens once at module import**, mirroring Phase 9 D-08:
  ```python
  if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
      from .blob import *
  else:
      from .local import *
  ```
  No per-request branching. `OFFLINE_DEMO=true` hard-overrides to `local` (mirror Phase 9 D-11).
- **D-14:** **DB write/read sites refactor minimally.** `db_sqlite.py` and `db_postgres.py` currently hardcode `CLIPS_DIR / f"{clip_id}.{ext}"` (line 168 / 167). Phase 10 replaces those calls with `await storage.save_clip_bytes(clip_id, ext, contents) -> blob_url_or_local_path`, and the DB row stores the result in `clips.blob_url` (when blob) or in `clips.path` (when local; v1.0 column kept for `STORAGE_BACKEND=local` rollback path). Read paths return absolute URL via `storage.get_playable_url(row)` which inspects whichever column is populated.

### v1.0 cutover handling (D-15)
- **D-15:** **No backfill, no feed filter, no read-fallback.** At Phase 10 deploy, run the existing `POST /admin/reset` (token-guarded; CLAUDE.md confirms it wipes clips) to truncate the legacy clips/embeddings/clusters/segments rows. Demo dataset re-uploaded fresh via the UI (or a thin `backend/scripts/seed_demo_to_blob.py` that POSTs each `backend/seed/demo/*.mp4` to `/clips`). Zero migration code, zero dead `WHERE blob_url IS NOT NULL` predicate to carry forward. Justification: Newz has no production user data — anonymous-by-design — and the demo corpus is checked-in fixtures we control. Mirrors Phase 9 D-02 explicit-no-dual-write posture and is even simpler since there's no row-preserving requirement.

### `/media` mount + frontend URL handling (D-16..17)
- **D-16:** **`/media` StaticFiles mount is conditionally registered** at `app.py:151` based on `config.STORAGE_BACKEND`:
  ```python
  if config.STORAGE_BACKEND == "local" or config.OFFLINE_DEMO:
      app.mount("/media", StaticFiles(directory=str(config.DATA_DIR / "clips")), name="media")
  ```
  Default deploy (`STORAGE_BACKEND=blob`, `OFFLINE_DEMO=false`) leaves `/media` unmounted, satisfying BLOB-05. Rollback (`STORAGE_BACKEND=local`) re-enables it without code changes.
- **D-17:** **Frontend `api.ts` URL prefixing logic stays put.** Backend now returns absolute URLs for blob-backed clips (`https://*.vercel-storage.com/...`) and the existing `${API_BASE}${s.video_url}` concat logic is a no-op for absolute URLs (becomes `${API_BASE}https://...` only if backend returns relative — guarded by detecting `://` in the URL). Net result: zero frontend code change required for happy path. *(Open verification owed in research: confirm that `frontend/src/api.ts:29-31` doesn't double-prefix absolute URLs. If it does, add a one-line `s.video_url.startsWith('http')` guard.)*

### OFFLINE_DEMO + STORAGE_BACKEND interaction (D-18..19)
- **D-18:** **`OFFLINE_DEMO=true` hard-overrides STORAGE_BACKEND to local** regardless of env value, mirroring Phase 9 D-11. Logged once at startup: `storage_backend: forcing local (OFFLINE_DEMO=true)`. CI smoke test (DEMO-02, owned by Phase 13) sets `OFFLINE_DEMO=true` only — Phase 10 must guarantee that startup never opens a Blob HTTP connection under that flag.
- **D-19:** **Fail-loud on missing config:** when `STORAGE_BACKEND=blob` and `OFFLINE_DEMO=false`, missing `BLOB_READ_WRITE_TOKEN` raises at lifespan startup. Mirrors Phase 9's posture for missing `DATABASE_URL` — bad config should fail the deploy, not graceful-degrade.

### BLOB-08 cleanup hook contract (D-20)
- **D-20:** **Synchronous hook function shipped in Phase 10, called from Phase 11.** Signature: `async def cleanup_blocked_clip(clip_id: str) -> None`. Looks up `clips.path` / `clips.blob_url`, calls `storage.delete_clip(...)` (DELETEs the Blob object), no-ops if already deleted (idempotent). Phase 11 calls this immediately after writing `moderation_status='blocked'` to the row. **No background sweeper task in Phase 10** — the hook runs in the same task that owns the moderation decision. If Phase 11 wants to defer/batch deletes, that's Phase 11's planner choice.

### Test discipline (D-21..22)
- **D-21:** **Extend the Phase 9 D-10 test fixture** to parametrize `STORAGE_BACKEND` (`local`, `blob`) alongside `METADATA_BACKEND` (`sqlite`, `postgres`). Default CI matrix becomes 2x2 = 4 cells. Cells where `STORAGE_BACKEND=blob` use a recorded-tape (`pytest-vcr` or hand-rolled) httpx mock — DO NOT hit real Vercel Blob from CI. Cell `STORAGE_BACKEND=local + METADATA_BACKEND=sqlite` is the OFFLINE_DEMO firewalled path; must still pass.
- **D-22:** **Smoke test owed early in plan execution:** wave-0 manual deploy with `STORAGE_BACKEND=blob` + a test upload. Mirrors Phase 9 D-14 wave-0 smoke posture. Catches token-shape / URL-format / `vercel-storage.com` DNS issues before the integration tests are in their final shape.

### Claude's Discretion (locked-in defaults the planner can act on)
- **D-23:** New env vars in `backend/config.py`: `STORAGE_BACKEND` (default `local`), `BLOB_READ_WRITE_TOKEN` (default empty). Add to `.env.example` with comment block matching Phase 9's style.
- **D-24:** httpx wrapper retry posture: `tenacity` (already in requirements.txt) for transient 5xx with exponential backoff, max 3 attempts. 4xx and 401/403 fail-loud immediately.
- **D-25:** httpx wrapper module location: `backend/storage/blob_client.py` — keeps `blob.py` focused on the storage interface and isolates HTTP details. Internal to the storage package; never imported elsewhere.
- **D-26:** Run-segment upload `Content-Type` is always `video/mp4` (we control the encode); upload `Content-Type` for `uploads/` matches the inbound `UploadFile.content_type` (mp4 or webm via the existing iOS Safari MIME ladder).
- **D-27:** Pre-warm posture: NO Blob warm-up on startup. Vercel Blob is a CDN PUT — there is no analog to Marengo's cold-start. Skipping warm-up keeps `OFFLINE_DEMO=true` startup truly silent.
- **D-28:** Logging: every Blob operation logs one structured line at INFO with `op` (upload|delete|sign), `pathname`, `latency_ms`, `bytes` (for upload). Standard Phase 8 structlog kwargs style — no high-cardinality labels, no signed-URL token in the log line.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and acceptance criteria
- `.planning/ROADMAP.md` §"Phase 10: Vercel Blob Migration" — phase goal, depends-on (Phase 9), 6 success criteria
- `.planning/REQUIREMENTS.md` §"Object Storage — Vercel Blob Migration" (BLOB-01..08) — server-mediated upload, runs/ prefix, ffmpeg trim from signed URL, tempdir stitch, /media mount removal, STORAGE_BACKEND flag, redeploy survival, cleanup hook

### Project-level constraints (cross-phase)
- `.planning/PROJECT.md` §"Constraints" — anonymity load-bearing, single Uvicorn worker, OFFLINE_DEMO end-to-end
- `.planning/PROJECT.md` §"Out of Scope" — Vercel Blob locked over R2; direct browser PUT permanently rejected
- `.planning/STATE.md` §"Locked Decisions" — Vercel Blob, server-mediated only, STORAGE_BACKEND flag, OFFLINE_DEMO firewalled CI gate
- `.planning/STATE.md` §"Pending Todos" — "Run Vercel Blob AsyncBlobClient (vercel 0.5.8) spike before Phase 10 planning" (RESOLVED in this CONTEXT — D-01 sidesteps the SDK)
- `.planning/REQUIREMENTS.md` §"Out of Scope" — SQLAlchemy ORM rejected; pgvector rejected; direct browser → Blob upload rejected; R2 deferred

### Phase 8 inheritance (must not regress)
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-12 — middleware order (XFFStrip → RequestID → Metrics → CORS → routes); Phase 10 changes nothing
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-14 — Sentry before_send already scrubs `blob_url`. Phase 10 must NOT add Blob signed-URL tokens to log lines (D-28 enforces).
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-16 — graceful-degrade pattern (empty `SENTRY_DSN` → skip Sentry init). Phase 10 D-18 mirrors for `OFFLINE_DEMO=true` → skip Blob client init.
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-17 — Prometheus label policy. Phase 10 must not add Blob-pathname labels (high-cardinality); use `op` (upload|delete|sign) and `status_class` only if metrics get added.
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` PRIV-02 (D-08) — structlog contextvars whitelist. Phase 10 D-07 enforces: Blob URLs/tokens are kwargs, never contextvars.

### Phase 9 inheritance (must not regress)
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-07, D-08 — module-split dispatcher pattern (template for D-12, D-13)
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-10 — `METADATA_BACKEND` parametrize fixture; Phase 10 D-21 extends to `STORAGE_BACKEND`
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-11 — `OFFLINE_DEMO=true` hard-overrides backend selection (template for D-18)
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-14 — wave-0 smoke deploy posture (template for D-22)
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-16 — asyncpg pool init in `lifespan()` (template for D-02 httpx client init)
- `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py` lines 35-55 — confirms `clips.blob_url TEXT NULL` + `clips.is_hidden BOOLEAN NOT NULL DEFAULT FALSE` already exist; Phase 10 does no schema changes

### v1.0 architecture being replaced (read for migration scope)
- `backend/app.py:151` — `app.mount("/media", StaticFiles(directory=...))`. **Conditionally guard per D-16.**
- `backend/app.py:163-194` — `POST /clips` ingest route. `await db.insert_clip(file, lat, lng, ts, ...)` writes file via the storage path; refactor target.
- `backend/db_sqlite.py:16, 94, 168, 205, 375-379, 599, 677` — local-FS write/read/delete sites. **Lift to `backend/storage/local.py` per D-12.**
- `backend/db_postgres.py:32, 58-61, 145-150, 167, 199, 379-383, 612, 695` — same sites in the Postgres branch. Same lift-and-shift target.
- `backend/pipeline/stitch.py:30 (_sync_stitch), 112 (_sync_trim)` — ffmpeg call sites. **`_sync_trim` swaps `ref["path"]` for a signed Blob URL minted at `_resolve_run_ids_to_stitch_refs` time (D-08, D-11). `_sync_stitch` wraps in `tempfile.TemporaryDirectory()` + parallel download (D-09).**
- `backend/pipeline/compile.py:194-217 (_resolve_run_ids_to_stitch_refs), 312-353 (_stitch_segment_runs), 343 (output_path)` — orchestrator that builds stitch refs and writes run outputs. Output path becomes a tempfile; uploaded to `runs/{run_id}.mp4`; absolute URL returned to caller.
- `backend/pipeline/compile.py:425` — `/media/...` URL hardcoded; replace with absolute Blob URL post-upload.
- `backend/config.py:8 (DATA_DIR), 35 (ADMIN_TOKEN), 38-56 (Phase 8/9 env-var pattern)` — add `STORAGE_BACKEND` and `BLOB_READ_WRITE_TOKEN` here per D-23.
- `backend/Procfile`, `backend/railway.toml` — single `--workers 1`. Phase 10 changes neither.
- `backend/.env.example` — add `STORAGE_BACKEND=local` (default) and `BLOB_READ_WRITE_TOKEN=` (commented) per D-23.
- `backend/requirements.txt` — `tenacity` already present (D-24); no new pin needed beyond `httpx` (verify it's not already pulled in transitively by FastAPI).
- `backend/tests/conftest.py` (Phase 9 D-10 fixture) — extend with `STORAGE_BACKEND` parametrize per D-21.
- `frontend/src/api.ts:29-31` — relative-URL prefix logic. **Audit during research/planning per D-17 to confirm no double-prefix on absolute URLs.**
- `frontend/src/types.ts:7-9, 69` — `Segment.video_url` doc-string says "Path served by the backend StaticFiles mount, e.g. '/media/abc.mp4'". Update to reflect that absolute Blob URLs are now possible.
- `frontend/src/components/SegmentCard.test.tsx:46-48` — test fixtures use `/media/test.mp4`. Add a parallel fixture with absolute Blob URL.

### Forward-looking (do NOT implement now, but plan for)
- Phase 11 (MOD-01..08, MOD-10, PRIV-03) calls Phase 10's `cleanup_blocked_clip(clip_id)` hook (D-20) and the moderation classifier itself fetches signed URLs from `uploads/` for input video bytes. PRIV-03 requires GPS/session_uuid/timestamp stripped from the moderation API request — Phase 10's storage layer never carries those, so the constraint is trivially satisfied at the storage boundary.
- Phase 12 (REPORT-01..10) reads `clips.is_hidden` (Phase 9 D-05); Phase 10 storage layer does not gate on it — that's a DB query concern, not a storage concern.
- Phase 13 (OBS-05..09) wraps the new ffmpeg-from-Blob path in Logfire spans. Phase 10 must keep storage operations in clean async boundaries (no blocking I/O in the event loop) so Logfire's `span()` instrumentation works without contortions.
- Phase 13 (DEMO-02) firewalled CI smoke test — Phase 10's D-18 `OFFLINE_DEMO=true` skip is what that test asserts.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`POST /admin/reset`** (`backend/app.py:433`, token-guarded): wipes clips between demo runs. **D-15 leans on this directly** for the cutover step — no new wipe script needed.
- **`backend/db_sqlite.py:168` and `backend/db_postgres.py:167` (`path = CLIPS_DIR / f"{clip_id}.{ext}"; path.write_bytes(contents)`)**: identical local-FS write logic. Lift-and-shift to `backend/storage/local.py:save_clip_bytes()` preserves both branches.
- **Phase 9 D-07 module-split pattern** (`backend/db_sqlite.py` + `backend/db_postgres.py` + thin `backend/db.py` selector): exact template for `backend/storage/{local,blob}.py` + `backend/storage/__init__.py` selector.
- **Phase 9 D-10 conftest fixture** (parametrizes `METADATA_BACKEND`): extends to `STORAGE_BACKEND` for the 2x2 CI matrix.
- **Phase 9 `lifespan()` startup pattern** (asyncpg pool init, fail-loud on missing DATABASE_URL, OFFLINE_DEMO graceful-skip): exact template for httpx Blob client lifecycle (D-02, D-19).
- **`tenacity`** (already in `requirements.txt`): retry posture for transient 5xx (D-24).
- **`ffmpeg.input(url)` URL ingest** (ffmpeg-python's native HTTP support): no new ffmpeg flags needed for BLOB-03; signed URLs work as plain inputs.
- **`tempfile.TemporaryDirectory()` context manager** (Python stdlib): exact tool for BLOB-04 stitch download dir.

### Established Patterns
- **Empty-token-disables-endpoint** (Phase 8 `/metrics` and `/admin/reset`): Phase 10 mirrors with `BLOB_READ_WRITE_TOKEN` empty + `STORAGE_BACKEND=blob` + not `OFFLINE_DEMO` → fail-loud at lifespan (D-19).
- **OFFLINE_DEMO graceful-degrade** (Phase 8 D-16, Phase 9 D-11): Phase 10 D-18 mirrors — empty `BLOB_READ_WRITE_TOKEN` is fine when `OFFLINE_DEMO=true`; storage forces local mode.
- **Single module-level client** (asyncpg pool, twelvelabs SDK): Phase 10's `httpx.AsyncClient` lives at module level in `backend/storage/blob_client.py`, init in `lifespan()`.
- **Atomic-rename ffmpeg outputs** (`stitch.py:63-79`, `_sync_trim` lines 132-155): preserved unchanged. The temp .mp4 → atomic-rename → upload-to-Blob sequence (D-10) keeps the existing failure-fallback semantics intact.
- **`async def …` wrappers around `_sync_…` functions** (`stitch_clips`, `trim_window`): these stay in place. Phase 10 changes only what's inside the `_sync_…` invocation site (signed URL minted in the async wrapper, passed in `ref` dict to the sync function).
- **structlog `bind_contextvars` clip_id** (Phase 8 D-08, used at `app.py:191`): contextvars survive `asyncio.create_task` boundaries. Storage logs inherit `clip_id` automatically — no new contextvar bindings needed in Phase 10.

### Integration Points
- **`backend/storage/__init__.py` selector + `backend/storage/local.py` + `backend/storage/blob.py` + `backend/storage/blob_client.py`** (new): D-12, D-13, D-25.
- **`backend/db_sqlite.py:168` and `backend/db_postgres.py:167`**: replace `path.write_bytes(contents)` with `await storage.save_clip_bytes(clip_id, ext, contents)`. Returned URL/path goes into `clips.blob_url` (blob mode) or `clips.path` (local mode) per D-14.
- **`backend/db_sqlite.py:205` / `db_postgres.py:199` (the `f"/media/{filename}"` URL builder)**: replace with `storage.get_playable_url(row)` which returns absolute URL when `blob_url` is populated, `/media/...` otherwise.
- **`backend/app.py:151` (`/media` mount)**: wrap in `if config.STORAGE_BACKEND == "local" or config.OFFLINE_DEMO:` per D-16.
- **`backend/app.py` `lifespan()`** (Phase 9 already added asyncpg pool init): add httpx client init + close. Order: XFFStrip middleware → asyncpg pool → httpx Blob client → Marengo pre-warm → CLUSTERS rebuild → Neon keepalive → yield.
- **`backend/pipeline/compile.py:194-217 (_resolve_run_ids_to_stitch_refs)`**: when `STORAGE_BACKEND=blob`, replace `r.parent_path` with `await storage.mint_signed_url(parent_pathname, ttl_seconds=900)` per D-06, D-08, D-11.
- **`backend/pipeline/compile.py:343 (output_path)`**: change from `config.DATA_DIR / "clips" / f"{run_id}.mp4"` to a `tempfile.NamedTemporaryFile(suffix='.mp4')`. After trim succeeds, upload via `storage.upload(prefix='runs', ...)`. Return absolute Blob URL into the segment row (D-10).
- **`backend/pipeline/stitch.py:30 (_sync_stitch)`**: wrap caller-side in `tempfile.TemporaryDirectory()` + parallel download per D-09. The `_sync_stitch` body itself can stay path-based — only the call site (in `compile.py`) changes.
- **`backend/config.py`**: new env vars `STORAGE_BACKEND`, `BLOB_READ_WRITE_TOKEN` (D-23). Phase 8/9 comment-block style.
- **`backend/.env.example`**: document the new env vars.
- **`backend/tests/conftest.py`** (Phase 9 D-10 fixture): extend with `STORAGE_BACKEND` parametrize (D-21).
- **`frontend/src/api.ts:29-31` and `frontend/src/types.ts:7-9, 69`**: audit + likely-no-change per D-17. Update doc-strings to reflect absolute URL possibility.
- **`backend/scripts/seed_demo_to_blob.py`** (new, optional): minimal script to POST `backend/seed/demo/*.mp4` through `/clips` for live-demo re-seeding after `POST /admin/reset` (D-15). Planner can decide whether this ships in Phase 10 or stays as a doc-snippet.

</code_context>

<specifics>
## Specific Ideas

- **Avoiding the `vercel_blob` SDK is the load-bearing simplification of this phase.** The STATE.md "bleeding-edge AsyncBlobClient @0.5.8" concern is real — pinning a pre-1.0 async SDK in our requirements.txt is a future-source-of-pain. A 150-LOC httpx wrapper is auditable, type-safe, version-stable, and fits the existing async stack 1:1.
- **Split access (private uploads/, public runs/) is the highest-leverage decision in the file.** It separates the "intermediate" surface (raw user clips that should rot quickly under leak conditions) from the "publish" surface (compiled segments that need CDN reach). Both BLOB-08 (cleanup of moderation-blocked clips) and frontend caching benefit.
- **`POST /admin/reset` already does the cutover work.** That this endpoint exists means D-15 is essentially zero new code. Don't reinvent.
- **The two-module storage split (D-12) is the regression guard that lets `STORAGE_BACKEND=local` keep working forever.** Phase 9 made the same call for `db_sqlite.py` (D-09: keep indefinitely). Phase 10 mirrors. OFFLINE_DEMO survivability depends on this.
- **15-min signed URL TTL (D-06) is intentionally generous.** Tighter TTLs (e.g., 60s) would force re-mint mid-trim if ffmpeg cold-starts on Railway, and the leak-decay benefit is marginal because the cleanup hook (BLOB-08) is the real defense against post-block leaks. 15min is a strict upper bound on cleanup latency.
- **Sequential trim → upload (D-10) over streaming through a pipe.** The streaming alternative saves a few hundred KB of disk and one syscall, but breaks the existing atomic-rename pattern in `_sync_trim` and complicates the failure-fallback contract (currently returns `ref['path']` — what does it return when the local temp doesn't exist?). At our compile rate (~handful of stitches/min during demo), the disk cost is irrelevant.
- **Tempdir-per-call on stitch (D-09) over cluster-level reuse.** Reuse would speed up recompiles but would require eviction-on-cluster-update plumbing, and `montage-not-updating` (deferred from v1.0 retro) means cluster mutation paths are already fragile. Don't add cache-coherence concerns mid-migration.
- **2x2 test matrix (D-21) costs CI time but is the correctness guard for the migration window.** Phase 9 D-10 already paid for the `METADATA_BACKEND` axis; adding `STORAGE_BACKEND` doubles the matrix but most cells are fast (sqlite + local FS).

</specifics>

<deferred>
## Deferred Ideas

- **Cluster-level tempdir reuse / cross-recompile source-clip cache** — v1.2+. Trade-off table: ~30% faster recompile vs. cache-coherence complexity; not worth it at v1.1 traffic.
- **Stream trim output directly to Blob (no local temp)** — Skip-file optimization considered and rejected (breaks atomic-rename / failure-fallback). Revisit if disk pressure on Railway becomes material.
- **Cluster-aware Blob region pinning** — v1.2+. All Blob writes use the default region for v1.1. Hyperlocal traffic might benefit from edge pinning later.
- **Blob CDN metrics (bytes-served, cache-hit-rate)** — v1.2+. Vercel exposes these in the dashboard; no need to surface in /metrics for v1.1.
- **`backend/storage/local.py` deletion / consolidation** — v1.2+ (mirrors Phase 9 D-09 `db_sqlite.py` posture). Keep indefinitely through v1.1 for OFFLINE_DEMO + rollback.
- **Multipart upload for large clips (>100 MiB)** — Out of scope. Existing `MAX_UPLOAD_BYTES = 100 MiB` (`app.py:159`) caps payload size; single-PUT works for everything under that cap.
- **Direct browser → Blob upload via Vercel client tokens** — Permanently rejected (REQUIREMENTS.md "Out of Scope"; skips moderation gate).
- **Cloudflare R2** — v1.2+ if egress becomes material (REQUIREMENTS.md).
- **pgvector / Pinecone for centroid storage** — v1.2+ (REQUIREMENTS.md; out of scope for storage phase too — orthogonal concern).
- **Pre-warm Blob on startup** — Rejected (D-27). No analog to Marengo cold-start; warm-up adds an OFFLINE_DEMO violation surface.
- **Background sweeper for orphan blob cleanup** — Out of scope. BLOB-08's synchronous hook (D-20) is sufficient. A sweeper might surface in v1.2 if an audit shows orphan blobs accumulate.
- **Cluster-aware retry on signed-URL expiry mid-ffmpeg** — Deferred. 15-min TTL on signed URLs makes mid-trim expiry virtually impossible; if we ever shorten the TTL, plan a retry shim then.

### Verifications Owed (research / planning surface)
- **D-17 frontend prefix audit** — Confirm `frontend/src/api.ts:29-31` does NOT double-prefix absolute URLs. Likely-OK (the existing template literal `${API_BASE}${s.video_url}` becomes `http://localhost:8000https://blob.../...` if it doesn't guard, which would 404 visibly). One-line guard if needed.
- **Wave-0 smoke deploy** (D-22) — `STORAGE_BACKEND=blob` + `BLOB_READ_WRITE_TOKEN=...` on Railway, single test upload via `/clips`, confirm Blob console shows the object. Flush any token-format / DNS / signed-URL-minting surprises before the integration tests are wired.
- **Confirm `httpx` is already in requirements** — FastAPI may pull it in transitively. If not, pin it explicitly (D-25 implies its presence).
- **Confirm `frontend/src/types.ts` doc-string update is the only frontend doc churn** (D-17).

</deferred>

---

*Phase: 10-vercel-blob-migration*
*Context gathered: 2026-04-29*
