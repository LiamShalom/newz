"""Phase 9 (D-07): asyncpg implementation of backend.db_sqlite functions.

Signature parity contract: every public name in `__all__` matches db_sqlite.__all__
byte-for-byte (D-07). Per-request branching is forbidden (D-08); the dispatcher in
backend/db.py picks this module once at import time when METADATA_BACKEND=postgres
and OFFLINE_DEMO is unset (D-11).

Pool lifecycle: init_pool() in app.lifespan startup; close_pool() in shutdown.
Module-level _pool singleton; --workers 1 (L-02) makes inter-process coordination
unnecessary.

Schema is owned by Alembic (backend/migrations); init() is a no-op for postgres
(09-05 ships the initial migration that lands all 7 v1.1 tables).
"""

import json
import logging
import time
import uuid
from pathlib import Path

import asyncpg
import numpy as np
from fastapi import UploadFile

from . import config

log = logging.getLogger(__name__)

__all__ = [
    # Constants (db_sqlite parity stubs)
    "DB_PATH", "CLIPS_DIR",
    # Sync helpers
    "ext_from_mime",
    # Init
    "init",
    # Postgres-specific lifecycle (NOT in db_sqlite.py — exported for app.lifespan)
    "init_pool", "close_pool", "get_pool",
    # Clips CRUD
    "insert_clip", "get_clip", "fetch_recent_clips",
    # Embeddings
    "store_embedding", "get_embedding",
    # Clusters
    "get_all_clusters", "upsert_cluster", "assign_clip_to_cluster",
    "get_cluster", "count_distinct_parents_in_cluster",
    # Segments
    "insert_segment", "fetch_recent_segments", "get_segment_for_cluster",
    # Compile lock
    "set_compile_in_flight", "is_compile_in_flight",
    # Cluster clip queries
    "fetch_cluster_clips", "fetch_cluster_clips_with_children",
    # Children
    "insert_child_clip", "get_children_by_parent",
    # Admin
    "reset_all", "delete_recent_clips",
]

# Stubbed for db_sqlite parity. CLIPS_DIR is still consumed by /media StaticFiles
# in Phase 9; Phase 10 retires that mount when blob storage lands.
DB_PATH: "Path | None" = None  # postgres has no file path
CLIPS_DIR: Path = config.DATA_DIR / "clips"

# Module-level pool singleton — process-wide; --workers 1 makes this safe.
_pool: "asyncpg.Pool | None" = None


# ---------------------------------------------------------------------------
# Pool lifecycle (D-16)
# ---------------------------------------------------------------------------

def get_pool() -> asyncpg.Pool:
    """Return the process-wide asyncpg pool. Raises if init_pool was not called.

    Called by every db_postgres function — must be invoked AFTER lifespan startup.
    """
    if _pool is None:
        raise RuntimeError(
            "asyncpg pool not initialized — backend.app.lifespan must call init_pool() first"
        )
    return _pool


async def init_pool() -> None:
    """Create the process-wide asyncpg pool (D-16). Called from app.lifespan startup.

    Pool config:
      - dsn: config.DATABASE_URL (Neon DIRECT endpoint; sslmode=require parsed natively).
        RESEARCH Pitfall 1: do NOT use the -pooler endpoint; PgBouncer breaks asyncpg's
        prepared-statement cache.
      - min_size=1: allow scale-to-zero of idle connections.
      - max_size=10: L-02 / DB-07. --workers 1 makes process-singleton sufficient.
      - statement_cache_size: leave at default (100). Setting 0 only needed against -pooler.
    """
    global _pool
    if _pool is not None:
        log.warning("init_pool called twice; ignoring second call")
        return
    if not config.DATABASE_URL:
        # Fail-loud: this branch is only reached when METADATA_BACKEND=postgres and
        # OFFLINE_DEMO=false (dispatcher enforces). Empty DATABASE_URL is a deploy bug.
        raise RuntimeError(
            "DATABASE_URL is empty but METADATA_BACKEND=postgres and OFFLINE_DEMO=false. "
            "Set DATABASE_URL or flip METADATA_BACKEND=sqlite to use the SQLite path."
        )
    try:
        _pool = await asyncpg.create_pool(
            dsn=config.DATABASE_URL,
            min_size=1,
            max_size=10,
        )
        log.info("asyncpg pool created min=1 max=10")
    except Exception as exc:
        # Sanitize: never log the DSN itself (RESEARCH §Security: DATABASE_URL leak via log).
        log.error("asyncpg pool init failed: %s (DSN redacted)", type(exc).__name__)
        raise


async def close_pool() -> None:
    """Close the process-wide asyncpg pool. Called from app.lifespan shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("asyncpg pool closed")


# ---------------------------------------------------------------------------
# Init no-op + sync helper
# ---------------------------------------------------------------------------

_MIME_EXT = {"video/mp4": "mp4", "video/webm": "webm"}


def ext_from_mime(mime: str | None) -> str:
    if not mime:
        return "webm"
    base = mime.split(";")[0].strip().lower()
    return _MIME_EXT.get(base, "webm")


async def init() -> None:
    """Schema is owned by Alembic migrations (run by Railway preDeployCommand).

    Phase 9 keeps init() in the public surface for db_sqlite parity (D-07);
    postgres branch is a no-op + log line. The DATA_DIR / CLIPS_DIR mkdirs are
    still useful because /media StaticFiles serves files from CLIPS_DIR until
    Phase 10's blob migration lands.
    """
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    log.info("db_postgres.init: noop (schema owned by alembic)")


# ---------------------------------------------------------------------------
# Clips CRUD
# ---------------------------------------------------------------------------

async def insert_clip(
    file: UploadFile,
    lat: float,
    lng: float,
    ts: float,
    session_id: str | None,
) -> str:
    from . import storage  # local import — avoid circular at module load
    clip_id = uuid.uuid4().hex
    ext = ext_from_mime(file.content_type)
    contents = await file.read()
    result = await storage.save_clip_bytes(clip_id, ext, contents)
    is_blob_url = result.startswith("http")
    now = time.time()
    pool = get_pool()
    await pool.execute(
        "INSERT INTO clips (id, path, blob_url, lat, lng, ts, session_id, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        clip_id,
        None if is_blob_url else result,
        result if is_blob_url else None,
        lat, lng, ts, session_id, now,
    )
    log.info("insert_clip id=%s bytes=%d", clip_id, len(contents))
    return clip_id


async def get_clip(clip_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM clips WHERE id = $1", clip_id)
    return dict(row) if row else None


async def fetch_recent_clips(limit: int = 50) -> list[dict]:
    from . import storage  # local import — avoid circular at module load
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, path, blob_url, lat, lng, ts, created_at FROM clips "
        "ORDER BY created_at DESC LIMIT $1",
        limit,
    )
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "url": storage.get_playable_url(dict(r)),
            "lat": r["lat"],
            "lng": r["lng"],
            "ts": r["ts"],
            "created_at": r["created_at"],
        })
    return out


# ---------------------------------------------------------------------------
# Embeddings (BYTEA round-trip; Pitfall 5 — defensive bytes() cast on read)
# ---------------------------------------------------------------------------

async def store_embedding(clip_id: str, vec: np.ndarray, latency_ms: int) -> None:
    blob = vec.astype(np.float32).tobytes()
    now = time.time()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO clip_embeddings (clip_id, vector, latency_ms, created_at) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (clip_id) DO UPDATE SET "
                "  vector = EXCLUDED.vector, "
                "  latency_ms = EXCLUDED.latency_ms, "
                "  created_at = EXCLUDED.created_at",
                clip_id, blob, latency_ms, now,
            )
            await conn.execute(
                "UPDATE clips SET embedding_status='done', embed_latency_ms=$1 WHERE id=$2",
                latency_ms, clip_id,
            )


async def get_embedding(clip_id: str) -> np.ndarray | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT vector FROM clip_embeddings WHERE clip_id = $1", clip_id,
    )
    if row is None:
        return None
    # Pitfall 5: defensive bytes() cast handles asyncpg memoryview returns.
    return np.frombuffer(bytes(row["vector"]), dtype=np.float32).copy()


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

async def get_all_clusters() -> list[dict]:
    """Read all clusters with member_ids populated from clips.cluster_id JOIN.

    Used by lifespan rebuild (CLU-10). Same shape as db_sqlite.get_all_clusters.
    """
    pool = get_pool()
    cluster_rows = [
        dict(r) for r in await pool.fetch(
            "SELECT id, centroid, centroid_lat, centroid_lng, median_ts, "
            "member_count, created_at FROM clusters"
        )
    ]
    # Pitfall 5: defensive bytes() cast on BYTEA centroid column for memoryview safety.
    for c in cluster_rows:
        if c["centroid"] is not None:
            c["centroid"] = bytes(c["centroid"])
    clip_rows = await pool.fetch(
        "SELECT id, cluster_id FROM clips WHERE cluster_id IS NOT NULL"
    )
    members: dict[str, list[str]] = {}
    for r in clip_rows:
        members.setdefault(r["cluster_id"], []).append(r["id"])
    for c in cluster_rows:
        c["member_ids"] = members.get(c["id"], [])
    return cluster_rows


async def upsert_cluster(cluster) -> None:
    """Insert or update a cluster row. Centroid stored as float32 BYTEA.

    cluster has attributes: id (str), centroid (np.ndarray float32),
    centroid_lat (float|None), centroid_lng (float|None),
    median_ts (float), member_count (int).
    """
    blob = cluster.centroid.astype(np.float32).tobytes()
    now = time.time()
    pool = get_pool()
    await pool.execute(
        """INSERT INTO clusters
             (id, centroid, centroid_lat, centroid_lng, median_ts,
              member_count, created_at, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           ON CONFLICT(id) DO UPDATE SET
             centroid=EXCLUDED.centroid,
             centroid_lat=EXCLUDED.centroid_lat,
             centroid_lng=EXCLUDED.centroid_lng,
             median_ts=EXCLUDED.median_ts,
             member_count=EXCLUDED.member_count,
             updated_at=EXCLUDED.updated_at""",
        cluster.id, blob, cluster.centroid_lat, cluster.centroid_lng,
        cluster.median_ts, cluster.member_count, now, now,
    )


async def assign_clip_to_cluster(clip_id: str, cluster_id: str) -> None:
    """Set clips.cluster_id for an already-inserted clip."""
    pool = get_pool()
    await pool.execute(
        "UPDATE clips SET cluster_id = $1 WHERE id = $2", cluster_id, clip_id,
    )


# ---------------------------------------------------------------------------
# Segments (Phase 4)
# ---------------------------------------------------------------------------

async def insert_segment(
    cluster_id: str,
    ordered_clip_ids: list[str],
    caption: str,
    location: str,
    source_count: int,
    video_url: str | None = None,
    title: str | None = None,
) -> str:
    """Idempotent: one segment per cluster. ON CONFLICT(cluster_id) updates. CMP-09."""
    seg_id = uuid.uuid4().hex
    now = time.time()
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO segments
             (id, cluster_id, ordered_clip_ids, title, caption, location,
              source_count, created_at, video_url)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT(cluster_id) DO UPDATE SET
             ordered_clip_ids = EXCLUDED.ordered_clip_ids,
             title            = EXCLUDED.title,
             caption          = EXCLUDED.caption,
             location         = EXCLUDED.location,
             source_count     = EXCLUDED.source_count,
             video_url        = EXCLUDED.video_url
           RETURNING id""",
        seg_id, cluster_id, json.dumps(ordered_clip_ids),
        title, caption, location, source_count, now, video_url,
    )
    return row["id"]


async def fetch_recent_segments(limit: int = 50) -> list[dict]:
    """JOIN segments + clusters; batch-fetch all ordered clip paths for sequential playback."""
    from . import storage  # local import — avoid circular at module load
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT s.id, s.cluster_id, s.ordered_clip_ids, s.title, s.caption,
                  s.location, c.member_count AS source_count, s.created_at,
                  c.centroid_lat, c.centroid_lng, s.video_url AS stored_video_url
           FROM segments s
           JOIN clusters c ON c.id = s.cluster_id
           ORDER BY s.created_at DESC LIMIT $1""",
        limit,
    )
    all_ids: list[str] = []
    parsed_rows: list[tuple] = []
    for r in rows:
        ids = json.loads(r["ordered_clip_ids"])
        all_ids.extend(ids)
        parsed_rows.append((r, ids))
    clip_row_map: dict[str, dict] = {}
    if all_ids:
        # WHERE id = ANY($1::text[]) replaces the SQLite IN ({placeholders}) pattern;
        # asyncpg sends the Python list as a Postgres array.
        path_rows = await pool.fetch(
            "SELECT id, path, blob_url FROM clips WHERE id = ANY($1::text[])",
            all_ids,
        )
        for p in path_rows:
            clip_row_map[p["id"]] = dict(p)
    blob_mode = config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO
    out = []
    for r, ids in parsed_rows:
        def _url(clip_id: str) -> str | None:
            # Phase 4.6: ordered_clip_ids may be run IDs (`{parent}_run_{n}`).
            # Phase 10: in blob mode, run videos live at runs/{run_id}.mp4 on the
            # public store (constructed via storage.runs_public_url) — the old
            # `/media/{run_id}.mp4` 404s because the StaticFiles mount is not
            # registered. Parent-clip rows hold a PRIVATE blob URL that the
            # browser cannot fetch (no Authorization header on <video src=>);
            # return None so the frontend renders "Compiling…" instead of a
            # black <video> element.
            if "_run_" in clip_id:
                return storage.runs_public_url(clip_id)
            if blob_mode:
                return None
            row = clip_row_map.get(clip_id)
            if not row:
                return None
            return storage.get_playable_url(row)
        video_urls = [_url(cid) for cid in ids]
        out.append({
            "id": r["id"],
            "cluster_id": r["cluster_id"],
            "ordered_clip_ids": ids,
            "title": r["title"],
            "caption": r["caption"],
            "location": r["location"],
            "source_count": r["source_count"],
            "created_at": r["created_at"],
            "centroid_lat": r["centroid_lat"],
            "centroid_lng": r["centroid_lng"],
            "video_url": r["stored_video_url"] if r["stored_video_url"] else (video_urls[0] if video_urls else None),
            "video_urls": video_urls,
        })
    return out


async def get_segment_for_cluster(cluster_id: str) -> dict | None:
    """SELECT from segments WHERE cluster_id=$1; returns dict or None."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM segments WHERE cluster_id = $1", cluster_id,
    )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Compile lock (CAS via UPDATE rowcount; asyncpg returns command tag string)
# ---------------------------------------------------------------------------

async def set_compile_in_flight(cluster_id: str, value: bool, ttl_seconds: float = 30.0) -> bool:
    """Atomic compare-and-set. Returns True if lock acquired/cleared, False if already held.

    SQLite returned `cursor.rowcount`; asyncpg returns the command tag string
    ("UPDATE 1" / "UPDATE 0"). Parse via tag.endswith(" 1").
    """
    now = time.time()
    pool = get_pool()
    if value:
        tag = await pool.execute(
            """UPDATE clusters
               SET compile_in_flight = 1, last_compile_at = $1
               WHERE id = $2
                 AND (compile_in_flight = 0 OR last_compile_at < $3)""",
            now, cluster_id, now - ttl_seconds,
        )
        return tag.endswith(" 1")
    else:
        await pool.execute(
            "UPDATE clusters SET compile_in_flight = 0 WHERE id = $1",
            cluster_id,
        )
        return True


async def is_compile_in_flight(cluster_id: str, ttl_seconds: float = 30.0) -> bool:
    """Returns True only if compile_in_flight=1 AND last_compile_at is within ttl_seconds."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT compile_in_flight, last_compile_at FROM clusters WHERE id = $1",
        cluster_id,
    )
    if not row:
        return False
    flag, last = row["compile_in_flight"], row["last_compile_at"]
    if not flag:
        return False
    if last is None or time.time() - last > ttl_seconds:
        return False
    return True


# ---------------------------------------------------------------------------
# Cluster clip queries
# ---------------------------------------------------------------------------

async def fetch_cluster_clips(cluster_id: str) -> list[dict]:
    """SELECT clips where cluster_id=$1 ORDER BY ts ASC; includes id, path, lat, lng, ts."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, path, lat, lng, ts FROM clips WHERE cluster_id = $1 ORDER BY ts ASC",
        cluster_id,
    )
    return [dict(r) for r in rows]


async def fetch_cluster_clips_with_children(cluster_id: str) -> list[dict]:
    """Return parent rows in this cluster + their children (walk via parent_id).

    Phase 4.6 (Pivot 1) port: children no longer carry a cluster_id. Two-step walk:
      A) find parent ids (parent_id IS NULL) in this cluster
      B) fetch those parents themselves PLUS any rows whose parent_id is in (A)

    Output rows preserve the v1.0 shape (id, path, parent_path, lat, lng, ts,
    parent_id, start_offset_sec, end_offset_sec) so compile.py and the Angle
    Selector MCP tool stay backward compatible.

    Note: the SQLite version used `IN ({placeholders})` with `parent_ids + parent_ids`.
    asyncpg uses `ANY($1::text[])` against a single array argument.
    """
    pool = get_pool()
    # Step A: parent rows in this cluster
    parent_rows = [
        dict(r) for r in await pool.fetch(
            """SELECT id, path, blob_url, lat, lng, ts
               FROM clips
               WHERE cluster_id = $1 AND parent_id IS NULL
               ORDER BY ts ASC""",
            cluster_id,
        )
    ]
    parent_ids = [p["id"] for p in parent_rows]
    parent_path_map: dict[str, str] = {p["id"]: p["path"] for p in parent_rows}
    parent_blob_url_map: dict[str, str | None] = {p["id"]: p.get("blob_url") for p in parent_rows}

    if not parent_ids:
        return []

    # Step B: parents themselves + any child of those parents.
    rows = await pool.fetch(
        """SELECT id, path, blob_url, lat, lng, ts, parent_id,
                  start_offset_sec, end_offset_sec
           FROM clips
           WHERE id = ANY($1::text[])
              OR parent_id = ANY($1::text[])
           ORDER BY ts ASC, start_offset_sec ASC""",
        parent_ids,
    )

    out = []
    for r in rows:
        parent_path = (
            parent_path_map.get(r["parent_id"], "")
            if r["parent_id"]
            else r["path"]
        )
        parent_blob_url = (
            parent_blob_url_map.get(r["parent_id"])
            if r["parent_id"]
            else r["blob_url"]
        )
        out.append({
            "id": r["id"],
            "path": r["path"] or parent_path,
            "parent_path": parent_path,
            "parent_blob_url": parent_blob_url,
            "lat": r["lat"],
            "lng": r["lng"],
            "ts": r["ts"],
            "parent_id": r["parent_id"],
            "start_offset_sec": r["start_offset_sec"] or 0.0,
            "end_offset_sec": r["end_offset_sec"],
        })
    return out


async def get_cluster(cluster_id: str) -> dict | None:
    """SELECT from clusters WHERE id=$1; includes member_count, compile_in_flight, last_compile_at."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM clusters WHERE id = $1", cluster_id)
    return dict(row) if row else None


async def count_distinct_parents_in_cluster(cluster_id: str) -> int:
    """Pivot 2 gate: count parent (parent_id IS NULL) clip rows in this cluster.

    Defensive — under Pivot 1 cluster.member_count already equals this value
    (children never get a cluster_id), but if cluster_id ever leaks onto a
    child row this query stays correct.
    """
    pool = get_pool()
    n = await pool.fetchval(
        "SELECT COUNT(*) FROM clips WHERE cluster_id = $1 AND parent_id IS NULL",
        cluster_id,
    )
    return int(n) if n is not None else 0


# ---------------------------------------------------------------------------
# Phase 4.5: child clip helpers
# ---------------------------------------------------------------------------

async def insert_child_clip(
    parent_id: str,
    start_offset_sec: float,
    end_offset_sec: float,
    lat: float,
    lng: float,
    ts: float,
    session_id: str | None,
) -> str:
    """Insert a 3s child clip row. Child inherits lat/lng/ts/session_id from parent.

    Child id is deterministic: f"{parent_id}_child_{int(start_offset_sec)}".
    Child path is "" — children reference parent's file + use offsets for ffmpeg.
    INSERT OR IGNORE → ON CONFLICT DO NOTHING.
    """
    child_id = f"{parent_id}_child_{int(start_offset_sec)}"
    now = time.time()
    pool = get_pool()
    await pool.execute(
        """INSERT INTO clips
             (id, path, lat, lng, ts, session_id, created_at, parent_id,
              start_offset_sec, end_offset_sec, embedding_status)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending')
           ON CONFLICT DO NOTHING""",
        child_id, "", lat, lng, ts, session_id, now,
        parent_id, start_offset_sec, end_offset_sec,
    )
    log.info(
        "insert_child_clip child_id=%s parent_id=%s start=%.1f end=%.1f",
        child_id, parent_id, start_offset_sec, end_offset_sec,
    )
    return child_id


async def get_children_by_parent(parent_id: str) -> list[dict]:
    """Return all child clip rows for a given parent_id, ordered by start_offset_sec ASC."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, parent_id, start_offset_sec, end_offset_sec, lat, lng, ts, session_id "
        "FROM clips WHERE parent_id = $1 ORDER BY start_offset_sec ASC",
        parent_id,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Admin: destructive reset helpers
# ---------------------------------------------------------------------------

async def reset_all() -> dict:
    """Wipe clips, embeddings, clusters, segments. Returns row counts deleted.

    File cleanup (CLIPS_DIR) and CLUSTERS cache rebuild are caller's responsibility.

    Note on tbl interpolation: f-string in the SELECT is safe — the iterable is a
    hardcoded tuple of literal table names, never user data.
    """
    counts: dict[str, int] = {}
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for tbl in ("clips", "clip_embeddings", "clusters", "segments"):
                counts[tbl] = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
            # Order respects FK self-ref on clips(parent_id): single DELETE truncates fine.
            await conn.execute("DELETE FROM segments")
            await conn.execute("DELETE FROM clip_embeddings")
            await conn.execute("DELETE FROM clips")
            await conn.execute("DELETE FROM clusters")
    return counts


async def delete_recent_clips(
    limit: int | None = None,
    since_seconds: float | None = None,
) -> dict:
    """Delete most-recent parent clips and cascade their children, embeddings,
    plus any now-empty clusters and their segments.

    Pass exactly one of `limit` or `since_seconds`.

    Returns {"counts": {...}, "paths_to_delete": [str, ...]} — caller deletes
    files from disk and rebuilds CLUSTERS cache.

    Pitfall 6 discipline: every `pool.acquire()` block contains only DB statements;
    no non-DB awaits live inside the transaction.
    """
    if (limit is None) == (since_seconds is None):
        raise ValueError("pass exactly one of limit or since_seconds")

    counts = {"clips": 0, "embeddings": 0, "segments": 0, "clusters": 0}
    paths_to_delete: list[str] = []

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if limit is not None:
                parents_raw = await conn.fetch(
                    "SELECT id, path, blob_url, cluster_id FROM clips "
                    "WHERE parent_id IS NULL "
                    "ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
            else:
                assert since_seconds is not None
                cutoff = time.time() - float(since_seconds)
                parents_raw = await conn.fetch(
                    "SELECT id, path, blob_url, cluster_id FROM clips "
                    "WHERE parent_id IS NULL AND created_at >= $1",
                    cutoff,
                )
            parents = [dict(r) for r in parents_raw]
            if not parents:
                return {"counts": counts, "paths_to_delete": paths_to_delete}

            parent_ids = [p["id"] for p in parents]
            affected_clusters = sorted({p["cluster_id"] for p in parents if p["cluster_id"]})
            # Phase 10: blob_url takes precedence over path. admin/reset routes
            # URL-shaped entries through the storage dispatcher (Task 2.4).
            for p in parents:
                target = p.get("blob_url") or p.get("path")
                if target:
                    paths_to_delete.append(target)

            child_rows = await conn.fetch(
                "SELECT id FROM clips WHERE parent_id = ANY($1::text[])",
                parent_ids,
            )
            child_ids = [r["id"] for r in child_rows]
            all_clip_ids = parent_ids + child_ids

            # Capture run-output files (data/clips/{run_id}.mp4) referenced by
            # affected segments before we delete those segments.
            if affected_clusters:
                seg_rows = await conn.fetch(
                    "SELECT ordered_clip_ids FROM segments WHERE cluster_id = ANY($1::text[])",
                    affected_clusters,
                )
                for row in seg_rows:
                    for cid in json.loads(row["ordered_clip_ids"]):
                        if "_run_" in cid:
                            paths_to_delete.append(str(CLIPS_DIR / f"{cid}.mp4"))

            tag = await conn.execute(
                "DELETE FROM clip_embeddings WHERE clip_id = ANY($1::text[])",
                all_clip_ids,
            )
            # asyncpg returns "DELETE N" command tag; parse trailing int.
            counts["embeddings"] = int(tag.split()[-1]) if tag and tag.startswith("DELETE") else 0

            if child_ids:
                await conn.execute(
                    "DELETE FROM clips WHERE id = ANY($1::text[])", child_ids,
                )
            await conn.execute(
                "DELETE FROM clips WHERE id = ANY($1::text[])", parent_ids,
            )
            counts["clips"] = len(parent_ids) + len(child_ids)

            if affected_clusters:
                still_rows = await conn.fetch(
                    """SELECT cluster_id, COUNT(*) AS c
                       FROM clips
                       WHERE cluster_id = ANY($1::text[]) AND parent_id IS NULL
                       GROUP BY cluster_id""",
                    affected_clusters,
                )
                still_populated = {r["cluster_id"]: r["c"] for r in still_rows}
                empty = [cid for cid in affected_clusters if cid not in still_populated]

                now = time.time()
                for cid, cnt in still_populated.items():
                    await conn.execute(
                        "UPDATE clusters SET member_count = $1, updated_at = $2 WHERE id = $3",
                        cnt, now, cid,
                    )

                if empty:
                    seg_tag = await conn.execute(
                        "DELETE FROM segments WHERE cluster_id = ANY($1::text[])", empty,
                    )
                    counts["segments"] = (
                        int(seg_tag.split()[-1])
                        if seg_tag and seg_tag.startswith("DELETE")
                        else 0
                    )
                    cl_tag = await conn.execute(
                        "DELETE FROM clusters WHERE id = ANY($1::text[])", empty,
                    )
                    counts["clusters"] = (
                        int(cl_tag.split()[-1])
                        if cl_tag and cl_tag.startswith("DELETE")
                        else 0
                    )

    return {"counts": counts, "paths_to_delete": paths_to_delete}
