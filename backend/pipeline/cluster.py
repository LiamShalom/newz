"""
backend/pipeline/cluster.py — composite-score clustering stage (Phase 3).

Public API:
    cluster_worker(clip_id, vec) -> str
        Async entry point. Called by run_pipeline() AFTER embed_worker.
        Joins clip to best-matching cluster or creates a new one. Returns cluster_id.
    rebuild_cache() -> None
        Repopulate module-level CLUSTERS dict from sqlite. Called from app.lifespan
        BEFORE the server accepts work (CLU-10).

Module state:
    CLUSTERS: dict[str, ClusterCache]  -- in-memory active cluster cache
    _LOCK: asyncio.Lock                -- serializes the score-and-mutate critical section

Math (locked by CLAUDE.md + CONTEXT D-04/D-05/D-06):
    composite = 0.55*cos + 0.30*gps + 0.15*time   (gps=0.0 when lat/lng unavailable)
    threshold = config.CLUSTER_THRESHOLD          (env-tunable, default 0.55)
    centroid update: Welford running mean (float64 intermediate), re-normalized to unit length, stored as float32
"""

import asyncio
import logging
import math
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from .. import config, db, events

log = logging.getLogger(__name__)

# Composite weights (locked — do not change without updating CLAUDE.md + CONTEXT.md)
W_VISUAL = 0.55
W_GPS    = 0.30
W_TIME   = 0.15
GPS_RADIUS_M  = 200.0
TIME_WINDOW_S = 600.0


@dataclass
class ScoreBreakdown:
    visual: float        # cosine in [0,1]
    gps: float           # 1 - dist/200, in [0,1]; 0.0 when GPS unavailable
    time: float          # 1 - dt/600, in [0,1]
    composite: float     # un-renormalized weighted sum (per D-06)
    gps_available: bool


@dataclass
class ClusterCache:
    id: str
    centroid: np.ndarray             # 512-d float32 unit vector
    centroid_lat: float | None       # None when first-clip GPS was unavailable
    centroid_lng: float | None
    median_ts: float
    member_count: int
    member_ids: list[str] = field(default_factory=list)


CLUSTERS: dict[str, ClusterCache] = {}
_LOCK: asyncio.Lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in meters. No haversine-package dep (CLAUDE.md hard constraint)."""
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def update_centroid(old_centroid: np.ndarray, new_vec: np.ndarray, new_count: int) -> np.ndarray:
    """Welford running mean in float64, re-normalized, returned as float32.

    Formula: c_n = c_{n-1} + (v - c_{n-1}) / n   (numerically stable form)
    Then re-normalize so the unit-vector cosine identity stays valid.
    """
    old64 = old_centroid.astype(np.float64)
    new64 = new_vec.astype(np.float64)
    updated = old64 + (new64 - old64) / new_count
    updated /= np.linalg.norm(updated) + 1e-12
    return updated.astype(np.float32)


def _running_mean(old: float, new: float, count: int) -> float:
    return old + (new - old) / count


def score_against(cluster: ClusterCache, vec: np.ndarray,
                  lat: float | None, lng: float | None, ts: float) -> ScoreBreakdown:
    """Composite-score one clip against one cluster's centroid. CLU-02/03/04/06."""
    cos = max(0.0, float(np.dot(vec, cluster.centroid)))   # both unit vectors
    if (lat is not None and lng is not None
            and cluster.centroid_lat is not None and cluster.centroid_lng is not None):
        d_m = haversine_m(lat, lng, cluster.centroid_lat, cluster.centroid_lng)
        gps = max(0.0, 1.0 - d_m / GPS_RADIUS_M)
        gps_avail = True
    else:
        gps = 0.0          # CLU-06: collapse to 0; un-renormalized per D-06
        gps_avail = False
    delta_s = abs(ts - cluster.median_ts)
    tim = max(0.0, 1.0 - delta_s / TIME_WINDOW_S)
    composite = W_VISUAL * cos + W_GPS * gps + W_TIME * tim
    return ScoreBreakdown(visual=cos, gps=gps, time=tim, composite=composite, gps_available=gps_avail)


# ---------------------------------------------------------------------------
# Async public entry point
# ---------------------------------------------------------------------------

async def cluster_worker(clip_id: str, vec: np.ndarray) -> str:
    """Phase 3 entry. Returns cluster_id (joined or newly created)."""
    clip = await db.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"cluster_worker: clip {clip_id!r} not found")
    lat, lng, ts = clip["lat"], clip["lng"], clip["ts"]

    breakdown: ScoreBreakdown | None = None
    is_new = False
    cluster_id: str

    async with _LOCK:
        # 1. Score against every active cluster
        best: tuple[ClusterCache, ScoreBreakdown] | None = None
        for c in CLUSTERS.values():
            sb = score_against(c, vec, lat, lng, ts)
            if best is None or sb.composite > best[1].composite:
                best = (c, sb)

        if best is not None and best[1].composite >= config.CLUSTER_THRESHOLD:
            # JOIN existing cluster
            cluster, breakdown = best
            new_count = cluster.member_count + 1
            new_centroid = update_centroid(cluster.centroid, vec, new_count)

            # Running mean of GPS only when BOTH old and new have it; else preserve old
            if lat is not None and cluster.centroid_lat is not None:
                new_lat = _running_mean(cluster.centroid_lat, lat, new_count)
            else:
                new_lat = cluster.centroid_lat
            if lng is not None and cluster.centroid_lng is not None:
                new_lng = _running_mean(cluster.centroid_lng, lng, new_count)
            else:
                new_lng = cluster.centroid_lng

            new_median_ts = _running_mean(cluster.median_ts, ts, new_count)

            updated = ClusterCache(
                id=cluster.id,
                centroid=new_centroid,
                centroid_lat=new_lat,
                centroid_lng=new_lng,
                median_ts=new_median_ts,
                member_count=new_count,
                member_ids=cluster.member_ids + [clip_id],
            )
            # Persist FIRST, then mutate cache (Pitfall 6)
            await db.upsert_cluster(updated)
            await db.assign_clip_to_cluster(clip_id, cluster.id)
            CLUSTERS[cluster.id] = updated
            cluster_id = cluster.id
        else:
            # CREATE new cluster
            cluster_id = uuid.uuid4().hex
            new_cluster = ClusterCache(
                id=cluster_id,
                centroid=vec.astype(np.float32),
                centroid_lat=lat,
                centroid_lng=lng,
                median_ts=ts,
                member_count=1,
                member_ids=[clip_id],
            )
            await db.upsert_cluster(new_cluster)
            await db.assign_clip_to_cluster(clip_id, cluster_id)
            CLUSTERS[cluster_id] = new_cluster
            is_new = True

    # 2. Broadcast OUTSIDE the lock (events.broadcast may yield to other coroutines)
    payload: dict = {
        "type": "cluster_assigned",
        "clip_id": clip_id,
        "cluster_id": cluster_id,
        "is_new_cluster": is_new,
        "member_count": CLUSTERS[cluster_id].member_count,
        "score_breakdown": (
            None if breakdown is None
            else {
                "visual": round(breakdown.visual, 4),
                "gps": round(breakdown.gps, 4),
                "time": round(breakdown.time, 4),
                "composite": round(breakdown.composite, 4),
                "gps_available": breakdown.gps_available,
                "threshold": config.CLUSTER_THRESHOLD,
            }
        ),
    }
    await events.broadcast(payload)
    log.info("cluster_worker clip_id=%s cluster_id=%s new=%s composite=%s",
             clip_id, cluster_id, is_new,
             "n/a" if breakdown is None else f"{breakdown.composite:.3f}")
    return cluster_id


# ---------------------------------------------------------------------------
# Lifespan rebuild
# ---------------------------------------------------------------------------

async def rebuild_cache() -> None:
    """CLU-10: rebuild CLUSTERS dict from sqlite on lifespan startup."""
    rows = await db.get_all_clusters()
    CLUSTERS.clear()
    for row in rows:
        cc = ClusterCache(
            id=row["id"],
            centroid=np.frombuffer(row["centroid"], dtype=np.float32).copy(),
            centroid_lat=row["centroid_lat"],
            centroid_lng=row["centroid_lng"],
            median_ts=row["median_ts"],
            member_count=row["member_count"],
            member_ids=row["member_ids"],
        )
        CLUSTERS[cc.id] = cc
    log.info("clusters: rebuilt %d from sqlite", len(CLUSTERS))
