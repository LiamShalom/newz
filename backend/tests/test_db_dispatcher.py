"""Phase 9 (DB-06, D-08, D-11): dispatcher routing tests.

Validates that backend/db.py routes to the correct underlying module for each
of the 4 env-var combinations. The dispatcher runs at module import — these
tests evict backend.db from sys.modules and re-import after monkeypatching
env vars (importlib.reload alone preserves stale `from X import *` names).
"""
import importlib
import sys

import pytest


def _reload_db_after_env_flip(monkeypatch, metadata_backend: str, offline_demo: str):
    """Helper: set env vars + force a fresh import of backend.config and
    backend.db so the dispatcher re-runs from a clean namespace. Returns the
    freshly-imported `backend.db` module.

    Note: `importlib.reload` is insufficient because `from X import *` injects
    names into the module dict, and a subsequent reload that picks a different
    branch (e.g., sqlite after postgres) doesn't clear the postgres-only names
    (init_pool, close_pool, get_pool). We pop from sys.modules so the next
    import recreates the module's namespace from scratch.
    """
    monkeypatch.setenv("METADATA_BACKEND", metadata_backend)
    monkeypatch.setenv("OFFLINE_DEMO", offline_demo)
    sys.modules.pop("backend.db", None)
    import backend.config
    importlib.reload(backend.config)
    import backend.db  # fresh import — dispatcher runs against the just-reloaded config
    return backend.db


def test_dispatcher_sqlite_default(monkeypatch):
    """METADATA_BACKEND=sqlite + OFFLINE_DEMO=false → db_sqlite branch.

    Verified by: db.DB_PATH is a Path (sqlite has it), and init_pool is NOT exported.
    """
    db = _reload_db_after_env_flip(monkeypatch, "sqlite", "false")
    assert db.DB_PATH is not None, "sqlite branch must export DB_PATH (Path)"
    assert not hasattr(db, "init_pool"), "sqlite branch must NOT export init_pool"
    assert hasattr(db, "insert_clip"), "all 25 db_sqlite names must be re-exported"
    assert hasattr(db, "reset_all")


def test_dispatcher_postgres_normal(monkeypatch):
    """METADATA_BACKEND=postgres + OFFLINE_DEMO=false → db_postgres branch.

    Verified by: db.DB_PATH is None (postgres stub), and init_pool IS exported.
    """
    db = _reload_db_after_env_flip(monkeypatch, "postgres", "false")
    assert db.DB_PATH is None, "postgres branch must stub DB_PATH=None"
    assert hasattr(db, "init_pool"), "postgres branch must export init_pool"
    assert hasattr(db, "close_pool")
    assert hasattr(db, "get_pool")
    assert hasattr(db, "insert_clip"), "all 25 parity names must still be re-exported"


def test_dispatcher_offline_demo_overrides_postgres(monkeypatch):
    """METADATA_BACKEND=postgres + OFFLINE_DEMO=true → db_sqlite (D-11 hard-override).

    This is the keystone test for D-11: the firewalled CI smoke (DEMO-02, owned
    by Phase 13) sets OFFLINE_DEMO=true; even if METADATA_BACKEND is left at
    postgres in the env, the dispatcher must NOT attempt a Neon connection.
    """
    db = _reload_db_after_env_flip(monkeypatch, "postgres", "true")
    assert db.DB_PATH is not None, "OFFLINE_DEMO=true must force sqlite (D-11)"
    assert not hasattr(db, "init_pool"), "OFFLINE_DEMO=true must NOT expose init_pool"


def test_dispatcher_unknown_backend_falls_through_to_sqlite(monkeypatch):
    """Unknown METADATA_BACKEND value → sqlite (safe default per dispatcher fall-through)."""
    db = _reload_db_after_env_flip(monkeypatch, "mariadb", "false")
    assert db.DB_PATH is not None, "unknown backend must fall through to sqlite"
    assert not hasattr(db, "init_pool")
