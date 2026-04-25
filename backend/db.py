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
"""


async def init() -> None:
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
    clip_id = uuid.uuid4().hex
    ext = ext_from_mime(file.content_type)
    path = CLIPS_DIR / f"{clip_id}.{ext}"
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
    log.info("insert_clip id=%s lat=%.2f lng=%.2f bytes=%d", clip_id, lat, lng, len(contents))
    return clip_id


async def get_clip(clip_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def fetch_recent_clips(limit: int = 50) -> list[dict]:
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
