"""T-10-05 mitigation test (BLOB-06 / D-18 / Phase 13 DEMO-02).

Asserts that OFFLINE_DEMO=true produces zero outbound HTTP traffic to
Vercel Blob during full lifespan startup, even with STORAGE_BACKEND=blob
set. Mirrors Phase 9 OFFLINE_DEMO posture.
"""
import importlib

import pytest
import respx
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_offline_demo_firewall_no_blob_calls(monkeypatch):
    monkeypatch.setenv("OFFLINE_DEMO", "true")
    monkeypatch.setenv("STORAGE_BACKEND", "blob")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "")
    import backend.config
    import backend.storage
    importlib.reload(backend.config)
    importlib.reload(backend.storage)

    # Sanity: dispatcher resolved to local even with STORAGE_BACKEND=blob.
    assert backend.storage.save_clip_bytes.__module__ == "backend.storage.local"

    with respx.mock(base_url="https://vercel.com") as router, \
         respx.mock(base_url="https://teststore.private.blob.vercel-storage.com") as router2:
        import backend.app
        importlib.reload(backend.app)
        transport = ASGITransport(app=backend.app.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/health")
            assert r.status_code == 200
        assert len(router.calls) == 0, f"Blob API was called under OFFLINE_DEMO=true: {list(router.calls)}"
        assert len(router2.calls) == 0, f"Blob storage was called under OFFLINE_DEMO=true: {list(router2.calls)}"

    paths = [r.path for r in backend.app.app.routes if hasattr(r, "path")]
    assert any(p.startswith("/media") for p in paths), "/media mount missing under OFFLINE_DEMO=true"


@pytest.mark.asyncio
async def test_offline_demo_no_moderation_calls(monkeypatch, respx_mock):
    """Phase 11 MOD-10: OFFLINE_DEMO=true bypasses every external moderation API.

    Asserts respx routers see ZERO calls to Gemini Files (upload + poll),
    generateContent, or files-cleanup. moderate_clip's OFFLINE_DEMO short-circuit
    (Plan 04 line 199) returns BEFORE any SDK client is constructed.
    """
    from unittest.mock import AsyncMock

    monkeypatch.setenv("OFFLINE_DEMO", "true")
    monkeypatch.setenv("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")

    import backend.config
    import backend.pipeline.moderate
    importlib.reload(backend.config)
    importlib.reload(backend.pipeline.moderate)

    # Mock db.write_moderation_decision so the OFFLINE_DEMO row write doesn't
    # require the moderation_decisions table to exist in SQLite SCHEMA_SQL
    # (Plan 03 deferred issue under SQLite-backend retirement).
    write_decision = AsyncMock(return_value="dec_id_1")
    monkeypatch.setattr(backend.pipeline.moderate.db, "write_moderation_decision", write_decision)

    # Register Gemini routes — every call_count must be zero after moderate_clip.
    upload_route = respx_mock.post(
        "https://generativelanguage.googleapis.com/upload/v1beta/files"
    ).respond(json={})
    poll_route = respx_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/files/test"
    ).respond(json={})
    generate_route = respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    ).respond(json={})
    delete_route = respx_mock.delete(
        "https://generativelanguage.googleapis.com/v1beta/files/test"
    ).respond(json={})

    result = await backend.pipeline.moderate.moderate_clip("clip_offline_demo_test")

    assert result.decision == "passed"
    assert result.provider == "stub"
    assert upload_route.call_count == 0, "Gemini upload was called under OFFLINE_DEMO=true (MOD-10 violation)"
    assert poll_route.call_count == 0, "Gemini files-poll was called under OFFLINE_DEMO=true (MOD-10 violation)"
    assert generate_route.call_count == 0, "Gemini generateContent was called under OFFLINE_DEMO=true (MOD-10 violation)"
    assert delete_route.call_count == 0, "Gemini files-cleanup was called under OFFLINE_DEMO=true (MOD-10 violation)"


@pytest.mark.asyncio
async def test_offline_demo_writes_moderation_row_to_sqlite(monkeypatch, tmp_path):
    """CR-04 regression: OFFLINE_DEMO=true must end-to-end persist a moderation_decisions
    row to a real SQLite DB — no mocks. SCHEMA_SQL + init() must declare every Phase 11
    table/column the OFFLINE_DEMO write path touches.
    """
    monkeypatch.setenv("OFFLINE_DEMO", "true")
    monkeypatch.setenv("METADATA_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")

    import backend.config
    importlib.reload(backend.config)
    import backend.db_sqlite
    importlib.reload(backend.db_sqlite)
    import backend.db
    importlib.reload(backend.db)
    import backend.pipeline.moderate as mod
    importlib.reload(mod)

    # Initialize the schema in the fresh tmp_path DB. CR-04 fix: this now
    # creates moderation_decisions + reported_csam + clips.is_hidden alongside
    # the v1.0 tables, so the OFFLINE_DEMO write path doesn't crash.
    await mod.db.init()

    # Run the gate end-to-end (no mocks of write_moderation_decision).
    result = await mod.moderate_clip("clip_offline_sqlite_test")

    assert result.decision == "passed"
    assert result.provider == "stub"
    assert result.reason == "offline_demo"

    # Verify the row actually landed in SQLite.
    import aiosqlite
    async with aiosqlite.connect(mod.db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT clip_id, provider, decision, reason, prompt_version "
            "FROM moderation_decisions WHERE clip_id = ?",
            ("clip_offline_sqlite_test",),
        ) as cur:
            row = await cur.fetchone()

    assert row is not None, "moderation_decisions row missing in SQLite under OFFLINE_DEMO"
    assert row["provider"] == "stub"
    assert row["decision"] == "passed"
    assert row["reason"] == "offline_demo"
    assert row["prompt_version"] is None
