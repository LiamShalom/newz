# Phase 8 (D-01..D-17): observability MUST be imported before any other backend
# module that calls logging.getLogger(). Pitfall 6 — without this, pre-warm and
# DB-init log lines emit as plain text instead of JSON.
from . import observability  # noqa: F401  — runs configure_logging() + init_sentry() at import

import asyncio
import hmac
import json
import logging
import math
import os
import re
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, Form, Header, File, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from html import escape as _html_escape
from sse_starlette.sse import EventSourceResponse

from structlog.contextvars import bind_contextvars

from . import config, db, events, rate_limit, content_filter
from .pipeline.run import run_pipeline
from .models import IngestResponse, CommentCreateRequest
from .observability.middleware import XFFStrip, RequestIDAndContextvarsBind
from .observability.metrics import MetricsMiddleware, make_metrics_endpoint, STAGE_DURATION

log = logging.getLogger(__name__)


async def _pre_warm_marengo() -> None:
    """Fire-and-forget Marengo pre-warm. Pays cold-start cost before first clip.
    Failure is non-fatal."""
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
    Skipped when ANTHROPIC_API_KEY not set (log + degrade gracefully).
    """
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


async def _neon_keepalive(pool) -> None:
    """DEMO-03: SELECT 1 every config.KEEPALIVE_INTERVAL_S seconds (default 240)
    to defeat Neon's scale-to-zero idle threshold (5 min). Logs one INFO line per
    successful ping, one WARNING per failure. Cancelled cleanly on shutdown.

    Runs outside any request scope — no contextvars (request_id absent on purpose).
    structlog stdlib bridge from Phase 8 routes the log line through JSON automatically.
    """
    keepalive_log = logging.getLogger("backend.keepalive")
    while True:
        try:
            await pool.fetchval("SELECT 1")
            keepalive_log.info("neon_keepalive ok")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            keepalive_log.warning("neon_keepalive failed (non-fatal): %s", exc)
        await asyncio.sleep(config.KEEPALIVE_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # asyncpg pool init + Neon keepalive task.
    # Order: init_pool → db.init (no-op; schema owned by Alembic) → cluster rebuild
    #        → keepalive task → pre-warm tasks → yield. Shutdown reverses with cancel + close.
    # OFFLINE_DEMO=true skips every step that would touch Neon/Blob — preserves
    # the firewalled-CI smoke test posture without a SQLite fallback.
    keepalive_task: asyncio.Task | None = None
    db_live = not config.OFFLINE_DEMO

    # 1. asyncpg pool — skipped under OFFLINE_DEMO.
    if db_live:
        await db.init_pool()

    # 2. db.init() — no-op (schema owned by Alembic). Just ensures CLIPS_DIR
    #    exists for /media StaticFiles and emits a startup log line.
    await db.init()

    # 3. CLUSTERS rebuild — needs a live pool. Skip when no pool was init'd.
    if db_live:
        from .pipeline import cluster as cluster_mod
        await cluster_mod.rebuild_cache()

    # 3.5. Phase 10 (D-02, D-19): httpx Blob client init — only when blob mode active.
    # OFFLINE_DEMO=true short-circuits to local at the dispatcher (D-18), so this
    # branch is unreachable under firewalled-CI; enforces D-19 fail-loud on missing token.
    if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
        from .storage import blob_client
        await blob_client.init_client()

    # 4. Neon keepalive. Started AFTER rebuild so the rebuild gets a clean pool slot first.
    if db_live:
        keepalive_task = asyncio.create_task(_neon_keepalive(db.get_pool()))

    # 5. Existing pre-warms (unchanged) — fire-and-forget.
    asyncio.create_task(_pre_warm_marengo())
    asyncio.create_task(_pre_warm_sdk())

    try:
        yield
    finally:
        # Shutdown: cancel keepalive, close blob client, then close the pool.
        if keepalive_task is not None:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass
        if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
            from .storage import blob_client
            await blob_client.close_client()
        if not config.OFFLINE_DEMO:
            await db.close_pool()


app = FastAPI(title="Newz API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 8 (D-12): middleware registration order matters because FastAPI applies
# middleware in REVERSE-add-order. Effective request flow:
#   XFFStrip (outermost) -> RequestIDAndContextvarsBind -> MetricsMiddleware -> CORS -> routes
# XFFStrip MUST run first so client-supplied IP-revealing headers are stripped
# before any other middleware or route handler can log them (PRIV-01).
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIDAndContextvarsBind)
app.add_middleware(XFFStrip)

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
(config.DATA_DIR / "clips").mkdir(parents=True, exist_ok=True)
# Phase 10 (D-16): /media is only mounted in local mode or under OFFLINE_DEMO.
# In blob mode the frontend renders absolute Vercel Blob URLs (BLOB-05).
if config.STORAGE_BACKEND == "local" or config.OFFLINE_DEMO:
    app.mount("/media", StaticFiles(directory=str(config.DATA_DIR / "clips")), name="media")


@app.get("/health")
async def health():
    return {"ok": True}


_RUN_ID_RE = re.compile(r"^[a-f0-9]+_run_[0-9]+$")


@app.get("/runs/{run_id}.mp4", include_in_schema=False)
async def runs_proxy(run_id: str, request: Request):
    """Phase 10 proxy for runs/{run_id}.mp4 stored on a private-only Blob store.

    The provisioned Vercel Blob store rejects `access="public"` uploads, so
    runs/* land at the private domain and require the bearer token. We can't
    leak that token to the browser, so the backend streams the bytes through
    with the Authorization header attached. Forwards the client's Range header
    so iOS Safari's media element can seek without buffering the whole file.
    """
    if config.STORAGE_BACKEND != "blob" or config.OFFLINE_DEMO:
        raise HTTPException(status_code=404, detail="not found")
    if not _RUN_ID_RE.match(run_id) or len(run_id) > 128:
        raise HTTPException(status_code=400, detail="invalid run_id")

    from .storage import blob_client
    token = config.BLOB_READ_WRITE_TOKEN
    store_id = blob_client._store_id_from_token(token)
    upstream = f"https://{store_id}.private.blob.vercel-storage.com/runs/{run_id}.mp4"
    headers = {"Authorization": f"Bearer {token}"}
    rng = request.headers.get("range")
    if rng:
        headers["Range"] = rng

    client = blob_client.get_client()
    req = client.build_request("GET", upstream, headers=headers)
    upstream_resp = await client.send(req, stream=True)

    if upstream_resp.status_code in (404, 410):
        await upstream_resp.aclose()
        raise HTTPException(status_code=404, detail="not found")
    if upstream_resp.status_code >= 400:
        body = (await upstream_resp.aread())[:500]
        await upstream_resp.aclose()
        log.warning("runs proxy upstream %d run_id=%s body=%s", upstream_resp.status_code, run_id, body)
        raise HTTPException(status_code=502, detail="upstream error")

    passthrough = {"content-type", "content-length", "content-range", "accept-ranges", "etag", "last-modified"}
    out_headers = {k: v for k, v in upstream_resp.headers.items() if k.lower() in passthrough}
    out_headers.setdefault("content-type", "video/mp4")
    out_headers.setdefault("accept-ranges", "bytes")
    out_headers["cache-control"] = "private, max-age=60"

    async def _body():
        try:
            async for chunk in upstream_resp.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(_body(), status_code=upstream_resp.status_code, headers=out_headers)


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

    # Phase 8 (D-17): ingest stage timing covers file-write + DB-insert latency.
    # Full request latency captured separately by REQUEST_DURATION{route="/clips"}.
    with STAGE_DURATION.labels(stage="ingest").time():
        clip_id = await db.insert_clip(file, lat, lng, ts, session_id=x_session_id)
    # WR-01: bind clip_id into structlog contextvars now that it exists, so any
    # subsequent log line in this request (including the broadcast below) carries
    # clip_id as a structured field. PRIV-02 whitelist allows clip_id.
    # The contextvar is request-scoped — RequestIDAndContextvarsBind clears
    # contextvars at request end, and run_pipeline (spawned below) re-binds in
    # its own task context.
    bind_contextvars(clip_id=clip_id)
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
                    # Default "message" event so es.onmessage receives all types.
                    # Frontend discriminates on ev.type from the JSON payload.
                    yield {"data": json.dumps(event)}
                except asyncio.TimeoutError:
                    continue
        finally:
            await events.unsubscribe(q)

    return EventSourceResponse(event_stream(), ping=15)


# ---------------------------------------------------------------------------
# Phase 01 (feature track): anonymous comments on segments (montages)
#   POST /segments/{id}/comments — body { text }; X-Session-Id header (server-side only)
#   GET  /segments/{id}/comments — public-safe list, no session_id leakage
# ---------------------------------------------------------------------------

async def _segment_exists(segment_id: str) -> bool:
    """Existence check via get_segment_for_cluster reverse-lookup is awkward; use raw query.
    Returns True iff a row in `segments` matches the given id."""
    row = await db.get_pool().fetchrow(
        "SELECT 1 FROM segments WHERE id = $1", segment_id,
    )
    return row is not None


@app.post("/segments/{segment_id}/comments", status_code=201)
async def post_comment(
    segment_id: str,
    payload: CommentCreateRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-Id header required")
    if not await _segment_exists(segment_id):
        raise HTTPException(status_code=404, detail="segment not found")
    text = payload.text.strip()
    if not (1 <= len(text) <= 300):
        raise HTTPException(status_code=400, detail="text must be 1-300 chars after trim")
    allowed, retry_after = await rate_limit.check_and_record(x_session_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="too many comments — slow down",
            headers={"Retry-After": str(retry_after)},
        )
    filter_result = content_filter.check(text)
    if filter_result.blocked:
        raise HTTPException(status_code=400, detail=f"comment rejected: {filter_result.reason}")
    comment = await db.insert_comment(segment_id, x_session_id, text)
    await events.broadcast({
        "type": "comment_added",
        "segment_id": segment_id,
        "comment": comment,
    })
    return comment


@app.get("/segments/{segment_id}/comments")
async def list_segment_comments(segment_id: str):
    if not await _segment_exists(segment_id):
        raise HTTPException(status_code=404, detail="segment not found")
    return {"comments": await db.list_comments(segment_id)}


# ---------------------------------------------------------------------------
# Phase 01 (feature track): public single-segment fetch + share landing
#   GET /segments/{id}        — JSON for the standalone montage view (T3.2)
#   GET /m/{id}               — server-rendered HTML with OG tags (T3.1).
#                               Bots scrape OG; browsers JS-redirect to FRONTEND_URL.
# ---------------------------------------------------------------------------

@app.get("/segments/{segment_id}")
async def get_segment(segment_id: str):
    seg = await db.get_segment_by_id(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="segment not found")
    return seg


def _truncate(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


@app.get("/m/{segment_id}", response_class=HTMLResponse, include_in_schema=False)
async def share_landing(segment_id: str, request: Request):
    """T3.1 — server-rendered share landing. iMessage/Twitter unfurlers don't run
    JS, so OG tags must be in the initial HTML. Browsers fall through to a
    JS+meta-refresh redirect to FRONTEND_URL/m/{segment_id} (handled by the SPA)."""
    seg = await db.get_segment_by_id(segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail="segment not found")

    # request.base_url is what we hand to OG meta tags. Uvicorn defaults to
    # proxy_headers=True, so Railway's X-Forwarded-Proto: https propagates and
    # base_url reports https — required for og:video URLs to load in iMessage.
    base = str(request.base_url).rstrip("/")
    video_url = seg.get("video_url")
    absolute_video = f"{base}{video_url}" if video_url else ""

    title = seg.get("title") or seg.get("caption") or "Newz montage"
    caption = seg.get("caption") or ""
    location = seg.get("location") or ""
    description = _truncate(f"{caption}{(' · ' + location) if location else ''}".strip(" ·"), 200)

    share_url = f"{base}/m/{segment_id}"
    spa_url = f"{config.FRONTEND_URL.rstrip('/')}/m/{segment_id}"

    # html.escape covers attribute injection; no innerHTML interpolation here.
    e = _html_escape
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{e(title)}</title>
<meta name="description" content="{e(description)}" />

<meta property="og:type" content="video.other" />
<meta property="og:site_name" content="Newz" />
<meta property="og:title" content="{e(title)}" />
<meta property="og:description" content="{e(description)}" />
<meta property="og:url" content="{e(share_url)}" />
{f'<meta property="og:video" content="{e(absolute_video)}" />' if absolute_video else ''}
{f'<meta property="og:video:secure_url" content="{e(absolute_video)}" />' if absolute_video else ''}
{f'<meta property="og:video:type" content="video/mp4" />' if absolute_video else ''}

<meta name="twitter:card" content="{('player' if absolute_video else 'summary')}" />
<meta name="twitter:title" content="{e(title)}" />
<meta name="twitter:description" content="{e(description)}" />
{f'<meta name="twitter:player" content="{e(absolute_video)}" />' if absolute_video else ''}

<meta http-equiv="refresh" content="0; url={e(spa_url)}" />
<script>window.location.replace({json.dumps(spa_url)});</script>
</head>
<body style="font-family:system-ui,sans-serif;padding:24px;color:#111">
<p>Redirecting to <a href="{e(spa_url)}">Newz</a>…</p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@app.get("/debug/clusters", include_in_schema=False)
async def debug_clusters() -> dict:
    """CLU-09: per-cluster member breakdown + cross-cluster pairwise diagnostic.

    Internal calibration endpoint. Reads in-memory CLUSTERS dict + DB embeddings.
    Do NOT expose to authenticated public traffic in production.

    For each clip, emits TWO views:
      - `members[*]` (legacy): score against the cluster the clip already belongs to.
        For singletons this is trivially 1.0/1.0/1.0/1.0 (the clip IS the centroid).
      - `pairwise_scores[*]` (added 2026-04-26 per .planning/debug/clips-not-clustering.md):
        score the clip against every OTHER cluster's centroid, plus reasons it was
        rejected. Answers the real diagnostic question: "why didn't these cluster?"
    """
    from .pipeline import cluster as cluster_mod

    # Pre-load every clip's embedding + metadata once so we can score across clusters
    # without re-fetching from sqlite for each (cluster, clip) pair.
    all_clips: list[dict] = []
    for c in cluster_mod.CLUSTERS.values():
        for clip_id in c.member_ids:
            clip = await db.get_clip(clip_id)
            vec = await db.get_embedding(clip_id)
            if clip is None or vec is None:
                continue
            all_clips.append({
                "clip_id": clip_id,
                "own_cluster_id": c.id,
                "lat": clip["lat"],
                "lng": clip["lng"],
                "ts": clip["ts"],
                "vec": vec,
            })

    clusters_out = []
    for c in cluster_mod.CLUSTERS.values():
        members = []
        pairwise_scores = []
        for clip_info in all_clips:
            sb = cluster_mod.score_against(
                c, clip_info["vec"], clip_info["lat"], clip_info["lng"], clip_info["ts"]
            )
            gps_distance_m: float | None = None
            if (sb.gps_available
                    and clip_info["lat"] is not None and clip_info["lng"] is not None
                    and c.centroid_lat is not None and c.centroid_lng is not None):
                gps_distance_m = round(cluster_mod.haversine_m(
                    clip_info["lat"], clip_info["lng"],
                    c.centroid_lat, c.centroid_lng), 1)

            # Reproduce the cluster_worker gate logic so the diagnostic matches reality.
            rejected_by: list[str] = []
            if sb.visual < config.VISUAL_FLOOR:
                rejected_by.append("visual_floor")
            if sb.composite < config.CLUSTER_THRESHOLD:
                rejected_by.append("composite_threshold")

            entry = {
                "clip_id": clip_info["clip_id"],
                "lat": clip_info["lat"],
                "lng": clip_info["lng"],
                "ts": clip_info["ts"],
                "visual": round(sb.visual, 4),
                "gps": round(sb.gps, 4),
                "time": round(sb.time, 4),
                "composite": round(sb.composite, 4),
                "gps_available": sb.gps_available,
                "gps_distance_m": gps_distance_m,
                "time_delta_s": round(abs(clip_info["ts"] - c.median_ts), 1),
                "is_self": clip_info["own_cluster_id"] == c.id and c.member_count == 1,
                "rejected_by": rejected_by,
                "would_join": (not rejected_by),
            }

            if clip_info["own_cluster_id"] == c.id:
                # Legacy: this clip's score against its own cluster's centroid
                members.append({
                    "clip_id": entry["clip_id"],
                    "lat": entry["lat"],
                    "lng": entry["lng"],
                    "ts": entry["ts"],
                    "visual": entry["visual"],
                    "gps": entry["gps"],
                    "time": entry["time"],
                    "composite": entry["composite"],
                    "gps_available": entry["gps_available"],
                    "gps_distance_m": entry["gps_distance_m"],
                    "time_delta_s": entry["time_delta_s"],
                })
            else:
                # Cross-cluster: clip belongs to a DIFFERENT cluster — this is the
                # diagnostic line that exposes "why didn't clip X join cluster Y?"
                pairwise_scores.append(entry)

        clusters_out.append({
            "cluster_id": c.id,
            "member_count": c.member_count,
            "centroid_lat": c.centroid_lat,
            "centroid_lng": c.centroid_lng,
            "median_ts": c.median_ts,
            "members": members,
            "pairwise_scores": pairwise_scores,
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
    """Dev-only: counts + sample IDs straight from Postgres."""
    pool = db.get_pool()
    n_clips = await pool.fetchval("SELECT COUNT(*) FROM clips")
    n_clipped = await pool.fetchval(
        "SELECT COUNT(*) FROM clips WHERE cluster_id IS NOT NULL",
    )
    n_clusters = await pool.fetchval("SELECT COUNT(*) FROM clusters")
    sample_rows = await pool.fetch(
        "SELECT id, cluster_id FROM clips ORDER BY created_at DESC LIMIT 5",
    )
    cluster_rows = await pool.fetch("SELECT id, member_count FROM clusters")
    return {
        "backend": "postgres",
        "clips_total": n_clips,
        "clips_with_cluster_id": n_clipped,
        "clusters_total": n_clusters,
        "sample_clips": [dict(r) for r in sample_rows],
        "clusters": [dict(r) for r in cluster_rows],
    }


@app.get("/debug/clip/{clip_id}")
async def debug_clip(clip_id: str):
    """Dev-only: return the raw clip row from the DB."""
    clip = await db.get_clip(clip_id)
    if not clip:
        return {"found": False, "clip_id": clip_id}
    return {"found": True, "clip": clip}


async def _delete_paths_async(paths: list[str]) -> int:
    from . import storage  # local import — avoid circular
    n = 0
    for path_str in paths:
        try:
            await storage.delete_clip(path_str)
            n += 1
        except Exception as e:
            log.warning("admin_reset: could not delete %s: %s", path_str, e)
    return n


@app.post("/admin/reset", include_in_schema=False)
async def admin_reset(
    mode: str = Query("all", pattern="^(all|last|since)$"),
    count: int | None = Query(None, ge=1, le=10000),
    seconds: float | None = Query(None, gt=0),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
):
    """Destructive: wipe clips/embeddings/clusters/segments + their files.

    Auth: requires X-Admin-Token header matching env ADMIN_TOKEN. If
    ADMIN_TOKEN is unset on the server, returns 503 (closed by default).

    Modes:
      mode=all                — wipe everything (default)
      mode=last&count=N       — delete N most recent parent clips (cascades children/clusters/segments)
      mode=since&seconds=S    — delete parents uploaded within last S seconds
    """
    expected = config.ADMIN_TOKEN
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    # CR-01 — constant-time compare. Mirrors /metrics auth verbatim.
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="invalid admin token")

    if mode == "all":
        counts = await db.reset_all()
        deleted_files = 0
        # Phase 10 (D-15): mode=all physically scans the local clips dir, which
        # is empty in blob mode. The Blob-side bulk wipe relies on db.reset_all
        # truncating rows + Phase 11's cleanup hook for blocked clips. For the
        # v1.1 demo cutover (D-15) we accept stale Blob objects on mode=all —
        # the demo corpus is small and re-uploaded from fixtures.
        for p in (config.DATA_DIR / "clips").glob("*"):
            try:
                if p.is_file():
                    p.unlink()
                    deleted_files += 1
            except Exception as e:
                log.warning("admin_reset: could not delete %s: %s", p, e)
        result = {"mode": "all", "deleted": counts, "deleted_files": deleted_files}
    elif mode == "last":
        if count is None:
            raise HTTPException(status_code=400, detail="mode=last requires ?count=N")
        out = await db.delete_recent_clips(limit=count)
        deleted_files = await _delete_paths_async(out["paths_to_delete"])
        result = {
            "mode": "last",
            "count_requested": count,
            "deleted": out["counts"],
            "deleted_files": deleted_files,
        }
    else:  # since
        if seconds is None:
            raise HTTPException(status_code=400, detail="mode=since requires ?seconds=S")
        out = await db.delete_recent_clips(since_seconds=seconds)
        deleted_files = await _delete_paths_async(out["paths_to_delete"])
        result = {
            "mode": "since",
            "seconds": seconds,
            "deleted": out["counts"],
            "deleted_files": deleted_files,
        }

    from .pipeline import cluster as cluster_mod
    await cluster_mod.rebuild_cache()

    log.info("admin_reset %s", result)
    return result


# Phase 8 (D-09, D-10): /metrics endpoint mirrors /admin/reset auth verbatim.
# Same env var (ADMIN_TOKEN), same header (X-Admin-Token), same status codes
# (503 on empty token, 401 on mismatch). include_in_schema=False keeps it out
# of the public OpenAPI spec.
# WR-03: factory takes no argument; the route handler reads config.ADMIN_TOKEN
# per-request (mirrors /admin/reset behavior, survives in-process config reload).
app.add_api_route(
    "/metrics",
    make_metrics_endpoint(),
    methods=["GET"],
    include_in_schema=False,
)
