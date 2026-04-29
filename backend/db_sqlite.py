"""SQLite metadata backend — kept as the OFFLINE_DEMO fallback path only.

Slated for retirement once the Neon cutover stabilizes. Drop plan: delete this
file + simplify backend/db.py to a direct `from .db_postgres import *`, drop
aiosqlite from requirements.txt, and decide what OFFLINE_DEMO does without
SQLite (in-memory stub vs. retire the flag entirely). See STATE.md Pending
Todos. Don't add new SQLite-only behavior here — only signature parity with
db_postgres.py to keep the dispatcher healthy until removal.
"""
import json
import logging
import time
import uuid
from pathlib import Path

import aiosqlite
import numpy as np
from fastapi import UploadFile

from . import config

log = logging.getLogger(__name__)

DB_PATH = config.DATA_DIR / "newz.db"
CLIPS_DIR = config.DATA_DIR / "clips"

__all__ = [
    # Constants
    "DB_PATH", "CLIPS_DIR",
    # Sync helpers
    "ext_from_mime",
    # Init
    "init",
    # Clips CRUD
    "insert_clip", "get_clip", "fetch_recent_clips",
    # Embeddings
    "store_embedding", "get_embedding",
    # Clusters
    "get_all_clusters", "upsert_cluster", "assign_clip_to_cluster",
    "get_cluster", "count_distinct_parents_in_cluster",
    # Segments
    "insert_segment", "fetch_recent_segments", "get_segment_for_cluster",
    "get_segment_by_id",
    # Comments (Phase 01 feature track)
    "insert_comment", "list_comments", "count_comments_since",
    # Compile lock
    "set_compile_in_flight", "is_compile_in_flight",
    # Cluster clip queries
    "fetch_cluster_clips", "fetch_cluster_clips_with_children",
    # Children
    "insert_child_clip", "get_children_by_parent",
    # Admin
    "reset_all", "delete_recent_clips",
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL DEFAULT 'pending',
  embed_latency_ms INTEGER,
  cluster_id TEXT,
  session_id TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at);

CREATE TABLE IF NOT EXISTS clip_embeddings (
  clip_id TEXT PRIMARY KEY,
  vector BLOB NOT NULL,
  latency_ms REAL,
  created_at REAL,
  FOREIGN KEY(clip_id) REFERENCES clips(id)
);

CREATE TABLE IF NOT EXISTS clusters (
  id TEXT PRIMARY KEY,
  centroid BLOB,
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

CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  segment_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  text TEXT NOT NULL CHECK(length(text) >= 1 AND length(text) <= 300),
  created_at REAL NOT NULL,
  FOREIGN KEY(segment_id) REFERENCES segments(id)
);
CREATE INDEX IF NOT EXISTS idx_comments_segment_created ON comments(segment_id, created_at DESC);
"""


async def init() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.executescript(SCHEMA_SQL)
        # Phase 10 (L-04): defensive ALTER for legacy v1.0 SQLite DBs missing
        # blob_url. Postgres branch already has this column from Alembic 0001.
        async with conn.execute("PRAGMA table_info(clips)") as cur:
            existing_cols = {row[1] for row in await cur.fetchall()}
        if "blob_url" not in existing_cols:
            await conn.execute("ALTER TABLE clips ADD COLUMN blob_url TEXT")
        # Phase 4 migration: add compile tracking columns to clusters (idempotent via PRAGMA check).
        # SQLite does not support ADD COLUMN IF NOT EXISTS — check via PRAGMA table_info.
        async with conn.execute("PRAGMA table_info(clusters)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "compile_in_flight" not in cols:
            await conn.execute(
                "ALTER TABLE clusters ADD COLUMN compile_in_flight INTEGER NOT NULL DEFAULT 0"
            )
        if "last_compile_at" not in cols:
            await conn.execute(
                "ALTER TABLE clusters ADD COLUMN last_compile_at REAL"
            )
        # Phase 4.5 migration: add child clip columns (idempotent via PRAGMA check).
        async with conn.execute("PRAGMA table_info(clips)") as cur:
            clip_cols = {row[1] for row in await cur.fetchall()}
        if "parent_id" not in clip_cols:
            await conn.execute(
                "ALTER TABLE clips ADD COLUMN parent_id TEXT REFERENCES clips(id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_clips_parent_id ON clips(parent_id)"
            )
        if "start_offset_sec" not in clip_cols:
            await conn.execute(
                "ALTER TABLE clips ADD COLUMN start_offset_sec REAL DEFAULT 0"
            )
        if "end_offset_sec" not in clip_cols:
            await conn.execute(
                "ALTER TABLE clips ADD COLUMN end_offset_sec REAL DEFAULT NULL"
            )
        # Ensure segments.cluster_id is unique (one segment per cluster; ON CONFLICT updates on re-compile)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_cluster_id ON segments(cluster_id)"
        )
        # Phase 4.5 migration: add video_url column to segments
        async with conn.execute("PRAGMA table_info(segments)") as cur:
            seg_cols = {row[1] for row in await cur.fetchall()}
        if "video_url" not in seg_cols:
            await conn.execute(
                "ALTER TABLE segments ADD COLUMN video_url TEXT DEFAULT NULL"
            )
        # Phase 4.6 migration: add title column to segments (nullable; back-fills NULL)
        if "title" not in seg_cols:
            await conn.execute(
                "ALTER TABLE segments ADD COLUMN title TEXT"
            )
        await conn.commit()
    log.info("db.init: schema ready at %s", DB_PATH)


_MIME_EXT = {"video/mp4": "mp4", "video/webm": "webm"}


def ext_from_mime(mime: str | None) -> str:
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
    from . import storage  # local import — avoid circular at module load
    clip_id = uuid.uuid4().hex
    ext = ext_from_mime(file.content_type)
    contents = await file.read()
    result = await storage.save_clip_bytes(clip_id, ext, contents)
    is_blob_url = result.startswith("http")
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO clips (id, path, blob_url, lat, lng, ts, session_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                clip_id,
                None if is_blob_url else result,
                result if is_blob_url else None,
                lat, lng, ts, session_id, now,
            ),
        )
        await conn.commit()
    log.info("insert_clip id=%s bytes=%d", clip_id, len(contents))
    return clip_id


async def get_clip(clip_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_recent_clips(limit: int = 50) -> list[dict]:
    from . import storage  # local import — avoid circular at module load
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT id, path, blob_url, lat, lng, ts, created_at "
            "FROM clips ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
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


async def store_embedding(clip_id: str, vec: np.ndarray, latency_ms: int) -> None:
    blob = vec.astype(np.float32).tobytes()
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO clip_embeddings (clip_id, vector, latency_ms, created_at) "
            "VALUES (?, ?, ?, ?)",
            (clip_id, blob, latency_ms, now),
        )
        await conn.execute(
            "UPDATE clips SET embedding_status = 'done', embed_latency_ms = ? WHERE id = ?",
            (latency_ms, clip_id),
        )
        await conn.commit()


async def get_embedding(clip_id: str) -> np.ndarray | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT vector FROM clip_embeddings WHERE clip_id = ?", (clip_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    return np.frombuffer(row[0], dtype=np.float32).copy()


async def get_all_clusters() -> list[dict]:
    """Read all clusters with member_ids populated from clips.cluster_id JOIN.
    Used by lifespan rebuild (CLU-10). One DB connection, two cursors.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, centroid, centroid_lat, centroid_lng, median_ts, "
            "member_count, created_at FROM clusters"
        )
        cluster_rows = [dict(r) for r in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT id, cluster_id FROM clips WHERE cluster_id IS NOT NULL"
        )
        clip_rows = await cur.fetchall()
    members: dict[str, list[str]] = {}
    for r in clip_rows:
        members.setdefault(r["cluster_id"], []).append(r["id"])
    for c in cluster_rows:
        c["member_ids"] = members.get(c["id"], [])
    return cluster_rows


async def upsert_cluster(cluster) -> None:
    """Insert or update a cluster row. Centroid stored as float32 BLOB.

    cluster has attributes: id (str), centroid (np.ndarray float32),
    centroid_lat (float|None), centroid_lng (float|None),
    median_ts (float), member_count (int).
    """
    blob = cluster.centroid.astype(np.float32).tobytes()
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO clusters
                 (id, centroid, centroid_lat, centroid_lng, median_ts,
                  member_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 centroid=excluded.centroid,
                 centroid_lat=excluded.centroid_lat,
                 centroid_lng=excluded.centroid_lng,
                 median_ts=excluded.median_ts,
                 member_count=excluded.member_count,
                 updated_at=excluded.updated_at""",
            (cluster.id, blob, cluster.centroid_lat, cluster.centroid_lng,
             cluster.median_ts, cluster.member_count, now, now),
        )
        await conn.commit()


async def assign_clip_to_cluster(clip_id: str, cluster_id: str) -> None:
    """Set clips.cluster_id for an already-inserted clip."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE clips SET cluster_id = ? WHERE id = ?",
            (cluster_id, clip_id),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Phase 4: segment helpers
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
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            """INSERT INTO segments
                 (id, cluster_id, ordered_clip_ids, title, caption, location,
                  source_count, created_at, video_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cluster_id) DO UPDATE SET
                 ordered_clip_ids = excluded.ordered_clip_ids,
                 title            = excluded.title,
                 caption          = excluded.caption,
                 location         = excluded.location,
                 source_count     = excluded.source_count,
                 video_url        = excluded.video_url
               RETURNING id""",
            (seg_id, cluster_id, json.dumps(ordered_clip_ids),
             title, caption, location, source_count, now, video_url),
        )
        row = await cur.fetchone()
        await conn.commit()
    return row[0]


async def fetch_recent_segments(limit: int = 50) -> list[dict]:
    """JOIN segments + clusters; batch-fetch all ordered clip paths for sequential playback."""
    from . import storage  # local import — avoid circular at module load
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """SELECT s.id, s.cluster_id, s.ordered_clip_ids, s.title, s.caption,
                      s.location, c.member_count AS source_count, s.created_at,
                      c.centroid_lat, c.centroid_lng, s.video_url AS stored_video_url
               FROM segments s
               JOIN clusters c ON c.id = s.cluster_id
               ORDER BY s.created_at DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        # Batch-fetch path/blob_url rows for all clip IDs across all segments
        all_ids: list[str] = []
        parsed_rows = []
        for r in rows:
            ids = json.loads(r["ordered_clip_ids"])
            all_ids.extend(ids)
            parsed_rows.append((r, ids))
        clip_row_map: dict[str, dict] = {}
        if all_ids:
            placeholders = ",".join("?" * len(all_ids))
            path_cur = await conn.execute(
                f"SELECT id, path, blob_url FROM clips WHERE id IN ({placeholders})",
                all_ids,
            )
            for p in await path_cur.fetchall():
                clip_row_map[p["id"]] = dict(p)
    blob_mode = config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO
    out = []
    for r, ids in parsed_rows:
        def _url(clip_id: str) -> str | None:
            # Phase 4.6: ordered_clip_ids may be run IDs (`{parent}_run_{n}`).
            # Phase 10: in blob mode, run videos live at runs/{run_id}.mp4 on the
            # public store. Parent-clip URLs in blob mode are private and the
            # browser cannot fetch them — return None so the frontend renders
            # "Compiling…" instead of a black <video> element.
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
    """SELECT from segments WHERE cluster_id=?; returns dict or None."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM segments WHERE cluster_id = ?", (cluster_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_segment_by_id(segment_id: str) -> dict | None:
    """Single-segment fetch with the same dict shape as fetch_recent_segments items.
    Returns None when the segment doesn't exist. Used by /m/{id} share landing
    (T3.1) and GET /segments/{id} (T3.2)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT s.id, s.cluster_id, s.ordered_clip_ids, s.title, s.caption,
                      s.location, c.member_count AS source_count, s.created_at,
                      c.centroid_lat, c.centroid_lng, s.video_url AS stored_video_url
               FROM segments s
               JOIN clusters c ON c.id = s.cluster_id
               WHERE s.id = ?""",
            (segment_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        ids = json.loads(row["ordered_clip_ids"])
        clip_path_map: dict[str, str] = {}
        if ids:
            placeholders = ",".join("?" * len(ids))
            path_cur = await conn.execute(
                f"SELECT id, path FROM clips WHERE id IN ({placeholders})", ids,
            )
            for p in await path_cur.fetchall():
                clip_path_map[p["id"]] = p["path"]

    def _url(clip_id: str) -> str | None:
        if "_run_" in clip_id:
            return f"/media/{clip_id}.mp4"
        path = clip_path_map.get(clip_id)
        if not path:
            return None
        return f"/media/{path.rsplit('/', 1)[-1]}"

    video_urls = [_url(cid) for cid in ids]
    return {
        "id": row["id"],
        "cluster_id": row["cluster_id"],
        "ordered_clip_ids": ids,
        "title": row["title"],
        "caption": row["caption"],
        "location": row["location"],
        "source_count": row["source_count"],
        "created_at": row["created_at"],
        "centroid_lat": row["centroid_lat"],
        "centroid_lng": row["centroid_lng"],
        "video_url": row["stored_video_url"] if row["stored_video_url"] else (video_urls[0] if video_urls else None),
        "video_urls": video_urls,
    }


# ---------------------------------------------------------------------------
# Phase 01 (feature track): anonymous comments
# session_id is server-side only — never returned to clients.
# ---------------------------------------------------------------------------

async def insert_comment(segment_id: str, session_id: str, text: str) -> dict:
    """Append a comment + return public-safe dict (no session_id) including
    `commenter_index` — the rank of this session_id among unique commenters
    on this segment, ordered by their first-seen timestamp. Stable per
    (segment, session_id), so a returning commenter keeps the same number."""
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            """INSERT INTO comments (segment_id, session_id, text, created_at)
               VALUES (?, ?, ?, ?) RETURNING id""",
            (segment_id, session_id, text, now),
        )
        new_row = await cur.fetchone()
        idx_cur = await conn.execute(
            """SELECT idx FROM (
                   SELECT session_id,
                          ROW_NUMBER() OVER (ORDER BY MIN(created_at)) AS idx
                   FROM comments
                   WHERE segment_id = ?
                   GROUP BY session_id
               ) ranks
               WHERE session_id = ?""",
            (segment_id, session_id),
        )
        idx_row = await idx_cur.fetchone()
        await conn.commit()
    return {
        "id": new_row["id"],
        "segment_id": segment_id,
        "text": text,
        "created_at": now,
        "commenter_index": int(idx_row["idx"]) if idx_row else 1,
    }


async def list_comments(segment_id: str, limit: int = 200) -> list[dict]:
    """Public-safe comments for a segment, newest first. Each row carries a
    stable `commenter_index` (rank of session_id by first-seen timestamp)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """WITH ranks AS (
                   SELECT session_id,
                          ROW_NUMBER() OVER (ORDER BY MIN(created_at)) AS idx
                   FROM comments
                   WHERE segment_id = ?
                   GROUP BY session_id
               )
               SELECT c.id, c.text, c.created_at, r.idx AS commenter_index
               FROM comments c
               JOIN ranks r ON c.session_id = r.session_id
               WHERE c.segment_id = ?
               ORDER BY c.created_at DESC
               LIMIT ?""",
            (segment_id, segment_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {"id": r["id"], "text": r["text"], "created_at": r["created_at"],
         "commenter_index": int(r["commenter_index"])}
        for r in rows
    ]


async def count_comments_since(session_id: str, since_ts: float) -> int:
    """Count comments authored by this session since `since_ts` (Unix seconds). For rate limiting."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM comments WHERE session_id = ? AND created_at >= ?",
            (session_id, since_ts),
        ) as cur:
            row = await cur.fetchone()
    return int(row[0]) if row else 0


async def set_compile_in_flight(cluster_id: str, value: bool, ttl_seconds: float = 30.0) -> bool:
    """Atomic compare-and-set. Returns True if lock acquired/cleared, False if already held.

    value=True:  single atomic UPDATE WHERE compile_in_flight=0 OR last_compile_at < now-ttl.
                 cursor.rowcount==1 means we acquired; 0 means someone else holds it.
    value=False: unconditional clear; always returns True.
    """
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        if value:
            cursor = await conn.execute(
                """UPDATE clusters
                   SET compile_in_flight = 1, last_compile_at = ?
                   WHERE id = ?
                     AND (compile_in_flight = 0 OR last_compile_at < ?)""",
                (now, cluster_id, now - ttl_seconds),
            )
            await conn.commit()
            return cursor.rowcount == 1
        else:
            await conn.execute(
                "UPDATE clusters SET compile_in_flight = 0 WHERE id = ?",
                (cluster_id,),
            )
            await conn.commit()
            return True


async def is_compile_in_flight(cluster_id: str, ttl_seconds: float = 30.0) -> bool:
    """Returns True only if compile_in_flight=1 AND last_compile_at is within ttl_seconds."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT compile_in_flight, last_compile_at FROM clusters WHERE id = ?",
            (cluster_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    flag, last = row
    if not flag:
        return False
    if last is None or time.time() - last > ttl_seconds:
        return False
    return True


async def fetch_cluster_clips(cluster_id: str) -> list[dict]:
    """SELECT clips where cluster_id=? ORDER BY ts ASC; includes id, path, lat, lng, ts."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT id, path, lat, lng, ts FROM clips WHERE cluster_id = ? ORDER BY ts ASC",
            (cluster_id,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def fetch_cluster_clips_with_children(cluster_id: str) -> list[dict]:
    """Return parent rows in this cluster + their children (walk via parent_id).

    Phase 4.6 (Pivot 1): children no longer carry a cluster_id, so we can no
    longer SELECT them by cluster_id. Two-step walk:
      A) find parent ids (parent_id IS NULL) in this cluster
      B) fetch those parents themselves PLUS any rows whose parent_id is in (A)

    Output rows keep the existing shape (id, path, parent_path, lat, lng, ts,
    parent_id, start_offset_sec, end_offset_sec) so compile.py's
    `_get_children_with_vecs` and the Angle Selector MCP tool stay backward
    compatible. For parent rows path == parent_path. For child rows path may
    be empty (children store path="") — callers fall back to parent_path.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        # Step A: parent rows in this cluster
        parent_cur = await conn.execute(
            """SELECT id, path, blob_url, lat, lng, ts
               FROM clips
               WHERE cluster_id = ? AND parent_id IS NULL
               ORDER BY ts ASC""",
            (cluster_id,),
        )
        parent_rows = [dict(r) for r in await parent_cur.fetchall()]
        parent_ids = [p["id"] for p in parent_rows]
        parent_path_map: dict[str, str] = {p["id"]: p["path"] for p in parent_rows}
        parent_blob_url_map: dict[str, str | None] = {p["id"]: p.get("blob_url") for p in parent_rows}

        if not parent_ids:
            return []

        # Step B: parents themselves + any child of those parents.
        placeholders = ",".join("?" * len(parent_ids))
        rows_cur = await conn.execute(
            f"""SELECT id, path, blob_url, lat, lng, ts, parent_id,
                       start_offset_sec, end_offset_sec
                FROM clips
                WHERE id IN ({placeholders})
                   OR parent_id IN ({placeholders})
                ORDER BY ts ASC, start_offset_sec ASC""",
            parent_ids + parent_ids,
        )
        rows = [dict(r) for r in await rows_cur.fetchall()]

    out = []
    for r in rows:
        parent_path = (
            parent_path_map.get(r["parent_id"], "")
            if r.get("parent_id")
            else r["path"]
        )
        parent_blob_url = (
            parent_blob_url_map.get(r["parent_id"])
            if r.get("parent_id")
            else r.get("blob_url")
        )
        out.append({
            "id": r["id"],
            "path": r["path"] or parent_path,
            "parent_path": parent_path,
            "parent_blob_url": parent_blob_url,
            "lat": r["lat"],
            "lng": r["lng"],
            "ts": r["ts"],
            "parent_id": r.get("parent_id"),
            "start_offset_sec": r.get("start_offset_sec") or 0.0,
            "end_offset_sec": r.get("end_offset_sec"),
        })
    return out


async def get_cluster(cluster_id: str) -> dict | None:
    """SELECT from clusters WHERE id=?; includes member_count, compile_in_flight, last_compile_at."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def count_distinct_parents_in_cluster(cluster_id: str) -> int:
    """Pivot 2 gate: count parent (parent_id IS NULL) clip rows in this cluster.

    Defensive — under Pivot 1 cluster.member_count already equals this value
    (children never get a cluster_id), but if cluster_id ever leaks onto a
    child row this query stays correct.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM clips WHERE cluster_id = ? AND parent_id IS NULL",
            (cluster_id,),
        ) as cur:
            row = await cur.fetchone()
    return int(row[0]) if row else 0


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
    Child path is NULL — children reference parent's file + use offsets for ffmpeg.
    """
    child_id = f"{parent_id}_child_{int(start_offset_sec)}"
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT OR IGNORE INTO clips
               (id, path, lat, lng, ts, session_id, created_at, parent_id,
                start_offset_sec, end_offset_sec, embedding_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (child_id, "", lat, lng, ts, session_id, now,
             parent_id, start_offset_sec, end_offset_sec),
        )
        await conn.commit()
    log.info(
        "insert_child_clip child_id=%s parent_id=%s start=%.1f end=%.1f",
        child_id, parent_id, start_offset_sec, end_offset_sec,
    )
    return child_id


# ---------------------------------------------------------------------------
# Admin: destructive reset helpers
# ---------------------------------------------------------------------------

async def reset_all() -> dict:
    """Wipe clips, embeddings, clusters, segments. Returns row counts deleted.
    File cleanup (CLIPS_DIR) and CLUSTERS cache rebuild are caller's responsibility.
    """
    counts = {}
    async with aiosqlite.connect(DB_PATH) as conn:
        for tbl in ("clips", "clip_embeddings", "clusters", "segments"):
            async with conn.execute(f"SELECT COUNT(*) FROM {tbl}") as cur:
                counts[tbl] = (await cur.fetchone())[0]
        # Order respects FK self-ref on clips(parent_id): wipe children → parents
        # via single DELETE since we're truncating.
        await conn.execute("DELETE FROM segments")
        await conn.execute("DELETE FROM clip_embeddings")
        await conn.execute("DELETE FROM clips")
        await conn.execute("DELETE FROM clusters")
        await conn.commit()
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
    """
    if (limit is None) == (since_seconds is None):
        raise ValueError("pass exactly one of limit or since_seconds")

    counts = {"clips": 0, "embeddings": 0, "segments": 0, "clusters": 0}
    paths_to_delete: list[str] = []

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        if limit is not None:
            cur = await conn.execute(
                "SELECT id, path, blob_url, cluster_id FROM clips "
                "WHERE parent_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            assert since_seconds is not None
            cutoff = time.time() - float(since_seconds)
            cur = await conn.execute(
                "SELECT id, path, blob_url, cluster_id FROM clips "
                "WHERE parent_id IS NULL AND created_at >= ?",
                (cutoff,),
            )
        parents = [dict(r) for r in await cur.fetchall()]
        if not parents:
            return {"counts": counts, "paths_to_delete": paths_to_delete}

        parent_ids = [p["id"] for p in parents]
        affected_clusters = sorted({p["cluster_id"] for p in parents if p["cluster_id"]})
        # Phase 10: blob_url takes precedence over path. Mixed-mode rollback
        # safe — both columns may be populated across different rows.
        for p in parents:
            target = p.get("blob_url") or p.get("path")
            if target:
                paths_to_delete.append(target)

        ph_p = ",".join("?" * len(parent_ids))
        cur = await conn.execute(
            f"SELECT id FROM clips WHERE parent_id IN ({ph_p})", parent_ids
        )
        child_ids = [r["id"] for r in await cur.fetchall()]
        all_clip_ids = parent_ids + child_ids

        # Capture run-output files (data/clips/{run_id}.mp4) referenced by
        # affected segments before we delete those segments.
        if affected_clusters:
            ph_c = ",".join("?" * len(affected_clusters))
            cur = await conn.execute(
                f"SELECT ordered_clip_ids FROM segments WHERE cluster_id IN ({ph_c})",
                affected_clusters,
            )
            for row in await cur.fetchall():
                for cid in json.loads(row["ordered_clip_ids"]):
                    if "_run_" in cid:
                        paths_to_delete.append(str(CLIPS_DIR / f"{cid}.mp4"))

        ph_all = ",".join("?" * len(all_clip_ids))
        cur = await conn.execute(
            f"DELETE FROM clip_embeddings WHERE clip_id IN ({ph_all})", all_clip_ids
        )
        counts["embeddings"] = cur.rowcount

        if child_ids:
            ph_ch = ",".join("?" * len(child_ids))
            await conn.execute(f"DELETE FROM clips WHERE id IN ({ph_ch})", child_ids)
        await conn.execute(f"DELETE FROM clips WHERE id IN ({ph_p})", parent_ids)
        counts["clips"] = len(parent_ids) + len(child_ids)

        if affected_clusters:
            ph_c = ",".join("?" * len(affected_clusters))
            cur = await conn.execute(
                f"""SELECT cluster_id, COUNT(*) AS c
                    FROM clips
                    WHERE cluster_id IN ({ph_c}) AND parent_id IS NULL
                    GROUP BY cluster_id""",
                affected_clusters,
            )
            still_populated = {r["cluster_id"]: r["c"] for r in await cur.fetchall()}
            empty = [cid for cid in affected_clusters if cid not in still_populated]

            now = time.time()
            for cid, cnt in still_populated.items():
                await conn.execute(
                    "UPDATE clusters SET member_count = ?, updated_at = ? WHERE id = ?",
                    (cnt, now, cid),
                )

            if empty:
                ph_e = ",".join("?" * len(empty))
                cur = await conn.execute(
                    f"DELETE FROM segments WHERE cluster_id IN ({ph_e})", empty
                )
                counts["segments"] = cur.rowcount
                cur = await conn.execute(
                    f"DELETE FROM clusters WHERE id IN ({ph_e})", empty
                )
                counts["clusters"] = cur.rowcount

        await conn.commit()

    return {"counts": counts, "paths_to_delete": paths_to_delete}


async def get_children_by_parent(parent_id: str) -> list[dict]:
    """Return all child clip rows for a given parent_id, ordered by start_offset_sec ASC."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT id, parent_id, start_offset_sec, end_offset_sec, lat, lng, ts, session_id "
            "FROM clips WHERE parent_id = ? ORDER BY start_offset_sec ASC",
            (parent_id,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]
