"""Shared pytest fixtures.

Post-SQLite-retirement (2026-04-29) the metadata backend is always Postgres.
The previous `metadata_backend` parametrized fixture is retired alongside
db_sqlite.py — tests that need a DB now run only when `DATABASE_URL` is set
(i.e., against a Neon test branch). Storage backend stays parametrized
because both `local` and `blob` paths still ship.
"""
import importlib
import os

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def fresh_db(monkeypatch):
    """Wipe + re-init the DB for each test. Skips when DATABASE_URL is unset
    so local pytest runs (no Neon test branch) don't fail.

    Schema is owned by Alembic (already applied to the test DB); init() is a
    no-op. reset_all() wipes the v1.x tables.

    Yields the backend.db module — call db.insert_clip(...) etc. against this
    object, not against any imported-at-module-top reference.
    """
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; DB-touching test skipped")
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    import backend.config
    import backend.db
    importlib.reload(backend.config)
    importlib.reload(backend.db)
    from backend import db
    await db.init_pool()
    await db.init()
    await db.reset_all()
    try:
        yield db
    finally:
        await db.close_pool()


@pytest.fixture(params=["local", "blob"], ids=["local", "blob"])
def storage_backend(request, monkeypatch, respx_mock):
    """D-21: parametrize STORAGE_BACKEND.

    Cells where STORAGE_BACKEND=blob register respx mocks for Vercel Blob's
    REST endpoints. NEVER hits real Vercel Blob from CI. respx_mock is the
    pytest-fixture form (auto-tear-down per-test) — Pitfall 5.
    """
    backend = request.param
    monkeypatch.setenv("STORAGE_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    if backend == "blob":
        monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_TESTSTORE_xxxxx")
        respx_mock.put("https://vercel.com/api/blob").respond(
            json={
                "url": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4",
                "downloadUrl": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4?download=1",
                "pathname": "uploads/abc.mp4",
                "contentType": "video/mp4",
                "contentDisposition": 'attachment; filename="abc.mp4"',
            },
        )
        respx_mock.post("https://vercel.com/api/blob/delete").respond(200)
        respx_mock.get("https://vercel.com/api/blob").respond(
            json={
                "size": 1024,
                "uploadedAt": "2026-04-29T00:00:00Z",
                "pathname": "uploads/abc.mp4",
                "contentType": "video/mp4",
                "contentDisposition": "",
                "url": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4",
                "downloadUrl": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4?download=1",
                "cacheControl": "public, max-age=2592000",
            },
        )
    importlib.reload(__import__("backend.config", fromlist=[""]))
    importlib.reload(__import__("backend.storage", fromlist=[""]))
    yield backend


# ---------------------------------------------------------------------------
# Phase 11 (D-25 reconciled): single Gemini-mock fixture for moderation tests
# ---------------------------------------------------------------------------

@pytest.fixture
def gemini_moderation_mock(respx_mock, monkeypatch):
    """Phase 11 (D-25 reconciled): single Gemini-mock fixture for moderation tests.

    Default response is all-pass for every category. Tests that need a different
    verdict re-register the same generateContent route with their own .respond(...)
    payload (respx allows route override; the last registration wins for matching
    paths — verified inline before fixture authorship).

    NO per-provider parametrize per the 2026-04-29 reconciliation: classifier-
    only CSAM detection collapses any imagined per-provider matrix to a single
    Gemini route. See .planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/
    11-CONTEXT.md (D-25 reconciled).
    """
    import json
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setenv("MODERATION_MAX_BUDGET_S", "20.0")
    monkeypatch.setenv("OFFLINE_DEMO", "false")

    all_pass = {
        cat: {"verdict": "pass", "score": 0.0, "rationale": "no signal"}
        for cat in ("csam", "sexual", "hate", "extremist", "violence", "self_harm")
    }

    # Files API upload (default — tests can override).
    respx_mock.post(
        "https://generativelanguage.googleapis.com/upload/v1beta/files"
    ).respond(json={"file": {"name": "files/test", "state": "ACTIVE",
                              "uri": "https://generativelanguage.googleapis.com/v1beta/files/test"}})
    # Files API poll.
    respx_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/files/test"
    ).respond(json={"name": "files/test", "state": "ACTIVE"})
    # generateContent (default: all-pass).
    respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    ).respond(json={"candidates": [{"content": {"parts": [{"text": json.dumps(all_pass)}]}}]})
    # Files API cleanup.
    respx_mock.delete(
        "https://generativelanguage.googleapis.com/v1beta/files/test"
    ).respond(json={})

    yield respx_mock
