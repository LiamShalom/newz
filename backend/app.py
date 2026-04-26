import asyncio
import json
import logging
import math
import os
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, Form, Header, File, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

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
        _, _, latency_ms = await loop.run_in_executor(None, _sync_embed, pre_warm_path, "__prewarm__")
        log.info("Marengo pre-warm complete latency_ms=%d", latency_ms)
    except Exception as exc:
        log.warning("Marengo pre-warm failed (non-fatal): %s", exc)


async def _pre_warm_sdk() -> None:
    """Pre-warm Claude Agent SDK connection. Parallel with Marengo pre-warm.
    Skipped when OFFLINE_DEMO=true or ANTHROPIC_API_KEY not set (log + degrade gracefully).
    """
    if os.environ.get("OFFLINE_DEMO", "").lower() == "true":
        log.info("sdk pre-warm skipped (OFFLINE_DEMO=true)")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning(
            "ANTHROPIC_API_KEY not set — compile pipeline will be unavailable. "
            "Set the key to enable."
        )
        return
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
        async for _ in query(prompt="ok", options=ClaudeAgentOptions(model="sonnet", max_turns=1)):
            break
        log.info("Claude SDK pre-warm complete")
    except Exception as exc:
        log.warning("Claude SDK pre-warm failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    # Phase 3: rebuild in-memory cluster cache from sqlite (CLU-10).
    # Must complete before pre-warm task is scheduled so the first clip ingest
    # sees a populated cache.
    from .pipeline import cluster as cluster_mod
    await cluster_mod.rebuild_cache()
    # FED-05: insert staged demo segment if segments table is empty
    from .seed.demo_segment import seed_demo_segment
    await seed_demo_segment()
    # Fire pre-warms in parallel (Marengo + Claude SDK) — fire-and-forget; never blocks startup
    asyncio.create_task(_pre_warm_marengo())
    asyncio.create_task(_pre_warm_sdk())
    yield


app = FastAPI(title="Newz API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.get("/feed")
async def feed(
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
):
    """FED-01: proximity + recency sort. lat/lng optional — falls back to recency."""
    rows = await db.fetch_recent_segments(limit=50)
    if lat is not None and lng is not None:
        def _score(seg: dict) -> float:
            clat, clng = seg.get("centroid_lat"), seg.get("centroid_lng")
            d_m = _haversine_m(lat, lng, clat, clng) if clat is not None else 1e9
            age_s = max(1.0, _time.time() - seg["created_at"])
            return -(d_m / 1000.0) - (age_s / 3600.0) * 0.5
        rows.sort(key=_score, reverse=True)
    return {"segments": rows}


@app.get("/events")
async def sse_events(request: Request):
    """RTM-01: SSE endpoint. One EventSource per tab (HTTP/1.1 6-connection limit)."""
    q = await events.subscribe()

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield {"event": event.get("type", "message"), "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    continue
        finally:
            await events.unsubscribe(q)

    return EventSourceResponse(event_stream(), ping=15)


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


@app.post("/debug/compile/{cluster_id}")
async def debug_trigger_compile(cluster_id: str):
    """Dev-only: manually trigger compile on an existing cluster."""
    from .pipeline.compile import compile_segment
    await db.set_compile_in_flight(cluster_id, False)  # reset so CAS allows it
    acquired = await db.set_compile_in_flight(cluster_id, True)
    if not acquired:
        raise HTTPException(status_code=409, detail="compile already in flight")
    asyncio.create_task(compile_segment(cluster_id))
    return {"status": "triggered", "cluster_id": cluster_id}


@app.get("/debug/dbstate")
async def debug_dbstate():
    """Dev-only: counts and sample IDs straight from sqlite, no in-memory."""
    import aiosqlite as _aios
    async with _aios.connect(db.DB_PATH) as conn:
        conn.row_factory = _aios.Row
        cur = await conn.execute("SELECT COUNT(*) FROM clips")
        n_clips = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM clips WHERE cluster_id IS NOT NULL")
        n_clipped = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM clusters")
        n_clusters = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT id, cluster_id FROM clips ORDER BY created_at DESC LIMIT 5")
        sample_clips = [dict(r) for r in await cur.fetchall()]
        cur = await conn.execute("SELECT id, member_count FROM clusters")
        cluster_rows = [dict(r) for r in await cur.fetchall()]
    return {
        "db_path": str(db.DB_PATH),
        "clips_total": n_clips,
        "clips_with_cluster_id": n_clipped,
        "clusters_total": n_clusters,
        "sample_clips": sample_clips,
        "clusters": cluster_rows,
    }


@app.get("/debug/clip/{clip_id}")
async def debug_clip(clip_id: str):
    """Dev-only: return the raw clip row from the DB."""
    clip = await db.get_clip(clip_id)
    if not clip:
        return {"found": False, "clip_id": clip_id}
    return {"found": True, "clip": clip}


@app.post("/debug/caption_writer/{cluster_id}")
async def debug_caption_writer(cluster_id: str):
    """Dev-only: run the vision caption-writer directly. Does NOT write to DB.

    Returns the raw caption/location on success, or the exception type+message
    on failure. Also reports keyframe extraction count so we can isolate where
    the pipeline is failing.
    """
    from .pipeline.compile import _run_caption_writer_with_vision
    from .pipeline.keyframes import (
        extract_cluster_keyframes,
        _fetch_cluster_clips_with_duration,
        _extract_one,
        FFMPEG,
    )
    import os as _os

    diagnostics: dict = {"ffmpeg_path": FFMPEG, "ffmpeg_exists": _os.path.exists(FFMPEG)}

    # Stage 1: DB lookup
    try:
        kf_clips = await _fetch_cluster_clips_with_duration(cluster_id)
        diagnostics["keyframes_db_clips"] = [
            {"id": c["id"], "path": c["path"], "duration_sec": c.get("duration_sec"),
             "path_exists": _os.path.exists(c["path"])}
            for c in kf_clips
        ]
    except Exception as e:
        return {"stage": "keyframes_db_lookup", "error": type(e).__name__,
                "message": str(e), "diagnostics": diagnostics}

    # Cross-check: what does compile's own DB lookup return?
    try:
        compile_clips = await db.fetch_cluster_clips(cluster_id)
        diagnostics["compile_db_clips_count"] = len(compile_clips)
    except Exception as e:
        diagnostics["compile_db_clips_error"] = f"{type(e).__name__}: {e}"

    if not kf_clips:
        return {
            "stage": "keyframes_db_lookup",
            "note": "no clips with this cluster_id — DB mismatch",
            "diagnostics": diagnostics,
        }

    # Stage 2: per-clip ffmpeg
    per_clip = []
    for c in kf_clips:
        try:
            png = await _extract_one(c["path"], c.get("duration_sec"))
            per_clip.append({"id": c["id"], "png_bytes": len(png) if png else 0})
        except Exception as e:
            per_clip.append({"id": c["id"], "error": f"{type(e).__name__}: {e}"})
    diagnostics["per_clip_extract"] = per_clip

    try:
        frames = await extract_cluster_keyframes(cluster_id)
        frames_info = [{"clip_id": cid, "png_bytes": len(png)} for cid, png in frames]
    except Exception as e:
        return {"stage": "extract_keyframes", "error": type(e).__name__,
                "message": str(e), "diagnostics": diagnostics}

    if not frames:
        return {
            "stage": "extract_keyframes",
            "frames_extracted": 0,
            "note": "no frames extracted — caption-writer would raise and trigger fallback",
            "diagnostics": diagnostics,
        }

    try:
        result = await _run_caption_writer_with_vision(cluster_id)
        return {
            "stage": "success",
            "frames_extracted": len(frames),
            "frames": frames_info,
            "caption": result.get("caption"),
            "location": result.get("location"),
        }
    except Exception as e:
        return {
            "stage": "caption_writer",
            "frames_extracted": len(frames),
            "frames": frames_info,
            "error": type(e).__name__,
            "message": str(e),
        }
