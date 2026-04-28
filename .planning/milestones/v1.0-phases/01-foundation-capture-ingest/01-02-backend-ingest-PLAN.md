---
phase: 01-foundation-capture-ingest
plan: 02
type: execute
wave: 2
depends_on: ["01-01"]
files_modified:
  - backend/app.py
  - backend/db.py
  - backend/models.py
  - backend/events.py
  - backend/pipeline/__init__.py
  - backend/pipeline/run.py
autonomous: true
requirements:
  - ING-01
  - ING-02
  - ING-03
  - ING-04
  - ING-05
  - ING-06

must_haves:
  truths:
    - "POST /clips accepts a multipart upload (file + lat + lng + ts) and returns 202 with clip_id in under 100ms"
    - "Uploaded clip bytes land at {DATA_DIR}/clips/{clip_id}.{ext}"
    - "Clip metadata (id, path, lat, lng, ts, session_id, created_at) is written to SQLite in WAL mode"
    - "Pipeline is kicked off via asyncio.create_task — POST handler does not await embed/cluster/compile"
    - "GET /feed returns up to 50 most recent clips ordered newest-first as JSON"
    - "Clips served as static files via /media/{filename} mount (NOT /clips/* — that prefix is reserved for the POST/GET API routes)"
    - "X-Session-Id header is persisted on the clip row but never echoed in responses or logs"
    - "Uploads larger than MAX_UPLOAD_BYTES (100 MiB) are rejected with HTTP 413 BEFORE bytes are written to disk or SQLite"
  artifacts:
    - path: "backend/db.py"
      provides: "aiosqlite WAL init + insert_clip + fetch_recent_clips + ext-from-mime helper"
      contains: "PRAGMA journal_mode=WAL"
    - path: "backend/app.py"
      provides: "POST /clips, GET /feed, /media static mount, lifespan calls db.init()"
      contains: "asyncio.create_task(run_pipeline(clip_id))"
    - path: "backend/events.py"
      provides: "broadcast() stub callable from app.py"
      contains: "async def broadcast"
    - path: "backend/pipeline/run.py"
      provides: "Phase 1 no-op stub for run_pipeline"
      contains: "async def run_pipeline"
    - path: "backend/models.py"
      provides: "Pydantic Clip response model"
      contains: "class Clip"
  key_links:
    - from: "backend/app.py"
      to: "backend/db.py"
      via: "db.init() in lifespan + db.insert_clip in /clips + db.fetch_recent_clips in /feed"
      pattern: "db\\.(init|insert_clip|fetch_recent_clips)"
    - from: "backend/app.py"
      to: "backend/pipeline/run.py"
      via: "asyncio.create_task(run_pipeline(clip_id))"
      pattern: "asyncio\\.create_task\\(run_pipeline"
    - from: "backend/app.py"
      to: "backend/events.py"
      via: "events.broadcast({type: clip_added})"
      pattern: "events\\.broadcast"
    - from: "POST /clips response"
      to: "GET /media/{file}"
      via: "StaticFiles mount on DATA_DIR/clips at URL prefix /media"
      pattern: "StaticFiles"
---

<objective>
Wire the backend ingest path. POST /clips accepts a multipart upload + GPS + timestamp + anonymous session id, persists the file to disk and the row to SQLite (WAL), kicks off the pipeline via `asyncio.create_task`, and returns 202 with `clip_id` in under 100ms. Add GET /feed (newest-first list) and a /media/* static mount so the FE can play uploads back. The pipeline itself is a no-op stub — Phase 2 lands real Marengo embed.

**URL-prefix rule (LOAD-BEARING):** the API verbs (`POST /clips`, `GET /clips`) live at `/clips`. Static files served from disk live at `/media`. Mounting `StaticFiles` at `/clips` would shadow the API routes (Starlette `Mount` returns `Match.FULL` on the bare path and intercepts ALL methods), so the POST handler would 405. **Do not change the static mount prefix back to `/clips` for any reason.**

Purpose: Without this plumbing the camera has no destination and the feed has nothing to render. The fire-and-forget pattern (`asyncio.create_task`, NOT `await`, NOT `BackgroundTasks`) is established here on day 1 so Phases 2-4 do not retrofit it.

Output: Backend ingest fully functional. `curl -X POST http://localhost:8000/clips -F file=@x.mp4 -F lat=34.14 -F lng=-118.13 -F ts=1714000000 -H "X-Session-Id: $(uuidgen)"` returns 202 + clip_id; the file appears on disk and the row appears in SQLite; `curl http://localhost:8000/feed` returns it with `url: "/media/<id>.mp4"`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-foundation-capture-ingest/01-CONTEXT.md
@.planning/phases/01-foundation-capture-ingest/01-PATTERNS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@.planning/research/STACK.md
@CLAUDE.md
@backend/app.py
@backend/config.py

<interfaces>
<!-- From Plan 01: backend/app.py exists with FastAPI(lifespan=lifespan), CORS middleware, /health route. -->
<!-- This plan extends backend/app.py — keep CORS, /health, and the lifespan; ADD db.init() inside lifespan, ADD StaticFiles mount AT /media (NOT /clips), ADD POST /clips and GET /feed routes. -->

Existing (from Plan 01):
```python
# backend/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import config

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # <-- Plan 02 adds db.init() here

app = FastAPI(title="Newz API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[config.FRONTEND_URL, "http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    return {"ok": True}
```

Existing config:
```python
# backend/config.py
DATA_DIR: Path  # ./data locally, /data on Railway (Plan 05)
FRONTEND_URL: str
OFFLINE_DEMO: bool
```

SQLite schema (Phase 1; PATTERNS.md lines 134-149):
```sql
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL DEFAULT 'pending',
  cluster_id TEXT,
  session_id TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at);
```

MIME-to-extension map (PATTERNS.md lines 184-193, CAP-10 from FE side):
- `video/mp4` -> `mp4`
- `video/webm` -> `webm`
- unknown / null -> `webm`
- strip codec params (`video/mp4;codecs=avc1` -> base `video/mp4`)

URL prefix map:
- `POST /clips` — ingest API (multipart upload)
- `GET /clips` — DOES NOT EXIST in Phase 1 (the API does not list clips at /clips; the list lives at GET /feed). Reserved for future API use.
- `GET /feed` — JSON list of recent clips
- `GET /media/{filename}` — static file serve from `DATA_DIR/clips/`. Note the URL prefix `/media` ≠ on-disk dir `clips/`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="false">
  <name>Task 1: SQLite (WAL) schema + db.py async helpers + models.py</name>
  <files>
    backend/db.py
    backend/models.py
  </files>
  <read_first>
    backend/config.py
    .planning/research/ARCHITECTURE.md (lines 528-585 — Storage / SQLite schema)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 128-193 — db.py pattern, MIME ext map)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (S1 anonymity invariant — session_id stored never logged as identity)
  </read_first>
  <action>
Create `backend/db.py` with WAL-mode init, insert_clip, fetch_recent_clips, and the MIME-to-extension helper. Create `backend/models.py` with the Pydantic Clip response model.

**`backend/db.py`** — all SQL must use parameterized queries (S5 in CLAUDE.md security implicit; Phase 1 takes only well-typed FastAPI Form floats so injection is bounded, but parameterize anyway). Anonymity invariant per ING-06: store `session_id` but never log it.

```python
import os
import time
import uuid
import logging
from pathlib import Path

import aiosqlite
from fastapi import UploadFile

from . import config

log = logging.getLogger(__name__)

DB_PATH = config.DATA_DIR / "newz.db"
CLIPS_DIR = config.DATA_DIR / "clips"

# Forward-compat: full schema declared at init even though Phase 1 only writes `clips`.
# Phase 2 fills clip_embeddings, Phase 3 clusters, Phase 4 segments. This avoids a migration.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL DEFAULT 'pending',
  cluster_id TEXT,
  session_id TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at);

CREATE TABLE IF NOT EXISTS clip_embeddings (
  clip_id TEXT PRIMARY KEY,
  vector BLOB,
  latency_ms REAL,
  created_at REAL,
  FOREIGN KEY(clip_id) REFERENCES clips(id)
);

CREATE TABLE IF NOT EXISTS clusters (
  id TEXT PRIMARY KEY,
  centroid_lat REAL,
  centroid_lng REAL,
  median_ts REAL,
  member_count INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  ordered_clip_ids TEXT NOT NULL,
  caption TEXT,
  location TEXT,
  source_count INTEGER NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(cluster_id) REFERENCES clusters(id)
);
"""


async def init() -> None:
    """Create directories + schema. WAL mode for concurrent reads during writes."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
    log.info("db.init: schema ready at %s", DB_PATH)


_MIME_EXT = {"video/mp4": "mp4", "video/webm": "webm"}


def ext_from_mime(mime: str | None) -> str:
    """Map browser-sent MIME to filesystem extension. Strips codec params per CAP-10 ladder."""
    if not mime:
        return "webm"
    base = mime.split(";")[0].strip().lower()
    return _MIME_EXT.get(base, "webm")


async def insert_clip(
    file: UploadFile,
    lat: float,
    lng: float,
    ts: float,
    session_id: str | None,
) -> str:
    """Persist clip bytes to disk + metadata row. Returns clip_id.

    Anonymity invariant (ING-06): session_id is stored but NEVER returned in any response,
    NEVER printed in logs at INFO level (logging session_id is forbidden).

    NOTE: caller is responsible for enforcing MAX_UPLOAD_BYTES BEFORE invoking this function.
    This helper does not re-check size; it trusts the route handler to gate.
    """
    clip_id = uuid.uuid4().hex
    ext = ext_from_mime(file.content_type)
    path = CLIPS_DIR / f"{clip_id}.{ext}"
    # Stream to disk; do not load whole blob into memory at large sizes.
    contents = await file.read()
    path.write_bytes(contents)
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO clips (id, path, lat, lng, ts, session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (clip_id, str(path), lat, lng, ts, session_id, now),
        )
        await conn.commit()
    # Log clip_id and rounded GPS only — never session_id, never exact GPS (privacy floor).
    log.info(
        "insert_clip id=%s lat=%.2f lng=%.2f bytes=%d",
        clip_id, lat, lng, len(contents),
    )
    return clip_id


async def fetch_recent_clips(limit: int = 50) -> list[dict]:
    """Return newest-first clips for the Phase 1 raw feed (D-08).
    NEVER include session_id in the returned dict — that is identity-adjacent.

    URL prefix is /media (the StaticFiles mount in app.py), NOT /clips.
    /clips is the API verb namespace (POST = ingest); /media is the static-file namespace.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT id, path, lat, lng, ts, created_at "
            "FROM clips ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
    out = []
    for r in rows:
        # Translate filesystem path to public URL the FE can fetch.
        # /media/* is mounted on DATA_DIR/clips by app.py.
        filename = Path(r["path"]).name
        out.append({
            "id": r["id"],
            "url": f"/media/{filename}",
            "lat": r["lat"],
            "lng": r["lng"],
            "ts": r["ts"],
            "created_at": r["created_at"],
        })
    return out
```

**`backend/models.py`** — Pydantic response models:
```python
from pydantic import BaseModel


class Clip(BaseModel):
    id: str
    url: str
    lat: float
    lng: float
    ts: float
    created_at: float


class IngestResponse(BaseModel):
    clip_id: str
    status: str
```

**Why path-from-mime here, not later:** the file extension determines what `<video src=...>` plays back. Hardcoding `.mp4` would silently break Chrome/Firefox webm uploads. The map is intentionally tiny — fancy MIME parsing is unnecessary because the FE MIME ladder (Plan 04) only emits the four shapes covered here.

**Why no SQL injection mitigations beyond `?` params:** every input either comes from a typed FastAPI Form (float for lat/lng/ts, validated strings for headers), or is a UUID we generate. We do not compose SQL strings.

**Privacy logging rule:** `lat=%.2f lng=%.2f` rounds to ~1.1km — coarse enough that logs never leak exact venue location. session_id is never logged.

**URL prefix rule:** the public URL emitted in the feed payload is `/media/<filename>`, not `/clips/<filename>`. The `/clips` URL prefix is reserved for the API verb (POST). Mounting StaticFiles at `/clips` would shadow the API route — see Task 2 action notes.
  </action>
  <verify>
    <automated>cd /Users/liamshalom &amp;&amp; backend/.venv/bin/python -c "
import asyncio
from backend import db, config
async def main():
    await db.init()
    # confirm WAL mode actually applied
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute('PRAGMA journal_mode')
        row = await cur.fetchone()
        assert row[0].lower() == 'wal', f'expected wal, got {row[0]}'
        cur = await conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")
        tables = sorted([r[0] for r in await cur.fetchall()])
        assert 'clips' in tables, f'missing clips table; got {tables}'
    print('OK', tables)
asyncio.run(main())
"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -q "PRAGMA journal_mode=WAL" backend/db.py` succeeds
    - `grep -q "uuid.uuid4().hex" backend/db.py` succeeds (clip_id is UUID4 hex per PATTERNS.md)
    - `grep -q "ext_from_mime" backend/db.py` succeeds
    - `grep -q "session_id is stored but NEVER returned" backend/db.py` OR equivalent comment containing both "session_id" and "NEVER" succeeds (anonymity invariant explicit in code)
    - `grep -q "lat=%.2f lng=%.2f" backend/db.py` succeeds (privacy-rounded logging)
    - `grep -q "ORDER BY created_at DESC" backend/db.py` succeeds
    - `! grep -E "log.*session_id" backend/db.py` returns 0 matches (session_id NEVER appears in any log call — verify via `grep -E "log\\.(info\\|warning\\|error\\|debug).*session_id" backend/db.py | grep -v "anonymity\\|invariant\\|forbidden\\|never"` returns no real log lines)
    - `grep -q 'f"/media/' backend/db.py` succeeds (feed URL uses /media prefix, NOT /clips)
    - `! grep -q 'f"/clips/{filename}"' backend/db.py` (must NOT emit /clips/<filename> as a public URL)
    - `grep -q "class Clip" backend/models.py` succeeds
    - Runtime test (verify command above) prints "OK ['clip_embeddings', 'clips', 'clusters', 'segments']" — schema persisted, WAL mode active
    - Verify command resolves to a SQLite file at `backend/data/newz.db` after running (`ls backend/data/newz.db` succeeds)
  </acceptance_criteria>
  <done>SQLite WAL DB initializes, schema applied, insert/fetch helpers in place, MIME-to-ext map covers the four FE-emitted shapes, anonymity invariant explicit in code (session_id stored but excluded from feed responses and logs). Feed payload emits `url: "/media/<filename>"` (NOT `/clips/<filename>`).</done>
</task>

<task type="auto" tdd="false">
  <name>Task 2: events.py stub + pipeline/run.py stub + extend app.py with POST /clips, GET /feed, /media static mount</name>
  <files>
    backend/events.py
    backend/pipeline/__init__.py
    backend/pipeline/run.py
    backend/app.py
  </files>
  <read_first>
    backend/app.py (current state from Plan 01)
    backend/db.py (just created in Task 1)
    .planning/research/ARCHITECTURE.md (lines 134-163 — fire-and-forget pattern; lines 290-313 — events bus)
    .planning/research/PITFALLS.md (Pitfall #9 — embed queue backup; Pitfall #1 — Marengo latency: explains why fire-and-forget on day 1)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 102-122 — POST /clips pattern; lines 197-237 — events.py + pipeline/run.py stubs)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (D-07 conflict: this plan accepts the FE side blocks on GPS; backend takes whatever lat/lng/ts arrives)
  </read_first>
  <action>
Add three new files and extend `backend/app.py` with the ingest + feed routes.

**`backend/pipeline/__init__.py`** — empty file (package marker).

**`backend/pipeline/run.py`** — Phase 1 no-op stub. The `asyncio.create_task(run_pipeline(clip_id))` call site in app.py must work today even though Phase 2 fills in the embed step. PATTERNS.md lines 222-238 specifies this verbatim:

```python
import logging

log = logging.getLogger(__name__)


async def run_pipeline(clip_id: str) -> None:
    """Phase 1 stub — fire-and-forget kickoff target. Real pipeline:
    Phase 2: await embed.generate(clip_id)
    Phase 3: cluster_id = await cluster.assign_or_create(...)
    Phase 4: if cluster.should_compile: await compile.run(...)
    """
    log.info("pipeline kicked off clip_id=%s (Phase 1: no-op)", clip_id)
```

**`backend/events.py`** — Phase 1 broadcast stub. Phase 4 (RTM-01) will replace the inert loop with an SSE response. PATTERNS.md lines 197-218:

```python
import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue] = []


async def broadcast(event: dict[str, Any]) -> None:
    """Phase 1: subscribers list is always empty (no SSE endpoint yet).
    Phase 4 wires GET /events to populate _subscribers and stream.
    """
    log.info("event %s", event.get("type"))
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
```

**Extend `backend/app.py`** — add db.init() in lifespan, mount StaticFiles AT `/media` (NOT `/clips`), add POST /clips and GET /feed.

**CRITICAL — URL prefix collision:** Starlette `Mount("/clips", StaticFiles(...))` returns `Match.FULL` for the bare path `/clips` regardless of method. If the static mount and the `@app.post("/clips")` route share the prefix, all methods on `/clips` route to StaticFiles, which 405s/404s on POST — the entire ingest path breaks. The fix is to mount static files at a different prefix (`/media`); the API verbs stay at `/clips`. Do not "simplify" by reusing the same prefix.

Replace the entire file with:
```python
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, Form, Header, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, db, events
from .pipeline.run import run_pipeline
from .models import IngestResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    yield


app = FastAPI(title="Newz API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static mount must be created after DATA_DIR exists. db.init() (in lifespan) creates it,
# but at module import StaticFiles checks the path. Make sure the dir exists eagerly:
config.DATA_DIR.mkdir(parents=True, exist_ok=True)
(config.DATA_DIR / "clips").mkdir(parents=True, exist_ok=True)
# IMPORTANT: mount at "/media", NOT "/clips". Starlette Mount("/clips") returns Match.FULL
# for the bare path /clips and would shadow the @app.post("/clips") API route below
# (POSTs would 405 because StaticFiles only answers GET/HEAD). The on-disk directory is
# still DATA_DIR/clips — only the URL prefix changes.
app.mount("/media", StaticFiles(directory=str(config.DATA_DIR / "clips")), name="media")


@app.get("/health")
async def health():
    return {"ok": True}


# Hard limit per PITFALLS.md "Security & Trust Mistakes" (no upload size limit -> DoS via giant uploads).
# 100MB is the documented cap; 30s clips at typical phone bitrates are 5-25MB.
# This constant is ENFORCED in ingest_clip below — see the explicit `len(contents) > MAX_UPLOAD_BYTES`
# check that 413s before any disk write or DB insert.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB

ALLOWED_MIME_PREFIXES = ("video/mp4", "video/webm")


@app.post("/clips", status_code=202, response_model=IngestResponse)
async def ingest_clip(
    file: UploadFile = File(...),
    lat: float = Form(...),
    lng: float = Form(...),
    ts: float = Form(...),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    # Defensive validation. Errors here are 4xx so the FE retry queue does NOT retry them.
    if file.content_type and not any(file.content_type.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail=f"unsupported content type: {file.content_type}")

    # Bound GPS to plausible ranges (defense-in-depth; FE already constrains).
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise HTTPException(status_code=422, detail="lat/lng out of range")

    # Read and SIZE-CHECK before persisting (T-02-02 mitigation).
    # We do this in the route (not inside db.insert_clip) so that:
    #   - the 413 fires BEFORE any disk write or SQLite insert (no orphan rows or files)
    #   - oversized uploads are rejected with a clean HTTP error rather than OOM
    # Note: `await file.read()` still buffers the whole body in memory. For Phase 1 dev this
    # is acceptable (laptop RAM >> 100 MiB). Plan 05 (Railway) sets an nginx-level body cap
    # so the bytes never reach Python in the first place.
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="clip too large")
    # Rewind so insert_clip can re-read via UploadFile API.
    await file.seek(0)

    clip_id = await db.insert_clip(file, lat, lng, ts, session_id=x_session_id)

    # Broadcast clip_added (no subscribers in Phase 1, but the call site is established).
    await events.broadcast({"type": "clip_added", "clip_id": clip_id})

    # Fire-and-forget. NEVER `await` this. NEVER use BackgroundTasks (per ARCHITECTURE.md
    # "Why not BackgroundTasks"). Phase 2 fills run_pipeline with the real embed step.
    asyncio.create_task(run_pipeline(clip_id))

    # Response is intentionally minimal — never echoes session_id, never echoes path.
    return IngestResponse(clip_id=clip_id, status="processing")


@app.get("/feed")
async def feed():
    """Phase 1: raw clips ordered newest-first (D-08). Phase 4 (FED-01) replaces with
    proximity+recency segment ranking — different schema entirely.

    Each clip's `url` field is `/media/<filename>`, served by the StaticFiles mount above.
    """
    rows = await db.fetch_recent_clips(limit=50)
    return {"clips": rows}
```

**Implementation notes (cross-checked against research):**

- **Why mount at `/media`, not `/clips`:** Starlette `Mount("/clips", StaticFiles(...))` returns `Match.FULL` for the bare path `/clips` and intercepts EVERY method on that path. Registering `@app.post("/clips")` after the mount does not save you — the mount wins. StaticFiles only knows GET/HEAD, so POST returns 405 and the ingest path is silently broken. Fix: keep the API verbs at `/clips`, move static-file serving to `/media`. The on-disk directory is still `DATA_DIR/clips/` — only the URL prefix differs.

- **Why size-check in the route, not inside db.insert_clip:** if we delegated to db.insert_clip, the bytes would already be on disk and the row would already be in flight before we noticed. Checking in the route lets us 413 BEFORE any side effect. Trade-off: we read the full body into memory (`await file.read()`) and then `seek(0)` so insert_clip can re-read via the UploadFile API. For Phase 1 dev this is fine; Plan 05 (Railway) layers an nginx body cap so the bytes never reach Python on prod.

- **Why `await events.broadcast` BEFORE `asyncio.create_task`:** broadcast is fast (Phase 1 just logs), and putting it before create_task means even if the pipeline task fails immediately, the SSE clients (Phase 4) still see the clip arrived. PATTERNS.md does it in this order verbatim.

- **Why `response_model=IngestResponse`:** Pydantic strips any field not declared on the model — defense in depth against accidentally returning session_id.

- **Why `HTTPException` 415/422/413 not 400:** the FE upload queue (CAP-09) retries on transient errors. 4xx says "do not retry, this is a programming error." 415 = wrong MIME, 422 = invalid GPS, 413 = oversize.

- **Why no `python-jose` / signature on session_id:** ING-06 invariant — session_id is NOT identity, NOT auth. It is a "this is mine" hint for later UX (Phase 4 FED). Adding signing would imply identity guarantees we explicitly do not have.

**ING-02 100ms budget check:** the handler does (a) form parse, (b) `file.read()` + size check (in-memory; for a 25MB clip on a laptop this is ~50-100ms — borderline), (c) `file.seek(0)`, (d) `db.insert_clip` which re-reads + writes to disk + inserts into SQLite (WAL = ~1ms). The 100ms target measures from header arrival to 202 response. For typical 5-15MB clips this is comfortable; 100MB clips will exceed. Document this honestly: in Phase 5 if we see >100ms in dev, switch to streaming the upload into a temp file via `aiofiles` rather than `await file.read()`. **Do not optimize prematurely.** The pipeline is what cannot block — and `asyncio.create_task` ensures it does not.
  </action>
  <verify>
    <automated>cd /Users/liamshalom &amp;&amp; backend/.venv/bin/python -c "from backend.app import app; routes = sorted([r.path for r in app.routes if hasattr(r, 'path')]); print(routes)" | grep -E "(/clips|/feed|/health|/media)"</automated>
    <runtime>cd /Users/liamshalom &amp;&amp; backend/.venv/bin/uvicorn backend.app:app --port 8765 --app-dir . &amp; sleep 2 &amp;&amp; printf "fakedata" &gt; /tmp/clip.mp4 &amp;&amp; T0=$(python3 -c "import time; print(time.time())") &amp;&amp; RESP=$(curl -fsS -X POST http://localhost:8765/clips -F "file=@/tmp/clip.mp4;type=video/mp4" -F "lat=34.14" -F "lng=-118.13" -F "ts=1714000000" -H "X-Session-Id: test-uuid-1234") &amp;&amp; T1=$(python3 -c "import time; print(time.time())") &amp;&amp; echo "RESP=$RESP elapsed=$(python3 -c "print($T1-$T0)")" &amp;&amp; echo "$RESP" | grep -E '"clip_id":"[a-f0-9]{32}"' &amp;&amp; echo "$RESP" | grep -v "test-uuid-1234" &amp;&amp; FEED=$(curl -fsS http://localhost:8765/feed) &amp;&amp; echo "FEED=$FEED" &amp;&amp; echo "$FEED" | grep -q '"url":"/media/' &amp;&amp; CLIP_URL=$(echo "$FEED" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['clips'][0]['url'])") &amp;&amp; curl -fsS -o /tmp/back.mp4 "http://localhost:8765$CLIP_URL" &amp;&amp; diff /tmp/clip.mp4 /tmp/back.mp4 &amp;&amp; kill %1; rm /tmp/clip.mp4 /tmp/back.mp4</runtime>
    <oversize>cd /Users/liamshalom &amp;&amp; backend/.venv/bin/uvicorn backend.app:app --port 8766 --app-dir . &amp; sleep 2 &amp;&amp; dd if=/dev/zero of=/tmp/big.mp4 bs=1m count=101 2&gt;/dev/null &amp;&amp; STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8766/clips -F "file=@/tmp/big.mp4;type=video/mp4" -F "lat=34.14" -F "lng=-118.13" -F "ts=1714000000" -H "X-Session-Id: test") &amp;&amp; echo "oversize_status=$STATUS" &amp;&amp; [ "$STATUS" = "413" ] &amp;&amp; kill %1; rm /tmp/big.mp4</oversize>
  </verify>
  <acceptance_criteria>
    - `grep -q "asyncio.create_task(run_pipeline(clip_id))" backend/app.py` succeeds (fire-and-forget pattern present)
    - `! grep -q "await run_pipeline" backend/app.py` (NEVER awaits the pipeline)
    - `! grep -q "BackgroundTasks" backend/app.py` (does NOT use FastAPI BackgroundTasks per ARCHITECTURE.md)
    - `grep -q 'status_code=202' backend/app.py` succeeds
    - `grep -q 'response_model=IngestResponse' backend/app.py` succeeds (response shape locked)
    - `grep -q 'X-Session-Id' backend/app.py` succeeds (header read)
    - `grep -q 'StaticFiles' backend/app.py` succeeds (clip files served back)
    - `grep -q 'app.mount("/media"' backend/app.py` succeeds (static mount uses /media prefix, NOT /clips)
    - `! grep -q 'app.mount("/clips"' backend/app.py` (must NOT mount StaticFiles at /clips — would shadow POST /clips)
    - `grep -q 'await db.init()' backend/app.py` succeeds (lifespan calls init)
    - `grep -q 'CORSMiddleware' backend/app.py` succeeds (CORS preserved from Plan 01)
    - `grep -q 'allowed_origins\\|allow_origins' backend/app.py` succeeds with `config.FRONTEND_URL` referenced
    - `grep -q 'ALLOWED_MIME_PREFIXES' backend/app.py` succeeds (defense vs. unexpected uploads)
    - `grep -q 'video/mp4' backend/app.py && grep -q 'video/webm' backend/app.py` (both MIMEs in allowlist)
    - `grep -q 'MAX_UPLOAD_BYTES' backend/app.py` succeeds (constant declared)
    - `grep -q 'len(contents) > MAX_UPLOAD_BYTES' backend/app.py` succeeds (constant ENFORCED, not just declared)
    - `grep -q 'status_code=413' backend/app.py` succeeds (oversize returns 413)
    - `grep -q 'await file.seek(0)' backend/app.py` succeeds (rewind after pre-read so insert_clip can re-read)
    - Runtime test: POST /clips returns HTTP 202 with `{"clip_id":"<32-hex>","status":"processing"}` (proven by runtime verify command)
    - Runtime test: response body does NOT contain "test-uuid-1234" (proven by `grep -v` in verify)
    - Runtime test: GET /feed returns at least one row with `"url":"/media/..."` (NOT `/clips/...`)
    - Runtime test: GET against the returned `/media/<id>.mp4` URL returns the original bytes (round-trip diff succeeds)
    - Oversize test: a 101 MiB POST returns HTTP 413 (proven by `<oversize>` verify command)
    - Runtime test wallclock from POST start to 202 receipt is < 1.0s on dev laptop (printed by verify command — manually verify <100ms target during execution; >1s = fail)
    - `grep -q "async def broadcast" backend/events.py` succeeds
    - `grep -q "async def run_pipeline" backend/pipeline/run.py` succeeds
  </acceptance_criteria>
  <done>POST /clips persists file + row, returns 202 with clip_id, kicks off run_pipeline via create_task. GET /feed returns newest-first clips with `url: "/media/<filename>"`. /media/{file} static mount serves video back from DATA_DIR/clips. Uploads exceeding MAX_UPLOAD_BYTES are rejected with 413 BEFORE any disk write or DB insert. Anonymity invariant: session_id never in response, never in logs.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser -> POST /clips | Untrusted multipart upload + form fields cross here. Anonymous; no auth. |
| POST /clips -> filesystem | File bytes written to local disk under `DATA_DIR/clips/`. |
| POST /clips -> SQLite | Metadata written; session_id stored but never echoed. |
| GET /media/{file} (static) | Public read of any clip filename — anonymous; PoC-acceptable. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-01 | T (Tampering) | clip filename / path traversal | mitigate | clip_id is `uuid.uuid4().hex` server-generated — user-supplied filename is discarded. Extension comes from MIME map (only `.mp4` or `.webm` possible). Path is `CLIPS_DIR / f"{clip_id}.{ext}"` — no user input in the path. StaticFiles only serves files under the mounted dir (`DATA_DIR/clips`, exposed at URL prefix `/media`). |
| T-02-02 | D (DoS) | upload size | mitigate | `MAX_UPLOAD_BYTES = 100 MiB` is **enforced** in the `ingest_clip` route: `await file.read()` then `if len(contents) > MAX_UPLOAD_BYTES: raise HTTPException(413)` BEFORE the disk write or SQLite insert. Oversize uploads cannot create orphan files or rows. ALLOWED_MIME_PREFIXES rejects non-video early (415). Hard nginx body limit deferred to Plan 05 (Railway deploy) so multi-GB POSTs are dropped at the proxy and never enter Python — current Phase 1 mitigation is RAM-bounded by the 100 MiB ceiling but still requires reading the full body into memory once; acceptable on dev laptop, hardened at deploy. |
| T-02-03 | I (Information disclosure) | session_id leak via response or log | mitigate | `IngestResponse` Pydantic model has only `clip_id` + `status` — Pydantic strips extras. `fetch_recent_clips` SELECTs explicit columns and the constructed dict has no `session_id` key. `db.insert_clip` log line uses `lat=%.2f lng=%.2f` (rounded to ~1.1km) and never logs session_id. Verified by acceptance criterion that excludes session_id from response body. |
| T-02-04 | I (Information disclosure) | exact GPS in logs | mitigate | All log calls use `%.2f` for lat/lng (rounds to ~1.1km — coarse enough that logs do not pinpoint the venue). |
| T-02-05 | S (Spoofing) | X-Session-Id is user-controlled | accept | ING-06 invariant: session_id is NOT identity, NOT auth — it is a "this is mine" UX hint. Spoofing it has no security impact because it confers no privilege. Documented in code comment. |
| T-02-06 | I (Information disclosure) | CORS misconfiguration | mitigate | `allow_origins=[config.FRONTEND_URL, "http://localhost:5173"]` — explicit allowlist, never `["*"]` with credentials. Plan 05 sets FRONTEND_URL to the Vercel prod origin. |
| T-02-07 | T (Tampering) | SQL injection | mitigate | All SQL uses `?` parameterized queries. No string concat or f-string composition into SQL. Inputs are FastAPI-validated floats and a UUID we generate. |
| T-02-08 | E (Elevation of privilege) | clip access via predictable IDs | accept | UUID4 is 122 bits — not enumerable. Clips are intentionally world-readable (anonymous-by-default product). No EoP path because anyone can read any clip; the URL space is the access control (no auth model exists by design). |
| T-02-09 | D (DoS) | rate limit absent | accept | Phase 1 has no rate limiting; Railway free tier provides basic infra-level limits. Pitfall #9 (queue backup under judge clicks) is the SLOW-BUILD path — not a security threat, a UX one. Defer real rate limiting to Plan 05 only if observed. |
| T-02-10 | T (Tampering) | URL prefix collision (StaticFiles shadowing POST) | mitigate | StaticFiles is mounted at `/media`, not `/clips`. Starlette `Mount("/clips")` would return `Match.FULL` and shadow the `@app.post("/clips")` route — POSTs would 405. Acceptance criterion `! grep -q 'app.mount("/clips"' backend/app.py` enforces this at the source level. Runtime verify proves POST /clips returns 202 (i.e. is not shadowed). |
</threat_model>

<verification>
- `make backend` brings the server up; `curl http://localhost:8000/health` returns 200.
- POST a tiny file via curl (see runtime verify) — receive 202 + clip_id, file appears at `backend/data/clips/<id>.mp4`, row appears in SQLite.
- `curl http://localhost:8000/feed | jq .clips[0]` returns the just-uploaded clip with a `/media/...` URL (NOT `/clips/...`).
- `curl http://localhost:8000/media/<id>.mp4 -o /tmp/back.mp4 && diff /tmp/back.mp4 <original>` — bytes round-trip cleanly via the static mount.
- Oversize gate: `dd if=/dev/zero of=/tmp/big bs=1m count=101 && curl -X POST .../clips -F file=@/tmp/big...` returns 413; no row in SQLite, no file under DATA_DIR/clips.
- `grep -ri "session_id" backend/data/newz.db.log 2>/dev/null` — no log file should ever contain a session_id (this verification is informational; the real check is the acceptance criteria grep on log format strings).
- Wall-clock from POST start to 202 response < 1s for a 1KB file on a dev laptop. ING-02's 100ms target is best-effort for clips < 25MB.
</verification>

<success_criteria>
- ING-01: POST /clips accepts multipart (file + lat + lng + ts) — proven by runtime test.
- ING-02: 202 returned with clip_id; pipeline never awaited — proven by code grep + runtime wallclock.
- ING-03: clip persisted to `DATA_DIR/clips/{clip_id}.{ext}` with extension from MIME map; served back via `/media/{filename}` URL prefix.
- ING-04: clip metadata persisted to SQLite (`clips` table, WAL mode) with id, path, lat, lng, ts, session_id, created_at.
- ING-05: pipeline kicked off via `asyncio.create_task(run_pipeline(clip_id))`.
- ING-06: X-Session-Id header read, stored on the clip row, never returned in responses, never logged.
- T-02-02 (DoS): MAX_UPLOAD_BYTES enforced; 101 MiB POST returns 413 with no side effects.
- T-02-10 (route collision): StaticFiles mounted at `/media`, not `/clips`; POST /clips reaches the API handler and returns 202.
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-capture-ingest/01-02-SUMMARY.md` with:
- Files changed (lines added) + the 4 new files
- Output of `curl -X POST .../clips ... -w "elapsed: %{time_total}s\n"` to record the actual ING-02 latency on dev hardware
- Output of the oversize gate test (HTTP status code from a 101 MiB POST)
- One-line schema dump: `sqlite3 backend/data/newz.db ".schema clips"`
- Confirmation that `grep -E "log\\.[a-z]+\\(.*session_id" backend/` returns no log call lines
- Confirmation that the feed payload's first clip has `url` starting with `/media/` (not `/clips/`)
</output>
</content>
</invoke>