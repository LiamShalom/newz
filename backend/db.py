import logging
import time
import uuid
from pathlib import Path

import aiosqlite
from fastapi import UploadFile

from . import config

log = logging.getLogger(__name__)

DB_PATH = config.DATA_DIR / "newz.db"
CLIPS_DIR = config.DATA_DIR / "clips"

# Forward-compat: full schema declared at init even though Phase 1 only writes `clips`.
# Phase 2 fills clip_embeddings, Phase 3 clusters, Phase 4 segments. This avoids a
# migration when those phases land.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL DEFAULT 'pending',
  cluster_id TEXT,
  session_id TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at);

CREATE TABLE IF NOT EXISTS clip_embeddings (
  clip_id TEXT PRIMARY KEY,
  vector BLOB,
  latency_ms REAL,
  created_at REAL,
  FOREIGN KEY(clip_id) REFERENCES clips(id)
);

CREATE TABLE IF NOT EXISTS clusters (
  id TEXT PRIMARY KEY,
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
    """Create directories + schema. WAL mode for concurrent reads during writes."""
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
    """Map browser-sent MIME to filesystem extension. Strips codec params per CAP-10 ladder."""
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
    """Persist clip bytes to disk + metadata row. Returns clip_id.

    Anonymity invariant (ING-06): session_id is stored but NEVER returned in any response,
    NEVER printed in logs at any level (logging session_id is forbidden).

    NOTE: caller is responsible for enforcing MAX_UPLOAD_BYTES BEFORE invoking this function.
    This helper does not re-check size; it trusts the route handler to gate.
    """
    clip_id = uuid.uuid4().hex
    ext = ext_from_mime(file.content_type)
    path = CLIPS_DIR / f"{clip_id}.{ext}"
    # Read full body — caller has already validated size.
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
    # Log clip_id and rounded GPS only — never session_id, never exact GPS (privacy floor).
    log.info(
        "insert_clip id=%s lat=%.2f lng=%.2f bytes=%d",
        clip_id, lat, lng, len(contents),
    )
    return clip_id


async def fetch_recent_clips(limit: int = 50) -> list[dict]:
    """Return newest-first clips for the Phase 1 raw feed (D-08).
    NEVER include session_id in the returned dict — that is identity-adjacent.

    URL prefix is /media (the StaticFiles mount in app.py), NOT /clips.
    /clips is the API verb namespace (POST = ingest); /media is the static-file namespace.
    """
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
        # Translate filesystem path to public URL the FE can fetch.
        # /media/* is mounted on DATA_DIR/clips by app.py.
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
