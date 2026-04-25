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

# CORS allowlist per STACK.md §"CORS" + PATTERNS.md S6.
# FRONTEND_URL is the Vercel deploy origin in prod (Plan 05); localhost:5173 is dev.
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


# Hard limit per PITFALLS.md "Security & Trust Mistakes" (no upload size limit -> DoS via
# giant uploads). 100MB is the documented cap; 30s clips at typical phone bitrates are 5-25MB.
# This constant is ENFORCED in ingest_clip below — see the explicit
# `len(contents) > MAX_UPLOAD_BYTES` check that 413s before any disk write or DB insert.
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
