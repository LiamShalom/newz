"""Phase 9 (D-10): shared pytest fixtures.

The `metadata_backend` parametrized fixture lets db-touching tests run against
both sqlite and postgres backends. Postgres path skips when DATABASE_URL is
unset (CI without a Neon test branch).

Existing v1.0 tests keep using their per-file `tmp_db` SQLite-only fixture
(RESEARCH §Pattern 6 caveat — those tests monkeypatch DB_PATH directly, which
only makes sense for the sqlite branch). Parity tests (test_db_postgres.py)
opt-in to `fresh_db` instead.
"""
import importlib
import os

import pytest
import pytest_asyncio


@pytest.fixture(params=["sqlite", "postgres"], ids=["sqlite", "postgres"])
def metadata_backend(request, monkeypatch):
    """D-10: parametrized backend selector.

    Skips the postgres parametrization when DATABASE_URL is unset — local CI
    against a Neon test branch is the only path that exercises the postgres
    leg. This keeps `pytest backend/tests/` runnable in any developer
    environment without requiring a live Postgres.
    """
    backend = request.param
    if backend == "postgres" and not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; postgres path skipped")
    monkeypatch.setenv("METADATA_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    # Force re-import of backend.config + backend.db so the dispatcher
    # re-evaluates with the new env vars. Mirrors test_observability_sentry.py
    # module-reimport pattern.
    import backend.config
    import backend.db
    importlib.reload(backend.config)
    importlib.reload(backend.db)
    yield backend


@pytest_asyncio.fixture
async def fresh_db(metadata_backend):
    """Wipe + re-init the DB for each (test, backend) pair.

    For sqlite: db.init() creates the schema; reset_all() wipes any prior data.
    For postgres: schema is owned by Alembic (already applied to the test DB);
    init() is a no-op; reset_all() wipes the 4 v1.0 tables.

    Yields the (just-reloaded) backend.db module — call db.insert_clip(...) etc.
    against this object, not against any imported-at-module-top reference.
    """
    from backend import db
    if hasattr(db, "init_pool"):
        # Postgres branch: lifespan would normally do this; in tests we do it manually.
        await db.init_pool()
    if hasattr(db, "init"):
        await db.init()
    if hasattr(db, "reset_all"):
        await db.reset_all()
    try:
        yield db
    finally:
        if hasattr(db, "close_pool"):
            await db.close_pool()
