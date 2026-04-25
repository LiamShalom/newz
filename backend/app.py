"""
backend/app.py — FastAPI application entry point for Newz.

Hot path:
    Browser → POST /clips (202) → asyncio.create_task(run_pipeline)
           → embed_worker (Phase 2) → cluster_worker (Phase 3)
           → compile_pipeline (Phase 4) → SSE broadcast → feed re-renders

Phase 1 delivers: clip ingest, DB storage, raw feed, SSE bus scaffold.
Phase 2 adds: embed_worker wired into run_pipeline, pre-warm lifespan.
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
import db as db_module

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

os.makedirs(config.CLIPS_DIR, exist_ok=True)


# ── SSE event bus ─────────────────────────────────────────────────────────────

class _SSEBus:
    """Simple fan-out event bus. Subscribers get a Queue; broadcast pushes to all."""

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []

    async def broadcast(self, event: dict) -> None:
        dead: list[asyncio.Queue] = []
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._queues.remove(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)


events = _SSEBus()


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_pipeline(clip_id: str) -> None:
    """
    Background pipeline triggered by POST /clips.
    Phase 2 wires embed_worker() here.
    Phase 3 wires cluster_worker() after embed.
    Phase 4 wires compile_pipeline() after cluster.
    """
    try:
        async with db_module.get_db_conn() as conn:
            # Phase 2 adds: embedding = await embed_worker(clip_id, conn)
            log.info("run_pipeline stub clip_id=%s (embed_worker not yet wired)", clip_id)
            await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "pending"})
    except Exception as exc:
        log.exception("run_pipeline failed clip_id=%s", clip_id)
        await events.broadcast({"type": "pipeline_error", "clip_id": clip_id, "error": str(exc)})


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_module.init_db()
    # Phase 2 adds: asyncio.create_task(_pre_warm_marengo())
    yield
    await db_module.close_db()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Newz API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/clips", status_code=202)
async def ingest_clip(
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lng: float | None = Form(None),
    ts: float | None = Form(None),
    duration_sec: float | None = Form(None),
):
    """Accept a video clip, store to disk, kick off background pipeline."""
    clip_id = str(uuid.uuid4())
    now = time.time()
    suffix = Path(file.filename or "clip.mp4").suffix or ".mp4"
    clip_path = os.path.join(config.CLIPS_DIR, f"{clip_id}{suffix}")

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:  # 100 MB guard (T-02-04)
        raise HTTPException(status_code=413, detail="Clip exceeds 100 MB limit")

    with open(clip_path, "wb") as f:
        f.write(content)

    clip = {
        "id": clip_id,
        "path": clip_path,
        "lat": lat,
        "lng": lng,
        "ts": ts or now,
        "duration_sec": duration_sec,
        "created_at": now,
    }

    async with db_module.get_db_conn() as conn:
        await db_module.create_clip(clip, conn)

    asyncio.create_task(run_pipeline(clip_id))

    return {"clip_id": clip_id, "status": "accepted"}


@app.get("/clips/{clip_id}")
async def get_clip(clip_id: str):
    async with db_module.get_db_conn() as conn:
        clip = await db_module.get_clip(clip_id, conn)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


@app.get("/feed")
async def get_feed():
    """Phase 1 stub — returns raw list of clips. Phase 4 replaces with SSE + clusters."""
    async with db_module.get_db_conn() as conn:
        async with conn.execute(
            "SELECT id, lat, lng, ts, embedding_status, cluster_id, created_at FROM clips ORDER BY created_at DESC LIMIT 50"
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@app.get("/health")
async def health():
    return {"status": "ok"}
