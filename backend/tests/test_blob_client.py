"""blob_client unit tests using respx_mock (Pitfall 5).

Covers: D-19 fail-loud (T-10-04), A3 token format, happy-path upload, header
contract (amendment 5), idempotent delete, retry policy (D-24 + amendment 6),
and T-10-01 token-not-in-logs.
"""
import importlib
import logging

import httpx
import pytest


@pytest.fixture
def reload_blob_client(monkeypatch):
    """Reload backend.config + backend.storage.blob_client with desired env."""

    def _do(**env):
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        import backend.config
        import backend.storage.blob_client as bc
        importlib.reload(backend.config)
        importlib.reload(bc)
        return bc

    return _do


@pytest.mark.asyncio
async def test_init_fails_loud_on_empty_token(reload_blob_client):
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN="")
    with pytest.raises(RuntimeError, match="BLOB_READ_WRITE_TOKEN is empty"):
        await bc.init_client()


@pytest.mark.asyncio
async def test_init_fails_on_malformed_token(reload_blob_client):
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN="garbage")
    with pytest.raises(RuntimeError, match="unexpected format"):
        await bc.init_client()


@pytest.mark.asyncio
async def test_upload_happy_path(reload_blob_client, respx_mock):
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN="vercel_blob_rw_TESTSTORE_xxxxx")
    respx_mock.put("https://vercel.com/api/blob").respond(
        json={
            "url": "https://teststore.private.blob.vercel-storage.com/uploads/x.mp4",
            "downloadUrl": "https://teststore.private.blob.vercel-storage.com/uploads/x.mp4",
            "pathname": "uploads/x.mp4",
            "contentType": "video/mp4",
            "contentDisposition": "",
        },
    )
    await bc.init_client()
    try:
        obj = await bc.upload(
            pathname="uploads/x.mp4",
            body=b"data",
            content_type="video/mp4",
            access="private",
        )
        assert obj["pathname"] == "uploads/x.mp4"
        assert obj["url"].startswith("https://teststore.private.blob.vercel-storage.com/")
    finally:
        await bc.close_client()


@pytest.mark.asyncio
async def test_upload_includes_required_headers(reload_blob_client, respx_mock):
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN="vercel_blob_rw_TESTSTORE_xxxxx")
    route = respx_mock.put("https://vercel.com/api/blob").respond(
        json={"url": "https://x", "downloadUrl": "https://x",
              "pathname": "uploads/x.mp4", "contentType": "video/mp4",
              "contentDisposition": ""},
    )
    await bc.init_client()
    try:
        await bc.upload(
            pathname="uploads/x.mp4",
            body=b"d",
            content_type="video/mp4",
            access="private",
        )
        sent = route.calls.last.request
        assert sent.headers.get("authorization", "").startswith("Bearer ")
        assert sent.headers.get("x-api-version") == "11"
        assert sent.headers.get("x-vercel-blob-access") == "private"
        assert sent.headers.get("x-allow-overwrite") == "1"
    finally:
        await bc.close_client()


@pytest.mark.asyncio
async def test_delete_idempotent_on_404(reload_blob_client, respx_mock):
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN="vercel_blob_rw_TESTSTORE_xxxxx")
    respx_mock.post("https://vercel.com/api/blob/delete").respond(404)
    await bc.init_client()
    try:
        # Must not raise.
        await bc.delete(pathname="uploads/missing.mp4")
    finally:
        await bc.close_client()


@pytest.mark.asyncio
async def test_5xx_retries_three_times(reload_blob_client, respx_mock):
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN="vercel_blob_rw_TESTSTORE_xxxxx")
    body = {
        "url": "https://x", "downloadUrl": "https://x",
        "pathname": "uploads/x.mp4", "contentType": "video/mp4",
        "contentDisposition": "",
    }
    route = respx_mock.put("https://vercel.com/api/blob").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, json=body),
        ],
    )
    await bc.init_client()
    try:
        obj = await bc.upload(
            pathname="uploads/x.mp4",
            body=b"d",
            content_type="video/mp4",
            access="private",
        )
        assert obj["pathname"] == "uploads/x.mp4"
        assert route.call_count == 3
    finally:
        await bc.close_client()

    # 4 consecutive 500s should raise.
    bc2 = reload_blob_client(BLOB_READ_WRITE_TOKEN="vercel_blob_rw_TESTSTORE_xxxxx")
    respx_mock.reset()
    respx_mock.put("https://vercel.com/api/blob").respond(500)
    await bc2.init_client()
    try:
        with pytest.raises(Exception):
            await bc2.upload(
                pathname="uploads/x.mp4",
                body=b"d",
                content_type="video/mp4",
                access="private",
            )
    finally:
        await bc2.close_client()


@pytest.mark.asyncio
async def test_429_retries(reload_blob_client, respx_mock):
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN="vercel_blob_rw_TESTSTORE_xxxxx")
    body = {
        "url": "https://x", "downloadUrl": "https://x",
        "pathname": "uploads/x.mp4", "contentType": "video/mp4",
        "contentDisposition": "",
    }
    route = respx_mock.put("https://vercel.com/api/blob").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=body),
        ],
    )
    await bc.init_client()
    try:
        obj = await bc.upload(
            pathname="uploads/x.mp4",
            body=b"d",
            content_type="video/mp4",
            access="private",
        )
        assert obj["pathname"] == "uploads/x.mp4"
        assert route.call_count == 3
    finally:
        await bc.close_client()


@pytest.mark.asyncio
async def test_no_token_in_logs(reload_blob_client, respx_mock, caplog):
    token = "vercel_blob_rw_TESTSTORE_xxxxx"
    bc = reload_blob_client(BLOB_READ_WRITE_TOKEN=token)
    respx_mock.put("https://vercel.com/api/blob").respond(
        json={
            "url": "https://x", "downloadUrl": "https://x",
            "pathname": "uploads/x.mp4", "contentType": "video/mp4",
            "contentDisposition": "",
        },
    )
    caplog.set_level(logging.DEBUG, logger="backend.storage.blob_client")
    await bc.init_client()
    try:
        await bc.upload(
            pathname="uploads/x.mp4",
            body=b"d",
            content_type="video/mp4",
            access="private",
        )
    finally:
        await bc.close_client()

    for record in caplog.records:
        assert token not in record.getMessage(), (
            f"bearer token leaked in log message: {record.getMessage()!r}"
        )
        for v in record.__dict__.values():
            if isinstance(v, str):
                assert token not in v, f"bearer token leaked in record attr: {v!r}"
