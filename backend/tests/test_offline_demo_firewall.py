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
