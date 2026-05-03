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
    composite = 0.40*cos + 0.40*gps + 0.20*time   (gps=0.0 when lat/lng unavailable)
    time = max(0, 1 - dt/14400)                   (4h linear decay; see TIME_WINDOW_S below)
    threshold = config.CLUSTER_THRESHOLD          (env-tunable, default 0.82)
    visual_floor = config.VISUAL_FLOOR            (env-tunable, default 0.70)
        Joining a cluster requires BOTH composite >= threshold AND visual >= visual_floor.
        Floor stops "same place, totally different thing in frame" from clustering on
        location alone; composite gate stops "same place, hours later" via the 4h time
        decay. Floor at 0.70 (down from 0.85, 2026-05-02) accommodates same-event-
        different-angle uploads where the same scene reads as visually different from
        another camera position (cafe interior shot vs. exterior of same cafe land in
        the 0.65–0.80 cosine band — 0.85 was rejecting these outright).
        Visual weight reduced 0.55 -> 0.40 and GPS raised 0.30 -> 0.40 (2026-05-02) so
        co-location is peer-equal with appearance — different angles of same scene are
        the dominant real-world case, not adversarial co-location which the floor still
        catches. Threshold held at 0.82 (raised from 0.70 in debug session
        clustering-false-positive-31h, 2026-05-01); the 4h time window does the heavy
        lifting against same-place-different-day uploads.
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
# 2026-05-02: rebalanced from (0.55/0.30/0.15) toward GPS so that same-event
# different-angle uploads (the dominant real-world case) cluster together when
# their visual cosine is depressed by framing/distance differences. The visual
# floor (config.VISUAL_FLOOR) still catches "same place, unrelated subject."
W_VISUAL = 0.40
W_GPS    = 0.40
W_TIME   = 0.20
GPS_RADIUS_M  = 50.0
# 4h linear decay (debug session clustering-false-positive-31h, 2026-05-01).
# Old 600s (10min) cliffed the time term to 0 past 10 minutes, so any same-place
# upload across hours/days saw composite = 0.55*cos + 0.30*gps + 0 — visual+gps
# alone could trivially clear the old 0.70 threshold even though "next day same
# room" isn't the same event. 4h matches realistic local-news event durations
# (rallies, fires, crowd reactions extending past initial flashpoint) while
# decaying to 0 well before "next day". Tuned alongside CLUSTER_THRESHOLD 0.82.
TIME_WINDOW_S = 14400.0


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
        # 1. Score against every active cluster. Pre-filter by visual floor so a
        # near-tie cluster with high GPS+time agreement but low visual cosine doesn't
        # win the "best" slot and then fail the gate (CLU-08 fix).
        best: tuple[ClusterCache, ScoreBreakdown] | None = None
        # near_miss tracks the highest-composite candidate REGARDLESS of floor so
        # we can report why a clip didn't join (debug-tuning aid, 2026-05-02).
        near_miss: tuple[ClusterCache, ScoreBreakdown] | None = None
        for c in CLUSTERS.values():
            sb = score_against(c, vec, lat, lng, ts)
            log.debug(
                "score clip_id=%s vs cluster_id=%s visual=%.3f gps=%.3f time=%.3f composite=%.3f gps_avail=%s floor=%.2f threshold=%.2f cleared_floor=%s",
                clip_id, c.id, sb.visual, sb.gps, sb.time, sb.composite,
                sb.gps_available, config.VISUAL_FLOOR, config.CLUSTER_THRESHOLD,
                sb.visual >= config.VISUAL_FLOOR,
            )
            if near_miss is None or sb.composite > near_miss[1].composite:
                near_miss = (c, sb)
            if sb.visual < config.VISUAL_FLOOR:
                continue  # ineligible: cluster fails visual floor for this clip
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
            if near_miss is not None:
                nm_cluster, nm_sb = near_miss
                reason = (
                    "below_floor" if nm_sb.visual < config.VISUAL_FLOOR
                    else "below_threshold"
                )
                log.info(
                    "cluster near-miss clip_id=%s best_cluster_id=%s reason=%s "
                    "visual=%.3f gps=%.3f time=%.3f composite=%.3f floor=%.2f threshold=%.2f",
                    clip_id, nm_cluster.id, reason,
                    nm_sb.visual, nm_sb.gps, nm_sb.time, nm_sb.composite,
                    config.VISUAL_FLOOR, config.CLUSTER_THRESHOLD,
                )
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
