"""
backend/seed/demo_segment.py — FED-05 pre-seeded staged demo segment.

seed_demo_segment() is called from app.lifespan after db.init().
Inserts one record when the segments table is empty so the feed is never blank.
The ordered_clip_ids reference backend/seed/demo/ placeholders (replaced in Phase 5
with real staged clips filmed at Caltech venue).
The cluster row is a stub — no real clips or embeddings exist for it.
"""
import logging
import time

import aiosqlite

from .. import db

log = logging.getLogger(__name__)

DEMO_CLUSTER_ID = "demo-cluster-000000000000000000000000"
DEMO_CLIP_IDS = ["demo-clip-1", "demo-clip-2", "demo-clip-3"]


async def seed_demo_segment() -> None:
    """Insert a staged demo segment if segments table is empty (FED-05).

    Idempotent: no-op if any segment already exists.
    """
    async with aiosqlite.connect(db.DB_PATH) as conn:
        async with conn.execute("SELECT COUNT(*) FROM segments") as cur:
            row = await cur.fetchone()
        if row and row[0] > 0:
            return  # table already has data — do not overwrite

    # Ensure stub cluster row exists for FK constraint
    now = time.time()
    stub_centroid = b"\x00" * (512 * 4)  # 512 float32 zeros — placeholder
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO clusters
                 (id, centroid, centroid_lat, centroid_lng, median_ts, member_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO NOTHING""",
            (DEMO_CLUSTER_ID, stub_centroid, 34.1377, -118.1253, now, 3, now, now),
        )
        await conn.commit()

    seg_id = await db.insert_segment(
        cluster_id=DEMO_CLUSTER_ID,
        ordered_clip_ids=DEMO_CLIP_IDS,
        caption=(
            "Pedestrians crossing in front of Caltech campus at midday — Pasadena, CA."
        ),
        location="Pasadena, CA",
        source_count=3,
    )
    log.info("FED-05: seeded demo segment seg_id=%s", seg_id)
