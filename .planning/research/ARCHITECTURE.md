# Architecture Research — Newz v1.1 Public-Launch-Ready Backbone

**Domain:** Subsequent-milestone production hardening of an existing FastAPI monolith (anonymous crowdsourced video → AI clustering → multi-agent compile → SSE feed)
**Researched:** 2026-04-27
**Confidence:** HIGH for v1.0-integration shape (read directly from `backend/`); MEDIUM for vendor-specific tuning (Vercel Blob, asyncpg+pooler, moderation vendor) where final numbers must be validated against the live deployment.

This is **not** a greenfield architecture document. v1.0 is shipped. Every decision below is framed as: "what changes inside the existing monolith, where in the existing files, in what build order."

---

## 1. v1.0 Architecture — Read From The Code

Pulled from `backend/app.py`, `backend/db.py`, `backend/pipeline/{run,embed,cluster,compile,stitch,runs,caption_pipeline}.py`, `backend/events.py`, `frontend/src/api.ts`.

```
                            ┌──────────────────────────────────────────────────────────────┐
                            │                    Browser (iOS Safari, PWA)                  │
                            │        recorder.tsx → api.postClip → multipart POST           │
                            └────────────────────────┬─────────────────────────────────────┘
                                                     │ multipart (file + lat/lng/ts)
                                                     │ X-Session-Id header
                            ┌────────────────────────▼─────────────────────────────────────┐
                            │                FastAPI app (single Uvicorn process)           │
                            │ app.py                                                        │
                            │  POST /clips     → db.insert_clip → write file to /data/clips │
                            │                  → events.broadcast({type: clip_added})       │
                            │                  → asyncio.create_task(run_pipeline(clip_id)) │
                            │                  → 202 IngestResponse                         │
                            │  GET  /feed      → db.fetch_recent_segments + haversine sort  │
                            │  GET  /events    → SSE (sse_starlette)                        │
                            │  GET  /media/*   → StaticFiles(/data/clips)                   │
                            │  POST /admin/*   → token-guarded reset                        │
                            └────────────────────────┬─────────────────────────────────────┘
                                                     │ in-process asyncio.create_task
                            ┌────────────────────────▼─────────────────────────────────────┐
                            │                pipeline/run.py — run_pipeline                 │
                            │   embed_worker → cluster_worker → _should_compile gate        │
                            │                                       └→ compile_segment      │
                            └─────┬───────────────┬───────────────┬─────────────────┬──────┘
                                  │               │               │                 │
                  ┌───────────────▼─┐    ┌────────▼────────┐  ┌───▼───────────┐  ┌──▼─────────────┐
                  │ pipeline/embed  │    │ pipeline/cluster│  │ pipeline/     │  │ pipeline/stitch│
                  │ Marengo 3.0     │    │ NumPy cosine    │  │ compile.py    │  │ ffmpeg libx264 │
                  │ run_in_executor │    │ + GPS + time    │  │ Claude SDK    │  │ ultrafast      │
                  │ (sync SDK)      │    │ asyncio.Lock    │  │ + Gemini      │  │ -c copy trim   │
                  └───────┬─────────┘    └────────┬────────┘  └───────┬───────┘  └────────┬───────┘
                          │                       │                   │                   │
                          │ store_embedding       │ upsert_cluster    │ insert_segment    │ writes
                          │ insert_child_clip     │ assign_clip       │ set_compile_in_   │ /data/
                          ▼                       ▼ CLUSTERS dict     ▼ flight CAS        ▼ clips/{run}.mp4
                ┌─────────────────────────────────────────────────────────────────────┐
                │  SQLite (aiosqlite, WAL) at /data/newz.db                            │
                │  tables: clips, clip_embeddings (BLOB), clusters (BLOB centroid),    │
                │          segments (UNIQUE cluster_id)                                 │
                │  Railway persistent volume — same volume as /data/clips (raw mp4)    │
                └─────────────────────────────────────────────────────────────────────┘
                                                     │
                                                     │ events.broadcast (cluster_assigned,
                                                     │  pipeline_progress, segment_published)
                            ┌────────────────────────▼─────────────────────────────────────┐
                            │  events.py — in-memory _subscribers list of asyncio.Queues   │
                            │  GET /events SSE fan-out (drops on QueueFull)                 │
                            └─────────────────────────────────────────────────────────────┘
```

### Key facts the v1.1 work has to respect

| Fact | Source | Why it matters |
|------|--------|----------------|
| `embed_worker` returns `(parent_clip_id, parent_vec)` only — children are persisted but cluster on the parent | `pipeline/embed.py:137-188`, `pipeline/run.py:42` | Moderation gate must operate on the **parent upload as a whole**, not per-child slice. |
| `cluster_worker` holds `_LOCK` across score-and-mutate and reads `CLUSTERS` dict | `pipeline/cluster.py:69, 136-195` | Calibration is anchored to threshold 0.70 / floor 0.85 / 50m. Migration must not change clustering math; only the storage layer changes. |
| `CLUSTERS` is rebuilt from sqlite on startup before pre-warm fires | `app.py:67-77`, `pipeline/cluster.py:227-242` | `rebuild_cache()` is the single startup hook to swap when Postgres lands. |
| `compile_segment` writes per-run `.mp4` files to `data/clips/{run_id}.mp4` and serves them via `StaticFiles("/media")` | `pipeline/compile.py:343, 349`, `app.py:93`, `db.py:346-353` | Vercel Blob migration touches **both** the input path (parent recordings) and the output path (compiled run mp4s). Two flows, not one. |
| ffmpeg ingests `ref["path"]` as a local filesystem path in `stitch._sync_stitch` and `_sync_trim` | `pipeline/stitch.py:52, 140` | If clips live in Vercel Blob, ffmpeg either streams from signed URL (`ffmpeg.input(signed_url)`) or downloads to local tmp first. |
| `caption_pipeline.generate_caption` ALSO calls `stitch_clips` to build a Gemini-bound composite | `pipeline/caption_pipeline.py:351`, `pipeline/compile.py:191` | Don't forget this second ffmpeg call site when migrating Blob inputs. |
| SSE `events.py` is an in-memory subscriber list with `asyncio.Queue(maxsize=64)` | `events.py:7-35` | Already drops on `QueueFull` — fine for one Uvicorn worker, but **forecloses horizontal scale** unless replaced (out of scope for v1.1; flag for v1.2). |
| `db.set_compile_in_flight` is a CAS on `clusters.compile_in_flight` with TTL | `db.py:383-408`, `pipeline/run.py:31` | This becomes a `SELECT ... FOR UPDATE SKIP LOCKED` or `UPDATE ... WHERE` against Postgres — semantics translate cleanly. |

---

## 2. Postgres Migration Architecture

### 2.1 Driver + pool

**Recommendation:** keep `aiosqlite` API surface where possible, swap to **`asyncpg` directly** (no SQLAlchemy / no ORM). The v1.0 code is hand-written async SQL — adding an ORM is a much bigger refactor than the migration itself, and `asyncpg` has its own pool that outperforms `psycopg3-async + PgBouncer transaction mode`.

**Why not SQLAlchemy:** every helper in `db.py` is hand-written (`reset_all`, `delete_recent_clips` cascade, `count_distinct_parents_in_cluster`, `set_compile_in_flight` CAS, BLOB embeddings round-tripped via `np.frombuffer`). An ORM would force re-modeling all of it for marginal gain at this codebase size (~710 lines, 25 functions).

**Pool sizing (Neon Free / Pro):** asyncpg pool with `min_size=2`, `max_size=10` per Uvicorn worker. Newz is single-worker-on-Railway today, so a single pool is sufficient. Neon's connection limit on Free tier is ~100 concurrent and Pro raises substantially, so 10 is comfortably under.

**Pool sizing (Supabase):** if Supabase is chosen, use **session mode (port 5432) directly to Postgres** with asyncpg's own pool, OR use Supavisor on port 6543 with `statement_cache_size=0` set on asyncpg. Supabase's PgBouncer-in-transaction-mode + asyncpg prepared-statement collision is a known pain point — asyncpg silently caches prepared statements per-connection, which breaks when transaction-pooler connections get reused across statements. ([asyncpg ↔ Supabase pooler issue](https://github.com/supabase/supabase/issues/39227); [Supabase pooling and asyncpg](https://medium.com/@patrickduch93/supabase-pooling-and-asyncpg-dont-mix-here-s-the-real-fix-44f700b05249))

**When PgBouncer becomes necessary:** not at v1.1 launch scale. Newz has one Uvicorn worker, no horizontal replicas. asyncpg's built-in pool is enough until the pipeline goes multi-worker. **Flag for v1.2** if/when scaling out.

**Concrete recommendation:** **Neon over Supabase** for v1.1, because (a) we don't need Supabase's auth/storage/realtime — we already have all of that via session-UUID + Vercel Blob + SSE; (b) Neon's serverless-driver pattern fits asyncpg cleanly with no pooler-quirk surprises; (c) Neon has a simpler permissions model and branching for staging/prod separation.

### 2.2 Where the pool lives

Add to `app.py` lifespan, before `db.init()`:

```python
# backend/db.py (new module-level)
_POOL: asyncpg.Pool | None = None

async def init() -> None:
    global _POOL
    _POOL = await asyncpg.create_pool(
        dsn=config.DATABASE_URL,
        min_size=2, max_size=10,
        command_timeout=30,
        # Supabase-only: statement_cache_size=0 if using transaction pooler
    )
    async with _POOL.acquire() as conn:
        await conn.execute(SCHEMA_SQL)  # idempotent; same shape

@asynccontextmanager
async def conn():
    async with _POOL.acquire() as c:
        yield c
```

Every `aiosqlite.connect(DB_PATH)` call site in `db.py` becomes `async with conn() as c:`. That's the **bulk of the migration diff** — mechanical, repetitive, but contained to one file.

### 2.3 CLUSTERS rebuild — keep in-memory

**Decision: keep the in-memory `CLUSTERS` dict, drive it from Postgres.**

Reasoning:
- `cluster_worker`'s critical section iterates `CLUSTERS.values()` doing NumPy dot products — this is the **hot path on every clip ingest**. A Postgres round trip per clip just to fetch all centroids is strictly worse than the current design.
- pgvector would let us push the `argmax(cosine)` into the DB, but pgvector's HNSW index isn't worth setting up for <10K centroids — exhaustive scan in NumPy with 512-d unit vectors is microseconds. Only revisit if cluster count grows past ~10K.
- Restart cost is unchanged: `rebuild_cache()` runs once at lifespan startup, just hits Postgres instead of sqlite. The `db.get_all_clusters()` query is two `SELECT`s — runs in tens of milliseconds against Postgres just like sqlite.

**No change to `pipeline/cluster.py`** — `rebuild_cache()` already calls `db.get_all_clusters()`, which now returns rows from Postgres instead of sqlite. The asyncio.Lock-guarded critical section stays identical.

**Centroid storage:** sqlite stores centroid as `BLOB` (`np.float32.tobytes()`). Postgres equivalent is `BYTEA` (same bytes round-trip). **Do not** convert to pgvector at v1.1 — that's a calibration risk for a benefit we don't need. Keep BYTEA, parse to NumPy in Python, identical to today.

### 2.4 Schema design — keep, don't refactor

The v1.0 schema has been calibrated against (`db.py:18-63` plus the migration ALTERs). Refactoring during a storage migration multiplies risk. **Keep current shape exactly:** `clips`, `clip_embeddings`, `clusters`, `segments` — same columns, same FK relationships, same UNIQUE index on `segments.cluster_id`.

Two minor type cleanups Postgres makes available (apply only if cheap):
- `created_at REAL` → `TIMESTAMPTZ` with `EXTRACT(EPOCH FROM ...)` for read compat. Optional; not load-bearing.
- `INTEGER NOT NULL DEFAULT 0` for `compile_in_flight` → `BOOLEAN`. Trivial, but means audit every read site (`db.py:419-426`).

**Do these in a follow-up post-migration commit, not in the migration itself.** The hard rule: migration = swap driver, not redesign.

**New columns added in v1.1 (not refactors):**

| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `clips` | `moderation_status` | TEXT NOT NULL DEFAULT 'pending' | one of: `pending`, `passed`, `blocked`, `errored` |
| `clips` | `moderation_reason` | TEXT NULL | classifier label when blocked |
| `clips` | `moderation_score` | REAL NULL | classifier confidence 0..1 |
| `clips` | `moderation_decided_at` | TIMESTAMPTZ NULL | observability + retention |
| `clips` | `blob_url` | TEXT NULL | Vercel Blob URL (replaces `path` once Blob ships) |
| `segments` | `is_hidden` | BOOLEAN NOT NULL DEFAULT FALSE | reactive-report admin action |
| `segments` | `hidden_reason` | TEXT NULL | reason captured at hide time |
| **new** `reports` | id, segment_id, session_id, reason, status, created_at, decided_at | report flow |

### 2.5 Cutover

**Decision: no dual-write window. Do a one-shot dump + load during a short demo window, gated behind `DATABASE_URL`.**

Rationale: there is no production traffic on Newz today. The "user count" is the team plus demo viewers. Dual-write is engineering cost solving a problem we don't have. The much safer move is:

1. Run Postgres alongside sqlite locally; verify schema + every helper round-trips.
2. Write a one-shot `scripts/sqlite_to_postgres.py`: read all rows from `data/newz.db`, write to Postgres, with a per-table count assertion at the end.
3. Cut `DATABASE_URL` env var on Railway, redeploy. Old sqlite remains on the volume as a recovery snapshot.
4. Keep the Railway volume + sqlite file untouched for one week; if anything breaks, revert and re-run dump.

**What goes wrong without dual-write:** the only real risk is row loss during the dump-load window. If we run the dump while the server is paused (admin/reset, no incoming traffic), this is zero risk. We pick a deploy window with no demo activity.

**`OFFLINE_DEMO=true` keeps working** through migration because it doesn't touch DB writes for embeddings/captions — just for cluster/segment row inserts. Verify this end-to-end on a staging Postgres before cutting prod.

### 2.6 What lives WHERE in the code

| File | Modified or New | Change |
|------|------|--------|
| `backend/db.py` | Modified (heavy) | Replace every `aiosqlite.connect(DB_PATH)` with `async with conn() as c`; replace `BLOB` reads (`np.frombuffer(row[0], dtype=np.float32)`) with `BYTEA` (same code, asyncpg returns `bytes`); replace `INSERT OR REPLACE` with `INSERT ... ON CONFLICT DO UPDATE` (already used for clusters/segments — extend to `clip_embeddings`). |
| `backend/db.py` | Modified | `init()`: open asyncpg pool, run `SCHEMA_SQL` (PostgreSQL dialect — minimal diffs, mostly `BLOB` → `BYTEA`, `REAL` → `DOUBLE PRECISION`). |
| `backend/config.py` | Modified | Add `DATABASE_URL` env var. |
| `backend/scripts/sqlite_to_postgres.py` | New | One-shot dump+load utility. |
| `backend/pipeline/cluster.py` | Unchanged | `rebuild_cache()` already abstracts the source. |
| `backend/app.py` lifespan | Unchanged in shape | `db.init()` → `cluster.rebuild_cache()` → seed → pre-warm sequence stays identical. |
| `backend/requirements.txt` | Modified | Add `asyncpg`, remove (or keep for migration script) `aiosqlite`. |

---

## 3. Vercel Blob Storage Architecture

### 3.1 Two distinct flows

The v1.0 code stores **both** the user-uploaded recordings (`/data/clips/{clip_id}.{ext}`) and the compiled per-run output (`/data/clips/{run_id}.mp4`) on the same Railway volume. v1.1 must move both to Blob, but they have different uploaders and different lifecycle.

```
   ┌──────────────────────────────┐         ┌──────────────────────────────┐
   │  USER RECORDINGS             │         │  COMPILED RUN OUTPUT          │
   │  written by: insert_clip     │         │  written by: stitch._sync_*   │
   │  served as: /media/{clip}.mp4│         │  served as: /media/{run}.mp4  │
   │  read by: ffmpeg stitch+trim │         │  read by: browser <video>     │
   │           Gemini composite   │         │                                │
   └──────────────────────────────┘         └──────────────────────────────┘
            │                                       │
            ▼                                       ▼
   ┌──────────────────────────────────────────────────────────┐
   │            Vercel Blob (single bucket, two prefixes)      │
   │  uploads/{clip_id}.{ext}    runs/{run_id}.mp4             │
   └──────────────────────────────────────────────────────────┘
```

### 3.2 Upload path: client → FastAPI → Blob (NOT direct PUT)

**Decision: server-mediated upload. Client posts to FastAPI as today; FastAPI pipes to Blob.**

Rationale, ordered by weight:

1. **Moderation requires server custody.** The moderation gate (Section 4) runs immediately after upload on the server. If the client PUTs to Blob directly, we get a webhook eventually but the clip is **already publicly addressable by URL** for a window before moderation completes. That's exactly the pre-publish gate the milestone is designed to prevent.
2. **Validation we already do.** `app.py:113-121` enforces MIME prefix allowlist + 100 MiB cap on the request before we touch storage. Direct PUT loses both — Vercel Blob doesn't validate MIME or per-app size at the storage layer beyond global account limits.
3. **Anonymity preserved.** Direct PUT requires either (a) a token-vending endpoint anyway (so the latency saving is one round-trip, not free), or (b) a public-write bucket policy (catastrophic).
4. **Blob bandwidth: Vercel charges egress, not ingress, so server-mediated upload doesn't cost more in bandwidth than direct PUT — only adds CPU + RAM for the proxy stage.** ([Vercel Blob client-side limits](https://vercel.com/docs/vercel-blob/client-upload))

The latency cost is one extra hop — Railway → Vercel Blob — and clips are 10-30 MiB typical. On Railway's network this is sub-second. Acceptable.

**Code shape inside `app.py:ingest_clip`:**

```python
contents = await file.read()  # already in v1.0
if len(contents) > MAX_UPLOAD_BYTES: raise HTTPException(413, ...)

# v1.1: replace `path.write_bytes(contents)` with Blob put
blob_url = await blob.put(
    pathname=f"uploads/{clip_id}.{ext}",
    body=contents,
    options={"access": "public", "addRandomSuffix": False},
)
clip_id = await db.insert_clip_v2(blob_url=blob_url, ...)
```

**Vercel Blob from Python:** Vercel publishes a TypeScript SDK; from Python use `httpx.put(blob_api_url, headers={"authorization": f"Bearer {BLOB_RW_TOKEN}"}, content=contents)`. There's a small `vercel-blob-py` community wrapper but the raw HTTP API is stable enough that direct httpx is fine.

**Multipart for large clips:** Vercel recommends multipart for >100 MiB. Newz's 100 MiB hard cap (`app.py:101`) sits exactly at that boundary. Keep the cap; don't bother with multipart at v1.1.

### 3.3 ffmpeg path: signed URL OR local download? Pick by call site.

**Two ffmpeg call sites:** `stitch._sync_stitch` (concat for caption composite, called from `caption_pipeline`) and `stitch._sync_trim` (per-run output). Both currently take `ref["path"]` as a local filesystem path (`pipeline/stitch.py:52, 140`).

ffmpeg can read from HTTPS URLs natively — `ffmpeg -i "https://..."` works because ffmpeg has an HTTP protocol handler. No signed-URL rewriting needed for HTTP read.

**Recommendation: signed URL streaming for `_sync_trim`, local-tmp download for `_sync_stitch` caption composite.**

Why split:
- `_sync_trim` is `-c copy` stream-copy. ffmpeg reads only the bytes inside the trim window (it seeks via HTTP Range). Streaming from Vercel Blob CDN is **strictly faster** than full-file download because we skip the bytes outside the trim window. ([ffmpeg HTTP protocol + Range](https://ffmpeg.org/ffmpeg-protocols.html); [S3 streaming for ffmpeg](https://copyprogramming.com/howto/how-to-read-remote-video-on-amazon-s3-using-ffmpeg))
- `_sync_stitch` does normalize-and-concat with libx264 ultrafast re-encode. It re-reads the full source repeatedly through the filter graph. Many round-trips against a remote URL is worse than one download to local tmp. Download to `/tmp/{clip_id}.{ext}`, run ffmpeg, delete.
- Caption composite is also short-lived and short-input (3 children × 3s each). Tmp space is trivial.

**The blob URL passed into ffmpeg can be the public `*.public.blob.vercel-storage.com` URL** as long as the bucket is configured public-read with token-required write. That keeps ffmpeg HTTP simple — no signed-URL refresh logic needed.

**Concrete change in `pipeline/compile.py:_resolve_run_ids_to_stitch_refs`:** the `ref["path"]` field becomes a Vercel Blob URL. `stitch._sync_trim` uses it directly via `ffmpeg.input(blob_url, ss=..., to=...)`. **One-line change** at the input-construction site — no other stitch logic moves.

**The `stitch_clips` fallback path** (`pipeline/stitch.py:101, 109`) currently returns `clip_refs[0]["path"]` on failure — that string is now a Blob URL, which is what we want anyway since the frontend will then play directly from Blob. No change needed.

### 3.4 Output path: stitch writes back to Blob

`_sync_trim` writes to `output_path = data/clips/{run_id}.mp4` (`pipeline/compile.py:343`). Two options:

**Option A — write locally then upload.** Run ffmpeg to local tmp, then `blob.put("runs/{run_id}.mp4", body=open(tmp,"rb").read())`, return the Blob URL. Atomic-rename safety (`os.replace`) loses meaning but Vercel Blob writes are atomic on completion, so reads either get the old object or the new — same property.

**Option B — pipe ffmpeg stdout to Blob.** ffmpeg can `-f mp4 -movflags +faststart -` to stdout, but `+faststart` requires the moov atom at the front, which means ffmpeg needs to seek backward in the output — incompatible with streaming pipe. Forget B.

**Decision: Option A.** Stitch to local tmp, upload to Blob, delete local tmp. The `os.replace` atomic rename in v1.0 was load-bearing for "browser already streaming the previous compile keeps reading clean bytes" — Vercel Blob writes-by-pathname are atomic from the reader's perspective (the URL flips from old object to new), so we preserve the property without the rename gymnastics.

**Code shape:**

```python
# pipeline/compile.py:_trim_one (modified)
local_tmp = f"/tmp/{run_id}.mp4"
result = await trim_window(ref, local_tmp)  # writes to /tmp
if result == local_tmp and Path(local_tmp).exists():
    blob_url = await blob_put_async(f"runs/{run_id}.mp4", local_tmp)
    Path(local_tmp).unlink(missing_ok=True)
    return run_id, blob_url
```

`StaticFiles("/media")` in `app.py:93` is **deleted** in v1.1 — segments now reference absolute Blob URLs in `db.fetch_recent_segments`, so the frontend gets `https://...blob.vercel-storage.com/runs/...mp4` directly with no rewriting. This simplifies `frontend/src/api.ts:29-32` (no more `${API_BASE}${s.video_url}` prefix).

### 3.5 Cleanup / retention

The v1.0 admin reset deletes both rows and files. With Blob, deletion has cost (egress isn't billed but storage is) and timing matters because of caching.

**Retention policy (recommended, not yet in PROJECT.md):**
- **Raw recordings (`uploads/{clip_id}.*`):** delete when the parent clip row is deleted, OR after 30 days unconditionally if not referenced by any segment. Background sweeper job (cron-style, `asyncio.create_task` on a daily timer) — out of scope for v1.1 if we don't ship the report flow's "delete from disk" action. Otherwise **mandatory** for the report flow's hard-delete path.
- **Compiled run outputs (`runs/{run_id}.mp4`):** delete on `clusters` row deletion, OR when a re-compile produces a new run set (orphaned run files from a prior compile).

**Implementation:** add `db.delete_recent_clips` calls a `blob.delete(blob_url)` for each path returned in `paths_to_delete`. The existing `_delete_files` helper in `app.py:343-353` becomes `_delete_blobs(urls)`.

**Storage cost forecast at launch:** assuming 10K clips × 20 MiB avg = 200 GiB. Vercel Blob Pro tier is $0.15/GiB/month for storage = ~$30/mo storage. Egress is the bigger lever — every feed view streams ~2 MiB of compiled segment. Ten thousand monthly views × 2 MiB = 20 GiB egress, well within free egress on Pro.

### 3.6 What lives WHERE in the code

| File | Modified or New | Change |
|------|------|--------|
| `backend/blob.py` | New | Thin async wrapper around Vercel Blob HTTP API: `put`, `delete`, `head`. |
| `backend/config.py` | Modified | `BLOB_RW_TOKEN`, `BLOB_PUBLIC_URL_BASE`. |
| `backend/app.py:ingest_clip` | Modified | Replace `path.write_bytes(contents)` with `blob.put`; persist `blob_url` instead of `path`. |
| `backend/db.py:insert_clip` | Modified | Sig change: takes `blob_url` not file. |
| `backend/db.py:fetch_recent_*` | Modified | Build URLs from `blob_url`, drop `/media` rewriting. |
| `backend/pipeline/embed.py:embed_worker` | Modified | Read clip bytes from Blob into `/tmp/{clip_id}.{ext}`, pass to `_sync_embed`. Twelve Labs SDK takes a file handle, can't take a URL — local tmp required for embed. |
| `backend/pipeline/stitch.py:_sync_trim` | Modified (1 line) | `ffmpeg.input(ref["path"], ...)` — `ref["path"]` is now a Blob URL; ffmpeg HTTP handler reads it directly. |
| `backend/pipeline/stitch.py:_sync_stitch` | Modified | Pre-download stitch refs to local tmp, then run ffmpeg, then cleanup. |
| `backend/pipeline/compile.py:_trim_one` | Modified | After local stitch, upload to Blob, return Blob URL. |
| `backend/pipeline/caption_pipeline.py:generate_caption` | Modified | Pre-download child clips to tmp before `stitch_clips`. |
| `backend/app.py` (lifespan + middleware) | Modified | Remove `app.mount("/media", StaticFiles(...))`. |
| `frontend/src/api.ts:29-32` | Modified | Drop `${API_BASE}` prefix when `video_url` is already absolute. |

---

## 4. Moderation Gate Architecture

### 4.1 Pipeline slot — parallel with embed, gate before cluster

The required code shape from the question is correct as stated. Concretely, modify `backend/pipeline/run.py:run_pipeline`:

```python
# CURRENT (v1.0)
parent_clip_id, parent_vec = await embed_worker(clip_id)
cluster_id = await cluster_worker(parent_clip_id, parent_vec)

# v1.1
embed_task = asyncio.create_task(embed_worker(clip_id))
mod_task   = asyncio.create_task(moderate_clip(clip_id))
embed_result, mod_result = await asyncio.gather(
    embed_task, mod_task, return_exceptions=True,
)

if isinstance(mod_result, ModerationDecision) and not mod_result.passed:
    await db.mark_clip_blocked(clip_id, mod_result.label, mod_result.score)
    await events.broadcast({"type": "clip_blocked", "clip_id": clip_id})
    return  # do NOT cluster, do NOT compile

if isinstance(embed_result, Exception):
    raise embed_result
parent_clip_id, parent_vec = embed_result
cluster_id = await cluster_worker(parent_clip_id, parent_vec)
...
```

**Why parallel works:** Marengo embed is the dominant latency stage (3-15s). Moderation classifiers from Hive / Sightengine / Rekognition typically return in 1-5s for short clips. Run them concurrently and we pay max(embed, moderation) ≈ embed. Upload latency does not regress. ([video moderation latency comparisons](https://deepcleer.com/m/blog/aws-rekognition-vs-google-vertex-ai-vs-azure-vs-hive-vs-unitary-vs-sightengine-comparison--107))

**Why the gate goes BEFORE cluster, not after:** clustering mutates `CLUSTERS` and writes `clips.cluster_id`. If we cluster first then revoke on moderation fail, we have to:
- pull the clip out of the cluster centroid (Welford reverse — error-prone),
- decrement member_count,
- potentially fail the `_should_compile` gate retroactively if the cluster drops below 2 parents.

That's a lot of inverse-mutation logic for the negative case. Gating before cluster makes blocked clips a **no-op everywhere downstream** — they exist only as `clips` rows with `moderation_status='blocked'`.

### 4.2 Vendor — pick one, defer the comparison

This is an architecture doc, not a vendor-comparison doc. The architecture is **vendor-agnostic** as long as the moderation worker exposes:

```python
async def moderate_clip(clip_id: str) -> ModerationDecision:
    # ModerationDecision = NamedTuple(passed: bool, label: str, score: float, raw: dict)
```

The worker downloads the clip from Blob (or uses the Blob signed URL if vendor accepts URL input — Sightengine and Hive both accept HTTPS URLs as input source, AWS Rekognition Video accepts S3 URIs — Vercel Blob is not S3 so Rekognition needs a download-and-reupload path).

**Architecture-level recommendation:** prefer a vendor that takes an HTTPS URL as input (Sightengine, Hive Moderation API). Saves a download step inside the worker.

### 4.3 Failure modes — explicit chosen behavior

**This is a hard constraint of the milestone — every failure mode needs a chosen behavior.**

| Failure mode | Detection | Chosen behavior | Rationale |
|--------------|-----------|-----------------|-----------|
| **Classifier returns `not passed`** | `ModerationDecision.passed == False` | **HARD-BLOCK.** `mark_clip_blocked` → return. Clip is NOT clustered, NOT compiled, NOT visible. | Only valid behavior given the milestone framing ("blocked clips never enter cluster/compile"). |
| **Classifier API timeout** (we set 10s timeout per call) | `asyncio.TimeoutError` on `mod_task` | **FAIL CLOSED — block as `errored`.** Clip is treated as blocked with `moderation_status='errored'`. Surfaces in admin queue for human review. | The whole point of v1.1 is "survivable in public." Failing open on classifier outage = an outage-shaped exfiltration window. Anonymous unmoderated upload is the exact thing v1.0 deferred. |
| **Classifier API outage / 5xx / connection refused** | `httpx.HTTPError` | **FAIL CLOSED — block as `errored`.** Same as timeout. | Same. |
| **Classifier API quota exhausted** | 429 from vendor | **FAIL CLOSED — block as `errored`.** Add retry-after honoring for 429 specifically (max 1 retry). | Backoff before failing-closed gives transient-burst recovery without dropping the safety property. |
| **Embed succeeds but moderation hangs past pipeline timeout (60s ceiling)** | We add a 60s outer wall-clock cap on `asyncio.gather` | Cancel `mod_task`, treat as fail-closed errored. | Bounded latency for the user-visible "still processing" indicator. |
| **Moderation decides `passed=True` but the clip later becomes objectionable** (e.g., context emerges) | Reactive report flow | Out of scope for moderation gate; handled by Section 5 (report → admin → hide). | This is what the report flow exists for. |

**Escape hatches:**
- `OFFLINE_DEMO=true` skips moderation (returns `passed=True`). Mirrors how `caption_pipeline` already short-circuits in offline mode (`pipeline/caption_pipeline.py:329-330`). Required for staged demos.
- `MODERATION_BYPASS=true` (separate env, not the same as `OFFLINE_DEMO`) for local development without paying classifier costs. Logs warning loudly.

### 4.4 Storage — separate `moderation_decisions` table OR columns on `clips`?

**Decision: columns on `clips` for the live decision; **plus** a `moderation_decisions` audit table for full request/response history.**

Rationale:
- The pipeline reads `clips.moderation_status` constantly (`run_pipeline`, admin views, the report queue). Joining `clips → moderation_decisions` for every read is unnecessary overhead.
- BUT we need full audit history for: (a) classifier-version drift over time, (b) appeal investigations, (c) re-running the gate when we change vendors.

Schema:

```sql
ALTER TABLE clips ADD COLUMN moderation_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE clips ADD COLUMN moderation_reason TEXT;
ALTER TABLE clips ADD COLUMN moderation_score REAL;
ALTER TABLE clips ADD COLUMN moderation_decided_at TIMESTAMPTZ;

CREATE TABLE moderation_decisions (
  id UUID PRIMARY KEY,
  clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
  vendor TEXT NOT NULL,
  vendor_version TEXT,
  status TEXT NOT NULL,  -- passed / blocked / errored
  label TEXT,            -- vendor's category
  score REAL,            -- vendor's confidence
  request_id TEXT,       -- vendor request ID for support escalation
  raw_response JSONB,    -- full response body, for replay
  decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  latency_ms INTEGER
);
CREATE INDEX idx_mod_decisions_clip_id ON moderation_decisions(clip_id);
CREATE INDEX idx_mod_decisions_decided_at ON moderation_decisions(decided_at DESC);
```

Live denormalized columns on `clips` are populated atomically with the audit row inside one transaction.

### 4.5 What lives WHERE in the code

| File | Modified or New | Change |
|------|------|--------|
| `backend/pipeline/moderate.py` | New | `moderate_clip(clip_id) -> ModerationDecision` async worker; vendor-specific HTTP call wrapped here. |
| `backend/pipeline/run.py` | Modified | Wrap `embed_worker` + `moderate_clip` in `asyncio.gather`; add gate that returns early on block. |
| `backend/db.py` | Modified | New helpers: `mark_clip_blocked`, `mark_clip_passed`, `insert_moderation_decision`. |
| `backend/db.py` SCHEMA_SQL | Modified | New columns on `clips`, new `moderation_decisions` table. |
| `backend/config.py` | Modified | `MODERATION_VENDOR`, `MODERATION_API_KEY`, `MODERATION_TIMEOUT_S`, `MODERATION_BYPASS`. |
| `backend/events.py` | Unchanged | New event type `clip_blocked` is just a payload. |

---

## 5. Reactive Report Architecture

### 5.1 Report submission

Single endpoint, anonymous. The session UUID is **non-binding** — it's logged for spam-rate-limiting heuristics but a user could rotate it trivially. Treat it as a coarse signal, not auth.

```python
# backend/app.py
class ReportRequest(BaseModel):
    segment_id: str
    reason: str  # enum: "violence" | "csam" | "harassment" | "private-info" | "other"
    note: str | None = None  # max 280 chars

@app.post("/report", status_code=202)
async def report_segment(
    body: ReportRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    if body.reason not in ALLOWED_REASONS: raise 422
    if body.note and len(body.note) > 280: raise 422
    seg = await db.get_segment(body.segment_id)
    if seg is None: raise 404
    report_id = await db.insert_report(
        segment_id=body.segment_id,
        session_id=x_session_id,
        reason=body.reason,
        note=body.note,
    )
    return {"report_id": report_id, "status": "received"}
```

**No SSE event for reports** — they're one-way notifications to the operator, not feed mutations. Adding a real-time admin notification is v1.2.

### 5.2 Schema

```sql
CREATE TABLE reports (
  id UUID PRIMARY KEY,
  segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  session_id TEXT,
  reason TEXT NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending / dismissed / actioned
  decided_by TEXT,        -- admin token holder; populated on action
  decided_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_reports_status_created ON reports(status, created_at DESC);
CREATE INDEX idx_reports_segment ON reports(segment_id);
```

### 5.3 Admin review surface — endpoint, not dashboard

**Decision: token-guarded JSON endpoints, no separate admin dashboard route.** A frontend admin UI is v1.2 if needed; for v1.1, `curl` + `gh` is enough for the team.

```python
@app.get("/admin/reports", include_in_schema=False)
async def admin_list_reports(
    status: str = Query("pending"),
    x_admin_token: str = Header(...),
): ...

@app.post("/admin/reports/{report_id}/action", include_in_schema=False)
async def admin_action_report(
    report_id: str,
    action: str = Query(...),  # "dismiss" | "hide-segment" | "hide-and-block-clips"
    x_admin_token: str = Header(...),
): ...
```

Reuses the existing `ADMIN_TOKEN` env var pattern from `app.py:373-377`. Same 503-when-unset behavior — closed by default.

### 5.4 Action paths

| Action | Effect |
|--------|--------|
| `dismiss` | `reports.status='dismissed'`, `decided_at=now`. Segment unchanged. |
| `hide-segment` | `segments.is_hidden=true`, `reports.status='actioned'`. Frontend feed query filters `WHERE NOT is_hidden`. |
| `hide-and-block-clips` | `hide-segment` AND for each parent clip in segment: `clips.moderation_status='blocked'`, `moderation_reason='reactive-report'`. (Does NOT delete blob — operator can request hard-delete via separate endpoint). Removes clips from `CLUSTERS` cache via in-memory mutation; if cluster drops below 2 parents, segment stays hidden permanently. |

The **`is_hidden` filter goes into `db.fetch_recent_segments`** (`db.py:314-369`) as a one-line `WHERE NOT s.is_hidden` clause.

### 5.5 What lives WHERE in the code

| File | Modified or New | Change |
|------|------|--------|
| `backend/app.py` | Modified | Add `POST /report`, `GET /admin/reports`, `POST /admin/reports/.../action`. |
| `backend/db.py` | Modified | Add `insert_report`, `list_reports`, `update_report_status`, `hide_segment`, `block_clips_for_segment`. Modify `fetch_recent_segments` to filter `is_hidden`. SCHEMA: new `reports` table, new `segments.is_hidden` column. |
| `backend/models.py` | Modified | `ReportRequest`, `ReportResponse`. |
| `frontend/src/components/SegmentCard.tsx` (or equivalent) | Modified | Add Report button + modal posting to `/report`. |
| `frontend/src/api.ts` | Modified | `postReport`. |

---

## 6. Observability Architecture

### 6.1 Logs — JSON to stdout, ship via Better Stack

**Decision: structured JSON to stdout via `structlog`, captured by Railway log drain → Better Stack.**

Rationale:
- Railway natively captures stdout. Adding any log shipping agent inside the container adds an ops surface.
- Better Stack Logs (formerly Logtail) has a generous free tier (~1 GB/mo, 3-day retention) and a Railway native integration that's a one-click log drain. Axiom is comparable; pick by team familiarity.
- `structlog` over the `logging`-stdlib defaults gives us: deterministic JSON shape, automatic context binding (`clip_id`, `cluster_id`, `request_id`), fast.

The v1.0 logging is plain stdlib (`app.py:19`), already to stdout. Drop-in replacement:

```python
# backend/log.py (new)
import structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
)
log = structlog.get_logger()
```

**Bind context per request via FastAPI middleware:**

```python
@app.middleware("http")
async def bind_request_context(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=str(uuid.uuid4()),
        path=request.url.path,
        session_id=request.headers.get("X-Session-Id"),
    )
    return await call_next(request)
```

This is what makes "trace one user's clip from upload to publish" possible from log-search alone.

### 6.2 Metrics — `/metrics` Prometheus endpoint, scraped by Better Stack or Grafana Cloud

**Decision: Prometheus-format `/metrics` endpoint, scraped pull-based.**

Reasoning over push (StatsD/OTLP):
- One process, one endpoint. Pull is operationally simpler.
- `prometheus_client` Python library has a `make_asgi_app()` that mounts directly into FastAPI.
- Grafana Cloud free tier (10K series, 14-day retention) is enough for v1.1 launch.

Metrics to ship at v1.1 (all derivable from existing log statements):

| Metric | Type | Labels | Source |
|--------|------|--------|--------|
| `newz_clips_uploaded_total` | counter | `mime`, `moderation_status` | `app.py:ingest_clip` |
| `newz_pipeline_stage_duration_seconds` | histogram | `stage` ∈ {embed, moderate, cluster, compile, stitch} | wrap each `await` in pipeline |
| `newz_moderation_decision_total` | counter | `vendor`, `status`, `label` | `pipeline/moderate.py` |
| `newz_compile_outcome_total` | counter | `outcome` ∈ {success, fallback, timeout, exception} | `pipeline/compile.py` |
| `newz_clusters_active` | gauge | — | reads `len(CLUSTERS)` |
| `newz_sse_subscribers` | gauge | — | `events.py:_subscribers` |
| `newz_blob_operation_duration_seconds` | histogram | `op` ∈ {put, get, delete} | `blob.py` |
| `newz_db_operation_duration_seconds` | histogram | `op` | `db.py` (asyncpg query timing) |
| `newz_marengo_latency_ms` | histogram | — | already logged in `embed.py:111` |

### 6.3 Tracing — Sentry as both error tracker AND tracing backend

**Decision: Sentry SDK with native tracing, NOT OpenTelemetry as a separate stack.**

Reasoning:
- We already need Sentry for error tracking. Sentry's native tracing means one SDK install, one DSN, one billing account.
- Sentry's free tier (5K transactions/mo + 5K errors/mo) is plenty for launch. Step up to Team ($26/mo) if quotas fill.
- Sentry's FastAPI integration is mature and auto-instruments routes + DB queries (asyncpg) + HTTPX out-of-the-box.
- OpenTelemetry → Sentry via OTLP works ([Sentry's OTLPIntegration](https://docs.sentry.io/platforms/python/tracing/instrumentation/opentelemetry/)) but adds a layer. We don't have Honeycomb / Lightstep / Tempo today, so the OTel abstraction buys nothing.
- Logfire is the dark-horse option — it's built on OpenTelemetry, has a generous free tier, and is Pydantic-team-built (Newz uses Pydantic for FastAPI). If pricing or vendor lock-in surfaces as a concern, Logfire is a 1:1 swap because both speak OTLP under the hood. ([Pydantic Logfire](https://logfire.pydantic.dev/docs/why/))

**Manual span instrumentation inside compile pipeline** — auto-instrumentation won't see custom function calls. Wrap each pipeline stage:

```python
# pipeline/run.py
import sentry_sdk

async def run_pipeline(clip_id: str):
    with sentry_sdk.start_transaction(op="pipeline", name="run_pipeline") as txn:
        txn.set_tag("clip_id", clip_id)
        with sentry_sdk.start_span(op="moderate"):
            mod_result = await moderate_clip(clip_id)
        with sentry_sdk.start_span(op="embed"):
            embed_result = await embed_worker(clip_id)
        ...
```

Inside `compile_segment`, wrap the orchestrator chain, the caption pipeline, the parent-diversity guard, and the stitch separately so a slow stage shows up in flamegraphs.

### 6.4 Cost forecast at small launch

| Vendor | Tier | Quota | Cost |
|--------|------|-------|------|
| Sentry | Developer (free) | 5K errors + 5K transactions/mo | $0 |
| Better Stack Logs | Free | 1 GB/mo, 3-day retention | $0 |
| Grafana Cloud | Free | 10K series, 14-day retention | $0 |
| Vercel Blob | Pro | $0.15/GB stored | ~$30/mo at 200 GiB |
| Neon Postgres | Free / Launch | 0.5 GiB / 10 GiB | $0 / $19/mo |
| Moderation vendor (Sightengine) | starter | 10K analyses/mo | ~$29/mo |

**v1.1 launch budget: ~$80/mo total** (Blob + Neon + moderation), with logs/metrics/traces free.

### 6.5 What lives WHERE in the code

| File | Modified or New | Change |
|------|------|--------|
| `backend/log.py` | New | structlog config, exposes `log = structlog.get_logger()`. |
| `backend/metrics.py` | New | `prometheus_client` Counter/Histogram/Gauge instances; `make_asgi_app()`. |
| `backend/app.py` | Modified | Install structlog config; mount `/metrics`; install Sentry SDK in lifespan; add request-context middleware. |
| `backend/pipeline/run.py` | Modified | Wrap pipeline stages in `sentry_sdk.start_span`; emit metrics. |
| `backend/pipeline/compile.py` | Modified | Span-wrap orchestrator chain, caption branch, stitch. |
| `backend/db.py` | Modified | Time asyncpg ops, emit `newz_db_operation_duration_seconds`. |
| `backend/blob.py` | New (also Section 3) | Time Blob ops. |
| `backend/config.py` | Modified | `SENTRY_DSN`, `LOGFIRE_TOKEN` (optional). |
| `backend/requirements.txt` | Modified | + `structlog`, `prometheus-client`, `sentry-sdk[fastapi]`. |

---

## 7. Build Order — Hard Dependencies

```
       ┌────────────────────────────────────┐
       │ STEP 0: Observability scaffolding  │   no dependencies
       │  - structlog + Sentry SDK install  │   ship FIRST so all
       │  - /metrics endpoint               │   subsequent work is
       │  - request-id middleware           │   visible in logs/traces
       └────────────────┬───────────────────┘
                        │
       ┌────────────────▼───────────────────┐
       │ STEP 1: Postgres migration         │   blocks STEPS 2-4
       │  - asyncpg pool                    │   because every new column
       │  - dump+load script                │   (moderation_status,
       │  - schema = v1.0 + new columns     │    blob_url, is_hidden)
       │    (moderation, blob_url, hidden)  │   should land in Postgres,
       │  - cutover                         │   not in retiring sqlite
       └────────────────┬───────────────────┘
                        │
       ┌────────────────▼───────────────────┐
       │ STEP 2: Vercel Blob migration      │   blocks STEP 3 hard,
       │  - server-mediated upload          │   because moderation
       │  - ffmpeg signed-URL trim          │   workers may need
       │  - stitch-to-Blob output           │   Blob URL as input
       │  - retire StaticFiles /media       │
       └─────────┬─────────────────┬────────┘
                 │                 │
                 ▼                 ▼
   ┌─────────────────────┐  ┌─────────────────────────┐
   │ STEP 3:             │  │ STEP 4:                 │
   │ Moderation gate     │  │ Reactive report flow    │
   │  (depends on Blob   │  │  (depends on            │
   │   URL for vendors   │  │   Postgres schema       │
   │   that take URL     │  │   +is_hidden column,    │
   │   input)            │  │   not on moderation)    │
   └──────────┬──────────┘  └────────────┬────────────┘
              │                          │
              └──────────────┬───────────┘
                             │
       ┌─────────────────────▼──────────────────────┐
       │ STEP 5: Observability deepening            │   gated on STEPS 1-4
       │  - span wrapping inside pipeline           │   so we wrap the
       │  - dashboard / alert wiring                │   FINAL stage shape,
       │  - cost validation against quotas          │   not throwaway code
       └────────────────────────────────────────────┘
```

### Hard dependency rationale

| Edge | Why it's hard |
|------|---------------|
| **Step 0 → all** | Soft, but recommended-first. Without logging/Sentry we won't be able to debug Steps 1-4 issues fast. Cheap (1 day) and unblocks the rest. |
| **Step 1 → Step 2** | Blob writes need to persist `blob_url` somewhere. Persisting to retiring sqlite is wasted work. |
| **Step 1 → Step 3** | Same — `moderation_status`, `moderation_decisions` table belong in the new DB. |
| **Step 1 → Step 4** | `reports` table + `segments.is_hidden` belong in the new DB. |
| **Step 2 → Step 3** | The moderation worker needs an input URL. If we're using a vendor that accepts HTTPS URL input (Sightengine, Hive), we need Blob's public URLs. Otherwise the moderation worker has to download from local disk, which forces ordering after embed and breaks the parallelism win. |
| **Step 4 ⊥ Step 3** | Report flow does not depend on moderation gate — they share `clips` table but operate on disjoint columns. Can ship in parallel. |

### Recommended phase decomposition for `/gsd-add-phase`

| Phase | Scope | Estimated effort | Demoable? |
|-------|-------|------------------|-----------|
| Phase 1: Observability scaffolding | structlog + Sentry + /metrics | Small (1 day) | Yes — Sentry dashboard shows live errors |
| Phase 2: Postgres migration | asyncpg + dump/load + schema | Medium (2-3 days) | Yes — full v1.0 demo flow on Postgres |
| Phase 3: Vercel Blob migration | server-mediated upload + ffmpeg signed URL | Medium (2-3 days) | Yes — full demo flow with Blob storage |
| Phase 4: Moderation gate (parallel with Phase 5) | moderate worker + pipeline gate + audit table | Medium (2 days) | Yes — block staged-bad clip |
| Phase 5: Reactive report flow (parallel with Phase 4) | report endpoint + admin queue + hide action | Small (1-2 days) | Yes — submit + dismiss + hide |
| Phase 6: Observability deepening | span wrapping + dashboards + alerts | Small (1-2 days) | Yes — distributed trace flamegraph |

---

## 8. Architectural Patterns Worth Naming

### Pattern 1: "Persist first, then mutate cache"
**What:** all state mutations go to Postgres BEFORE the in-memory `CLUSTERS` dict is updated.
**v1.0 source:** `pipeline/cluster.py:175-178` — comment "Pitfall 6" — already enforced.
**v1.1 extension:** same rule for `moderation_status` (DB before SSE broadcast), `is_hidden` (DB before fetch_recent_segments cache). If a process restart happens between persist and broadcast, the cache rebuild from DB recovers the correct state.

### Pattern 2: "Atomic rename / atomic write boundary"
**What:** writes to user-facing artifacts (compiled mp4s) are atomic-from-reader-perspective.
**v1.0 source:** `pipeline/stitch.py:79` — `os.replace(tmp_path, output_path)`.
**v1.1 extension:** Vercel Blob writes-by-pathname are atomic at the URL level. Drop the `os.replace` gymnastics — Blob provides the same property. Local stitch tmp + Blob upload preserves it.

### Pattern 3: "TTL-bounded compare-and-set lock in DB"
**What:** `compile_in_flight` uses `UPDATE ... WHERE compile_in_flight=0 OR last_compile_at < now-ttl` as a CAS.
**v1.0 source:** `db.py:383-408`.
**v1.1 extension:** translates 1:1 to Postgres. Add `SELECT ... FOR UPDATE SKIP LOCKED` if we ever go multi-worker (out of scope v1.1).

### Pattern 4: "Parallel `asyncio.gather` with stage-level wait_for"
**What:** outer wall-clock budget AND inner per-stage budget — preserves whole-pipeline timeout while bounding any single stage.
**v1.0 source:** `pipeline/compile.py:392-399` — outer 300s, inner 180s on orchestrator chain, 125s on Gemini.
**v1.1 extension:** moderation gate uses the same pattern: outer 60s on `gather(embed_task, mod_task)`, inner 10s on the moderation HTTP call.

---

## 9. Anti-Patterns To Avoid

### Anti-Pattern 1: "Migrate to ORM during storage migration"
**Trap:** "While we're touching all the DB code, let's also adopt SQLAlchemy."
**Why bad:** doubles the diff, doubles the risk, and the v1.0 hand-written queries (BLOB round-trip, CAS, cascade deletes, parent-only filters) all need bespoke ORM treatments. Calibration is anchored to behavior; behavior is anchored to query shape.
**Do instead:** swap `aiosqlite` → `asyncpg` mechanically. ORM, if ever, is a separate later milestone.

### Anti-Pattern 2: "Direct browser → Vercel Blob upload"
**Trap:** "It's faster and saves Railway bandwidth."
**Why bad:** breaks pre-publish moderation (clip is publicly addressable before the moderator runs), drops MIME + size validation, requires either a token-vending endpoint anyway or a public-write bucket policy.
**Do instead:** server-mediated upload through FastAPI (Section 3.2).

### Anti-Pattern 3: "Move clustering to pgvector while we're migrating to Postgres"
**Trap:** "Postgres has pgvector. Free upgrade."
**Why bad:** pgvector index choice (HNSW, IVF) interacts with thresholds. v1.0 thresholds are calibrated against exhaustive scan. Switching to approximate-NN silently changes which pairs cluster — and `RETROSPECTIVE.md` explicitly notes "calibration is anchored to specific inputs."
**Do instead:** keep BYTEA + NumPy + in-memory cosine. Revisit pgvector when cluster count justifies it (>10K).

### Anti-Pattern 4: "Fail-open on moderation timeout"
**Trap:** "If the classifier is down, we can't block uploads — that breaks the product."
**Why bad:** unmoderated upload during classifier outage = exactly the threat model v1.1 exists to close.
**Do instead:** fail-closed (Section 4.3). The user sees "still processing" state via SSE; admin queue surfaces `errored` clips for hand review. Bounded latency, bounded blast radius.

### Anti-Pattern 5: "Add OpenTelemetry collector + Tempo + Loki + Prometheus + Grafana"
**Trap:** "Production-grade observability needs the full OTel stack."
**Why bad:** five new operational surfaces for a one-Uvicorn-worker app with no horizontal scale.
**Do instead:** Sentry (one SDK, errors + traces) + structlog → Better Stack + prometheus_client → Grafana Cloud. All free tiers. Three vendors, zero self-hosted infra.

### Anti-Pattern 6: "Blob signed-URL refresh in the request path"
**Trap:** "Sign the Blob URL with a 60-second expiry per render."
**Why bad:** every feed render re-signs N URLs. SSE re-broadcast invalidates the URL the browser already has loaded. Refresh logic in the player.
**Do instead:** public-read bucket with token-required write. Public URLs are stable. The clip's anonymity is preserved by random `clip_id` UUID — the URL is not enumerable.

---

## 10. Integration Points Summary

### External services

| Service | Integration pattern | Failure mode | Notes |
|---------|---------------------|--------------|-------|
| Neon Postgres | asyncpg pool, single Uvicorn worker, max_size=10 | pool exhaustion → 503 via FastAPI | TLS required; `command_timeout=30s` |
| Vercel Blob | HTTP API via httpx; public-read bucket | upload failure → 502, retry once | retain Railway volume one week as recovery |
| Twelve Labs Marengo | sync SDK in `run_in_executor`; tenacity retry | already-handled in v1.0 | unchanged |
| Anthropic (Claude Agent SDK) | fire-and-forget compile; 180s inner timeout | already-handled in v1.0 | unchanged |
| Google Gemini 2.5 Flash | sync SDK in `run_in_executor`; 125s timeout | already-handled in v1.0 | unchanged |
| Moderation vendor | httpx async; 10s timeout; 1 retry on 429 | fail closed → `moderation_status='errored'` | prefer URL-input vendors |
| Sentry | SDK; FastAPI auto-instrument + manual spans | sampling drops on quota; no impact on app | DSN in env |
| Better Stack Logs | Railway log drain (no in-app SDK) | drain failure invisible to app | stdout always captured by Railway |
| Grafana Cloud | scrape `/metrics` endpoint | scrape failure → metrics gap, no app impact | bearer-token scrape config |

### Internal boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `app.py` ↔ pipeline workers | `asyncio.create_task` (fire-and-forget) | unchanged from v1.0 |
| pipeline workers ↔ DB | direct asyncpg via `db.py` helpers | swap from aiosqlite |
| pipeline workers ↔ Blob | direct httpx via `blob.py` helpers | new |
| pipeline workers ↔ moderation vendor | direct httpx via `pipeline/moderate.py` | new |
| pipeline workers ↔ SSE clients | `events.broadcast` → in-memory queue fan-out | unchanged; flag for v1.2 horizontal scaling |
| `cluster_worker` ↔ `CLUSTERS` dict | asyncio.Lock-guarded critical section | unchanged |
| compile pipeline ↔ stitch | direct function call; per-stage `asyncio.wait_for` | unchanged shape; ffmpeg input is now URL or local-tmp depending on call site |

---

## Sources

- [FastAPI async with Postgres (Neon)](https://neon.com/guides/fastapi-async)
- [Supabase Connection Scaling for FastAPI](https://medium.com/@papansarkar101/supabase-connection-scaling-the-essential-guide-for-fastapi-developers-2dc5c428b638)
- [asyncpg + Supabase pooler issue](https://github.com/supabase/supabase/issues/39227)
- [Supabase pooling and asyncpg — the real fix](https://medium.com/@patrickduch93/supabase-pooling-and-asyncpg-dont-mix-here-s-the-real-fix-44f700b05249)
- [Supabase connection management](https://supabase.com/docs/guides/database/connection-management)
- [Vercel Blob client uploads](https://vercel.com/docs/vercel-blob/client-upload)
- [Vercel Blob server uploads](https://vercel.com/docs/vercel-blob/server-upload)
- [Vercel platform limits](https://vercel.com/docs/limits)
- [ffmpeg HTTP / S3 streaming for video processing](https://copyprogramming.com/howto/how-to-read-remote-video-on-amazon-s3-using-ffmpeg)
- [ffmpeg protocols documentation](https://ffmpeg.org/ffmpeg-protocols.html)
- [2025/2026 video moderation platform comparison](https://deepcleer.com/m/blog/aws-rekognition-vs-google-vertex-ai-vs-azure-vs-hive-vs-unitary-vs-sightengine-comparison--107)
- [Best video moderation APIs 2026 — Eden AI](https://www.edenai.co/post/best-video-analysis-apis)
- [Sentry OpenTelemetry integration](https://docs.sentry.io/platforms/python/tracing/instrumentation/opentelemetry/)
- [Pydantic Logfire (OTel-based)](https://logfire.pydantic.dev/docs/why/)

### Internal sources (read directly)

- `/Users/liamshalom/Hacktech/backend/app.py` — request handlers, lifespan, admin
- `/Users/liamshalom/Hacktech/backend/db.py` — full schema + helper surface
- `/Users/liamshalom/Hacktech/backend/pipeline/run.py` — pipeline orchestration
- `/Users/liamshalom/Hacktech/backend/pipeline/embed.py` — Marengo integration
- `/Users/liamshalom/Hacktech/backend/pipeline/cluster.py` — clustering math + cache
- `/Users/liamshalom/Hacktech/backend/pipeline/compile.py` — multi-agent compile
- `/Users/liamshalom/Hacktech/backend/pipeline/stitch.py` — ffmpeg call sites
- `/Users/liamshalom/Hacktech/backend/pipeline/caption_pipeline.py` — Gemini composite (second ffmpeg call site)
- `/Users/liamshalom/Hacktech/backend/events.py` — SSE fan-out
- `/Users/liamshalom/Hacktech/frontend/src/api.ts` — frontend integration shape
- `/Users/liamshalom/Hacktech/.planning/PROJECT.md` — v1.1 scope authority
- `/Users/liamshalom/Hacktech/.planning/MILESTONES.md` — v1.0 shipped surface
- `/Users/liamshalom/Hacktech/CLAUDE.md` — stack, hard constraints, lessons

---
*Architecture research for: Newz v1.1 Public-Launch-Ready Backbone*
*Researched: 2026-04-27*
