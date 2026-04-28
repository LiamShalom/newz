"""Phase 9 (DB-03 / SC-2): one-shot v1.0 SQLite → Neon Postgres metadata migrator.

Usage:
  DATABASE_URL=postgresql://... python -m backend.scripts.sqlite_to_postgres [--force]

Pre-requisites:
  - Target Postgres has the v1.1 schema (run `alembic upgrade head` first).
  - Source SQLite at config.DATA_DIR / "newz.db" (default ./data/newz.db locally,
    /data/newz.db on Railway).

Idempotency: refuses to run if any target table has rows, unless --force is passed.

SC-2 row-count parity gate: raises RuntimeError on row-count mismatch per table.

Security (RESEARCH §Security action item 3): DATABASE_URL is read from environment,
NEVER accepted as a CLI argument (avoids shell-history capture).
"""
import argparse
import asyncio
import logging
import sys

import aiosqlite
import asyncpg
import numpy as np

from .. import config

log = logging.getLogger(__name__)

# Tables to copy in FK-safe order. clips before clip_embeddings (FK clip_id).
# clusters before segments (FK cluster_id). Note: reports / moderation_decisions /
# reported_csam are empty in v1.0 SQLite — not copied.
TABLES_IN_ORDER = ["clips", "clip_embeddings", "clusters", "segments"]

# Column lists. Must match v1.0 SQLite schema today AND v1.1 Postgres schema.
# Phase-9-bake-in nullable columns (clips.blob_url, clips.is_hidden) are NOT
# copied — left NULL/FALSE in target (Phases 10/11 populate).
COLUMNS = {
    "clips": [
        "id", "path", "lat", "lng", "ts", "duration_sec",
        "embedding_status", "embed_latency_ms", "cluster_id",
        "session_id", "created_at",
        "parent_id", "start_offset_sec", "end_offset_sec",
    ],
    "clip_embeddings": ["clip_id", "vector", "latency_ms", "created_at"],
    "clusters": [
        "id", "centroid", "centroid_lat", "centroid_lng", "median_ts",
        "member_count", "created_at", "updated_at",
        "compile_in_flight", "last_compile_at",
    ],
    "segments": [
        "id", "cluster_id", "ordered_clip_ids", "caption", "location",
        "source_count", "created_at", "video_url", "title",
    ],
}

# BYTEA columns — defensive bytes() cast on read (Pitfall 5: aiosqlite returns
# memoryview in some configurations).
BYTES_COLUMNS = {("clip_embeddings", "vector"), ("clusters", "centroid")}


async def _check_target_empty(pg_conn, force: bool) -> None:
    """Idempotency guard: refuse to run if any target table has rows."""
    for tbl in TABLES_IN_ORDER:
        n = await pg_conn.fetchval(f"SELECT count(*) FROM {tbl}")
        if n > 0 and not force:
            raise RuntimeError(
                f"target table {tbl} has {n} rows; pass --force to override"
            )


def _coerce_row(tbl: str, cols: list[str], r) -> tuple:
    """Convert aiosqlite Row to a tuple, applying bytes() cast on BLOB columns."""
    out = []
    for col in cols:
        v = r[col]
        if (tbl, col) in BYTES_COLUMNS and v is not None:
            v = bytes(v)  # Pitfall 5: defensive against memoryview
        out.append(v)
    return tuple(out)


async def _copy_table(sqlite_conn, pg_conn, tbl: str) -> tuple[int, int]:
    """Copy one table. Returns (rows_read_from_sqlite, rows_in_target_after).

    Within clips, parents (parent_id IS NULL) are inserted before children to
    satisfy the self-FK constraint.
    """
    cols = COLUMNS[tbl]
    col_list = ", ".join(cols)
    cur = await sqlite_conn.execute(f"SELECT {col_list} FROM {tbl}")
    rows = await cur.fetchall()
    if not rows:
        return 0, 0

    records = [_coerce_row(tbl, cols, r) for r in rows]

    if tbl == "clips":
        # Self-FK on parent_id: insert parents first (parent_id IS NULL), then children.
        parent_idx = cols.index("parent_id")
        parents = [r for r in records if r[parent_idx] is None]
        children = [r for r in records if r[parent_idx] is not None]
        if parents:
            await pg_conn.copy_records_to_table(tbl, records=parents, columns=cols)
        if children:
            await pg_conn.copy_records_to_table(tbl, records=children, columns=cols)
    else:
        await pg_conn.copy_records_to_table(tbl, records=records, columns=cols)

    n_pg = await pg_conn.fetchval(f"SELECT count(*) FROM {tbl}")
    return len(records), n_pg


async def _verify_centroid_round_trip(sqlite_conn, pg_conn) -> None:
    """One-row sanity check on BYTEA round-trip (Pitfall 5).

    If clusters has at least one row with a non-null centroid, fetch the same
    row from sqlite and postgres and assert byte-identity via np.array_equal.
    """
    cur = await sqlite_conn.execute(
        "SELECT id, centroid FROM clusters WHERE centroid IS NOT NULL LIMIT 1"
    )
    r = await cur.fetchone()
    if r is None:
        log.info("centroid round-trip skipped: no clusters with non-null centroid")
        return
    cluster_id = r["id"]
    src_bytes = bytes(r["centroid"])
    dst_row = await pg_conn.fetchrow(
        "SELECT centroid FROM clusters WHERE id = $1", cluster_id
    )
    dst_bytes = bytes(dst_row["centroid"])
    src_vec = np.frombuffer(src_bytes, dtype=np.float32)
    dst_vec = np.frombuffer(dst_bytes, dtype=np.float32)
    if not np.array_equal(src_vec, dst_vec):
        raise RuntimeError(
            f"centroid round-trip mismatch on cluster {cluster_id}: "
            "BYTEA bytes differ from BLOB bytes (RESEARCH Pitfall 5)"
        )
    log.info("centroid round-trip ok: cluster %s (len=%d)", cluster_id, len(src_vec))


async def main(force: bool) -> int:
    sqlite_path = config.DATA_DIR / "newz.db"
    if not sqlite_path.exists():
        print(f"FATAL: {sqlite_path} not found", file=sys.stderr)
        return 2
    pg_dsn = config.DATABASE_URL
    if not pg_dsn:
        print("FATAL: DATABASE_URL not set", file=sys.stderr)
        return 2

    pg_conn = await asyncpg.connect(pg_dsn)
    try:
        await _check_target_empty(pg_conn, force)
        async with aiosqlite.connect(sqlite_path) as sqlite_conn:
            sqlite_conn.row_factory = aiosqlite.Row
            for tbl in TABLES_IN_ORDER:
                n_src, n_dst = await _copy_table(sqlite_conn, pg_conn, tbl)
                print(f"{tbl}: copied {n_src} rows; target now has {n_dst}")
                # SC-2 row-count parity gate
                if n_src != n_dst:
                    raise RuntimeError(
                        f"row-count mismatch on {tbl}: src={n_src}, dst={n_dst}"
                    )
            # Pitfall 5 sanity: one-row centroid bytes equality check.
            await _verify_centroid_round_trip(sqlite_conn, pg_conn)
    finally:
        await pg_conn.close()
    print("OK: migration complete; SC-2 row-count parity verified")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--force",
        action="store_true",
        help="bypass the empty-target idempotency guard",
    )
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.force)))
