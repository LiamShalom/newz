"""Phase 9 (09-03) — db_postgres.py signature parity + pool lifecycle tests.

Tests in this file do NOT require a live Neon connection. They exercise:
  * module import without DATABASE_URL set
  * __all__ parity vs. db_sqlite.__all__ (D-07 contract)
  * inspect.signature() byte-identity for every callable in db_sqlite.__all__
  * get_pool() fail-fast when init_pool() not awaited
  * presence of $-style placeholders only (zero `?` placeholders in SQL strings)
  * BYTEA defensive cast pattern (`bytes(row[...])`)
  * DB_PATH stub == None; CLIPS_DIR == config.DATA_DIR / "clips"

Live-pool integration tests (insert_clip / get_clip round-trip, etc.) belong
in a separate file gated by DATABASE_URL availability — see Phase 9 plan 04+
for the conftest fixture (D-10).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module import smoke
# ---------------------------------------------------------------------------

def test_module_imports_cleanly_without_database_url(monkeypatch):
    """Module-level import must not touch Neon. init_pool() is lazy."""
    monkeypatch.setenv("DATABASE_URL", "")
    # Force fresh import in case another test has cached it
    import importlib
    from backend import db_postgres
    importlib.reload(db_postgres)
    assert db_postgres._pool is None
    assert hasattr(db_postgres, "init_pool")
    assert hasattr(db_postgres, "close_pool")
    assert hasattr(db_postgres, "get_pool")


def test_all_list_has_28_names():
    """25 db_sqlite parity names + 3 lifecycle helpers (init_pool, close_pool, get_pool)."""
    from backend import db_postgres
    assert len(db_postgres.__all__) == 28, db_postgres.__all__


# ---------------------------------------------------------------------------
# Signature parity — D-07 contract
# ---------------------------------------------------------------------------

def test_all_db_sqlite_names_present_in_db_postgres():
    """Every name in db_sqlite.__all__ MUST appear in db_postgres.__all__."""
    from backend import db_sqlite, db_postgres
    sqlite_names = set(db_sqlite.__all__)
    postgres_names = set(db_postgres.__all__)
    missing = sqlite_names - postgres_names
    assert not missing, f"db_postgres missing parity names: {missing}"


def test_db_postgres_only_extras_are_lifecycle_helpers():
    """db_postgres adds exactly 3 names not in db_sqlite (init_pool, close_pool, get_pool)."""
    from backend import db_sqlite, db_postgres
    sqlite_names = set(db_sqlite.__all__)
    postgres_names = set(db_postgres.__all__)
    extra = postgres_names - sqlite_names
    assert extra == {"init_pool", "close_pool", "get_pool"}, extra


def test_callable_signatures_match_db_sqlite():
    """For every callable name in db_sqlite.__all__, inspect.signature must match db_postgres."""
    from backend import db_sqlite, db_postgres
    for name in db_sqlite.__all__:
        if name in {"DB_PATH", "CLIPS_DIR"}:
            continue
        s_obj = getattr(db_sqlite, name)
        p_obj = getattr(db_postgres, name)
        if not callable(s_obj):
            continue
        s_sig = inspect.signature(s_obj)
        p_sig = inspect.signature(p_obj)
        assert s_sig == p_sig, f"signature mismatch for {name}: sqlite={s_sig}, postgres={p_sig}"


# ---------------------------------------------------------------------------
# Pool lifecycle — fail-fast contract
# ---------------------------------------------------------------------------

def test_get_pool_raises_runtime_error_before_init_pool(monkeypatch):
    """get_pool() must raise RuntimeError mentioning 'not initialized' before init_pool()."""
    from backend import db_postgres
    # Ensure a clean state in case prior tests/imports left _pool set.
    monkeypatch.setattr(db_postgres, "_pool", None)
    with pytest.raises(RuntimeError) as exc_info:
        db_postgres.get_pool()
    assert "not initialized" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Module-level constant stubs
# ---------------------------------------------------------------------------

def test_db_path_stub_is_none():
    """Postgres has no file path; DB_PATH is None for db_sqlite parity (debug/dbstate guards)."""
    from backend import db_postgres
    assert db_postgres.DB_PATH is None


def test_clips_dir_matches_sqlite_path():
    """CLIPS_DIR must equal config.DATA_DIR / 'clips' (still consumed by /media StaticFiles)."""
    from backend import config, db_postgres
    assert db_postgres.CLIPS_DIR == config.DATA_DIR / "clips"


# ---------------------------------------------------------------------------
# SQL safety — $N placeholders only
# ---------------------------------------------------------------------------

def _read_source() -> str:
    p = Path(__file__).resolve().parent.parent / "db_postgres.py"
    return p.read_text()


def test_no_question_mark_placeholders_in_sql():
    """Zero `?` placeholders may appear in SQL strings. asyncpg uses $N only."""
    src = _read_source()
    suspicious = []
    for ln in src.splitlines():
        # Heuristic: line containing SQL keyword AND a `?` in a string-ish position.
        if re.search(r"\?\s*[\"',)]", ln) and re.search(
            r"(SELECT|INSERT|UPDATE|DELETE|VALUES|WHERE)", ln, re.IGNORECASE
        ):
            suspicious.append(ln.strip())
    assert not suspicious, f"`?` placeholders detected in SQL: {suspicious[:3]}"


def test_dollar_placeholders_present():
    """At least 30 $N positional placeholders should appear across the ports."""
    src = _read_source()
    matches = re.findall(r"\$[0-9]+", src)
    assert len(matches) >= 30, f"only {len(matches)} $N placeholders found"


def test_pool_init_uses_min1_max10():
    """asyncpg.create_pool must be called with min_size=1 and max_size=10 (DB-07 / L-02)."""
    src = _read_source()
    assert "asyncpg.create_pool" in src
    # We just check that both bounds appear in the source. Order-tolerant.
    assert "min_size=1" in src, "min_size=1 not found"
    assert "max_size=10" in src, "max_size=10 not found"


def test_no_sqlalchemy_import():
    """L-01: SQLAlchemy is forbidden at runtime. Alembic-only."""
    src = _read_source()
    for forbidden in ("from sqlalchemy", "import sqlalchemy"):
        assert forbidden not in src, f"forbidden import: {forbidden}"


def test_no_pgbouncer_hint():
    """Pitfall 1: do NOT set statement_cache_size=0 (only needed against -pooler)."""
    src = _read_source()
    assert "statement_cache_size=0" not in src
    assert "statement_cache_size = 0" not in src


def test_bytea_defensive_cast():
    """Pitfall 5: every BYTEA read must defensive-cast to bytes() before numpy.

    Two use-sites: get_embedding (vector column) and get_all_clusters (centroid column).
    Match `bytes(<ident>[...]` rather than locking on `row` since we sometimes loop
    over a list of dicts where the variable is named `c` instead of `row`.
    """
    src = _read_source()
    n = len(re.findall(r"bytes\([a-zA-Z_][a-zA-Z0-9_]*\[", src))
    assert n >= 2, f"expected ≥2 `bytes(<ident>[...])` casts, found {n}"


def test_async_def_count_at_least_24():
    """db_sqlite has 22 async defs (21 functions + init). db_postgres adds init_pool +
    close_pool = 24 minimum. (get_pool is sync.)
    """
    src = _read_source()
    n = len(re.findall(r"^async def ", src, re.MULTILINE))
    assert n >= 24, f"only {n} async defs found"


# ===========================================================================
# Phase 9 (09-09): basic CRUD + embedding round-trip parity tests via fresh_db.
#
# These tests use the `fresh_db` fixture from conftest.py (D-10 parametrize) —
# each runs once against sqlite, once against postgres (postgres skipped when
# DATABASE_URL is unset). They are the DB-01 unit gate. The signature parity
# contract from D-07 means the same test body works against either backend.
# ===========================================================================

import io
import types
import uuid

import numpy as np
from fastapi import UploadFile


def _make_upload_file(content: bytes = b"FAKE_VIDEO_BYTES", mime: str = "video/mp4") -> UploadFile:
    return UploadFile(
        filename="t.mp4",
        file=io.BytesIO(content),
        headers={"content-type": mime},
    )


def _make_cluster(cluster_id: str | None = None, vec: np.ndarray | None = None):
    cid = cluster_id or uuid.uuid4().hex
    if vec is None:
        rng = np.random.default_rng(42)
        vec = rng.standard_normal(512).astype(np.float32)
    return types.SimpleNamespace(
        id=cid,
        centroid=vec,
        centroid_lat=37.0,
        centroid_lng=-122.0,
        median_ts=1700000000.0,
        member_count=1,
    )


@pytest.mark.asyncio
async def test_insert_and_get_clip(fresh_db):
    """DB-01: insert_clip + get_clip round-trip parity."""
    db = fresh_db
    f = _make_upload_file()
    clip_id = await db.insert_clip(f, lat=37.0, lng=-122.0, ts=1700000000.0, session_id="s1")
    assert clip_id
    clip = await db.get_clip(clip_id)
    assert clip is not None
    assert clip["id"] == clip_id
    assert clip["lat"] == 37.0
    assert clip["session_id"] == "s1"


@pytest.mark.asyncio
async def test_store_and_get_embedding_round_trip(fresh_db):
    """DB-01 / RESEARCH Pitfall 5: embedding bytes round-trip is byte-identical.

    This is the cluster-cosine correctness contract. If get_embedding returns
    bytes that differ from what store_embedding wrote, the entire clustering
    pipeline silently mis-scores.
    """
    db = fresh_db
    f = _make_upload_file()
    clip_id = await db.insert_clip(f, lat=37.0, lng=-122.0, ts=1700000000.0, session_id="s1")
    rng = np.random.default_rng(42)
    vec = rng.standard_normal(512).astype(np.float32)
    await db.store_embedding(clip_id, vec, latency_ms=1234)
    got = await db.get_embedding(clip_id)
    assert got is not None
    assert got.shape == (512,)
    assert np.array_equal(got, vec), "BYTEA/BLOB round-trip must be byte-identical"


@pytest.mark.asyncio
async def test_upsert_and_fetch_cluster_with_centroid(fresh_db):
    """DB-04: cluster centroid BYTEA round-trip + member_ids JOIN.

    Mirrors the rebuild_cache() startup path (DB-04 — CLUSTERS in-memory cache
    must rebuild from whichever backend is active).
    """
    db = fresh_db
    rng = np.random.default_rng(7)
    vec = rng.standard_normal(512).astype(np.float32)
    cluster = _make_cluster(vec=vec)
    await db.upsert_cluster(cluster)

    # Insert a clip and assign it to the cluster — exercises the JOIN in get_all_clusters
    f = _make_upload_file()
    clip_id = await db.insert_clip(f, lat=37.0, lng=-122.0, ts=1700000000.0, session_id="s1")
    await db.assign_clip_to_cluster(clip_id, cluster.id)

    rows = await db.get_all_clusters()
    matching = [c for c in rows if c["id"] == cluster.id]
    assert len(matching) == 1
    c = matching[0]
    # Centroid bytes must round-trip byte-identical (Pitfall 5).
    centroid_round_trip = np.frombuffer(bytes(c["centroid"]), dtype=np.float32)
    assert np.array_equal(centroid_round_trip, vec)
    # member_ids JOIN populated correctly
    assert clip_id in c["member_ids"]


@pytest.mark.asyncio
async def test_compile_in_flight_cas_lock(fresh_db):
    """DB-01: set_compile_in_flight CAS semantics — first acquire returns True,
    second returns False without releasing.

    asyncpg returns the command tag string ("UPDATE 1") which db_postgres parses
    via tag.endswith(' 1'). This test gates that parsing matches v1.0 sqlite
    cursor.rowcount semantics.
    """
    db = fresh_db
    rng = np.random.default_rng(3)
    cluster = _make_cluster(vec=rng.standard_normal(512).astype(np.float32))
    await db.upsert_cluster(cluster)

    acquired_first = await db.set_compile_in_flight(cluster.id, True)
    assert acquired_first is True, "first CAS acquire must succeed"
    acquired_second = await db.set_compile_in_flight(cluster.id, True)
    assert acquired_second is False, "second CAS acquire must fail (lock held)"

    # Release explicitly
    released = await db.set_compile_in_flight(cluster.id, False)
    assert released is True

    # Now another acquire should succeed
    re_acquired = await db.set_compile_in_flight(cluster.id, True)
    assert re_acquired is True


@pytest.mark.asyncio
async def test_reset_all_returns_counts_and_wipes(fresh_db):
    """DB-01: reset_all returns counts dict {clips, clip_embeddings, clusters, segments}
    and wipes all 4 tables."""
    db = fresh_db
    f = _make_upload_file()
    await db.insert_clip(f, lat=37.0, lng=-122.0, ts=1700000000.0, session_id="s1")

    counts = await db.reset_all()
    assert isinstance(counts, dict)
    assert set(counts.keys()) >= {"clips", "clip_embeddings", "clusters", "segments"}
    assert counts["clips"] >= 1

    # After reset, fetch_recent_clips returns empty
    assert await db.fetch_recent_clips() == []
