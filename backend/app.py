import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, Form, Header, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, db, events
from .pipeline.run import run_pipeline
from .models import IngestResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


async def _pre_warm_marengo() -> None:
    """Fire-and-forget Marengo pre-warm. Pays cold-start cost before first judge clip.
    Skipped when USE_MOCK_EMBEDDINGS=true. Failure is non-fatal."""
    if config.USE_MOCK_EMBEDDINGS:
        log.info("pre-warm skipped (USE_MOCK_EMBEDDINGS=true)")
        return
    pre_warm_path = config.PRE_WARM_CLIP_PATH
    if not pre_warm_path or not Path(pre_warm_path).exists():
        log.warning("pre-warm skipped: PRE_WARM_CLIP_PATH=%r not found", pre_warm_path)
        return
    try:
        from .pipeline.embed import _sync_embed
        loop = asyncio.get_event_loop()
        _, latency_ms = await loop.run_in_executor(None, _sync_embed, pre_warm_path, "__prewarm__")
        log.info("Marengo pre-warm complete latency_ms=%d", latency_ms)
    except Exception as exc:
        log.warning("Marengo pre-warm failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    # Phase 3: rebuild in-memory cluster cache from sqlite (CLU-10).
    # Must complete before pre-warm task is scheduled so the first clip ingest
    # sees a populated cache.
    from .pipeline import cluster as cluster_mod
    await cluster_mod.rebuild_cache()
    asyncio.create_task(_pre_warm_marengo())  # fire-and-forget; never blocks startup
    yield


app = FastAPI(title="Newz API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
(config.DATA_DIR / "clips").mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(config.DATA_DIR / "clips")), name="media")


@app.get("/health")
async def health():
    return {"ok": True}


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
    if file.content_type and not any(file.content_type.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail=f"unsupported content type: {file.content_type}")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise HTTPException(status_code=422, detail="lat/lng out of range")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="clip too large")
    await file.seek(0)

    clip_id = await db.insert_clip(file, lat, lng, ts, session_id=x_session_id)
    await events.broadcast({"type": "clip_added", "clip_id": clip_id})
    asyncio.create_task(run_pipeline(clip_id))
    return IngestResponse(clip_id=clip_id, status="processing")


@app.get("/feed")
async def feed():
    rows = await db.fetch_recent_clips(limit=50)
    return {"clips": rows}


@app.get("/debug/clusters", include_in_schema=False)
async def debug_clusters() -> dict:
    """CLU-09: per-cluster member breakdown with composite score against centroid.

    Internal calibration endpoint. Reads in-memory CLUSTERS dict + DB embeddings.
    Do NOT expose to authenticated public traffic in production.
    """
    from .pipeline import cluster as cluster_mod

    clusters_out = []
    for c in cluster_mod.CLUSTERS.values():
        members = []
        for clip_id in c.member_ids:
            clip = await db.get_clip(clip_id)
            vec = await db.get_embedding(clip_id)
            if clip is None or vec is None:
                continue   # race: clip in cluster but embedding not yet stored
            sb = cluster_mod.score_against(c, vec, clip["lat"], clip["lng"], clip["ts"])
            gps_distance_m = (
                None if not sb.gps_available
                else round(cluster_mod.haversine_m(
                    clip["lat"], clip["lng"], c.centroid_lat, c.centroid_lng), 1)
            )
            members.append({
                "clip_id": clip_id,
                "lat": clip["lat"],
                "lng": clip["lng"],
                "ts": clip["ts"],
                "visual": round(sb.visual, 4),
                "gps": round(sb.gps, 4),
                "time": round(sb.time, 4),
                "composite": round(sb.composite, 4),
                "gps_available": sb.gps_available,
                "gps_distance_m": gps_distance_m,
                "time_delta_s": round(abs(clip["ts"] - c.median_ts), 1),
            })
        clusters_out.append({
            "cluster_id": c.id,
            "member_count": c.member_count,
            "centroid_lat": c.centroid_lat,
            "centroid_lng": c.centroid_lng,
            "median_ts": c.median_ts,
            "members": members,
        })

    return {
        "threshold": config.CLUSTER_THRESHOLD,
        "visual_floor": config.VISUAL_FLOOR,
        "weights": {
            "visual": cluster_mod.W_VISUAL,
            "gps": cluster_mod.W_GPS,
            "time": cluster_mod.W_TIME,
        },
        "gps_radius_m": cluster_mod.GPS_RADIUS_M,
        "time_window_s": cluster_mod.TIME_WINDOW_S,
        "clusters": clusters_out,
    }
