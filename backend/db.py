"""
backend/db.py — SQLite data layer for Newz (aiosqlite, WAL mode).

Single shared connection opened at startup via init_db(). All helpers
accept an explicit `conn` argument so they can be tested with an
in-memory connection without touching the real DB.

Public API:
    init_db()                  — open connection, create schema
    init_db_on_conn(conn)      — create schema on an existing connection
    get_db_conn()              — async context manager yielding the shared conn
    get_clip(clip_id, conn)    — fetch one clip row as dict | None
    create_clip(clip, conn)    — insert a new clip row
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

import config

log = logging.getLogger(__name__)

# Module-level shared connection — opened once in init_db(), reused thereafter.
_conn: aiosqlite.Connection | None = None
_lock = asyncio.Lock()


async def init_db_on_conn(conn: aiosqlite.Connection) -> None:
    """Create schema on *conn*. Safe to call multiple times (IF NOT EXISTS guards)."""
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            id               TEXT PRIMARY KEY,
            path             TEXT NOT NULL,
            lat              REAL,
            lng              REAL,
            ts               REAL NOT NULL,
            duration_sec     REAL,
            embedding_status TEXT NOT NULL DEFAULT 'pending',
            embed_latency_ms INTEGER,
            cluster_id       TEXT,
            created_at       REAL NOT NULL
        )
    """)

    # 512-d float32 vector as 2048-byte BLOB, one row per clip.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS clip_embeddings (
            clip_id TEXT PRIMARY KEY,
            vector  BLOB NOT NULL,
            FOREIGN KEY (clip_id) REFERENCES clips(id)
        )
    """)

    await conn.commit()
    log.info("db schema initialized")


async def init_db() -> None:
    """Open the shared SQLite connection and initialize the schema."""
    global _conn
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    _conn = await aiosqlite.connect(config.DB_PATH)
    _conn.row_factory = aiosqlite.Row
    await init_db_on_conn(_conn)
    log.info("db ready path=%s", config.DB_PATH)


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


@asynccontextmanager
async def get_db_conn() -> AsyncIterator[aiosqlite.Connection]:
    """Yield the shared connection. Raises RuntimeError if init_db() was never called."""
    if _conn is None:
        raise RuntimeError("DB not initialized — call init_db() at startup")
    yield _conn


# ── Clip helpers ──────────────────────────────────────────────────────────────

async def get_clip(clip_id: str, conn: aiosqlite.Connection) -> dict | None:
    """Return one clip row as a plain dict, or None if not found."""
    async with conn.execute(
        "SELECT * FROM clips WHERE id = ?", (clip_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def create_clip(clip: dict, conn: aiosqlite.Connection) -> None:
    """Insert a new clip row. `clip` must have all non-nullable columns."""
    await conn.execute(
        """INSERT INTO clips
             (id, path, lat, lng, ts, duration_sec, embedding_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (
            clip["id"],
            clip["path"],
            clip.get("lat"),
            clip.get("lng"),
            clip["ts"],
            clip.get("duration_sec"),
            clip["created_at"],
        ),
    )
    await conn.commit()
