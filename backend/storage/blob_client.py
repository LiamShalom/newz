"""Phase 10 (D-01, D-02, D-25; amendments 1, 6, 8): raw httpx wrapper over the
Vercel Blob REST API.

Module-level singleton ``_client`` follows the asyncpg pool lifecycle pattern
from db_postgres.py:64-124. ``--workers 1`` (L-08) makes the process-wide
singleton sufficient — no inter-process coordination.

Lifecycle:
    init_client()  — called from app.lifespan startup (D-02). Fail-loud if
                     BLOB_READ_WRITE_TOKEN is empty (D-19).
    close_client() — called from app.lifespan shutdown.
    get_client()   — accessor for downstream callers (e.g. compile.py
                     stitch source download).

Operations:
    upload(*, pathname, body, content_type, access) -> BlobObject
    delete(*, pathname) -> None     (idempotent — 404 swallowed)
    head(*, pathname) -> BlobObject | None

Retry posture (D-24, amendment 6): tenacity exponential backoff on transient
5xx, 429, and httpx.TransportError. 4xx other than 429 fail-fast. 401/403
re-raise without retry.

Amendment 1 supersedes D-03's ``mint_signed_url`` op — Vercel Blob has no
signed-URL feature. The replacement is a pure helper at the storage layer
(backend/storage/blob.authorized_blob_input).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Literal, TypedDict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .. import config

log = logging.getLogger(__name__)


class BlobObject(TypedDict):
    url: str
    pathname: str
    contentType: str
    contentDisposition: str
    downloadUrl: str


class BlobNotFound(Exception):
    pass


class _RetryableHTTPError(Exception):
    """Internal: 5xx and 429 wrap into this so tenacity can retry them."""


_BLOB_API = "https://vercel.com/api/blob"
_BLOB_DELETE_API = "https://vercel.com/api/blob/delete"

_client: httpx.AsyncClient | None = None


def _store_id_from_token(token: str) -> str:
    parts = token.split("_")
    if len(parts) <= 3:
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN has unexpected format "
            "(expected vercel_blob_rw_<store_id>_<random>)"
        )
    return parts[3]


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError(
            "httpx blob client not initialized — backend.app.lifespan must call init_client() first"
        )
    return _client


async def init_client() -> None:
    global _client
    if _client is not None:
        log.warning("init_client called twice; ignoring second call")
        return
    if not config.BLOB_READ_WRITE_TOKEN:
        # D-19: Fail-loud — this branch only reached when STORAGE_BACKEND=blob and
        # OFFLINE_DEMO=false (dispatcher enforces). Empty token is a deploy bug.
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN is empty but STORAGE_BACKEND=blob and OFFLINE_DEMO=false. "
            "Set BLOB_READ_WRITE_TOKEN or flip STORAGE_BACKEND=local to use the local-FS path."
        )
    # Defensive token-format check (RESEARCH Assumption A3).
    _store_id_from_token(config.BLOB_READ_WRITE_TOKEN)
    try:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        log.info("httpx blob client created")
    except Exception as exc:
        log.error("blob client init failed: %s (token redacted)", type(exc).__name__)
        raise


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        log.info("httpx blob client closed")


def _request_id(store_id: str) -> str:
    return f"{store_id}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}",
        "x-api-version": "11",
    }


def _classify_response(resp: httpx.Response, *, pathname: str | None = None) -> None:
    status = resp.status_code
    if status == 404 or status == 410:
        raise BlobNotFound(pathname or "")
    if status == 429 or status >= 500:
        raise _RetryableHTTPError(f"status={status} body={resp.text[:200]}")
    if status >= 400:
        # 401/403/4xx-other: fail-fast (D-24). Surface the response body so
        # 400 Bad Request from the Vercel Blob control plane carries an
        # actionable error message into the log instead of just the URL.
        body = resp.text[:500] if resp.text else "<empty>"
        log.error(
            "blob 4xx response status=%d pathname=%s body=%s",
            status, pathname, body,
        )
        resp.raise_for_status()


_blob_retry = retry(
    retry=retry_if_exception_type((httpx.TransportError, _RetryableHTTPError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
    reraise=True,
)


@_blob_retry
async def upload(
    *,
    pathname: str,
    body: bytes,
    content_type: str,
    access: Literal["public", "private"],
) -> BlobObject:
    client = get_client()
    token = config.BLOB_READ_WRITE_TOKEN
    store_id = _store_id_from_token(token)
    headers = {
        **_auth_headers(),
        "x-api-blob-request-id": _request_id(store_id),
        "x-api-blob-request-attempt": "1",
        "x-content-type": content_type,
        "x-content-length": str(len(body)),
        "x-vercel-blob-access": access,
        "x-add-random-suffix": "0",
        # Amendment 5: deterministic pathname; recompiles overwrite in place.
        "x-allow-overwrite": "1",
    }
    t0 = time.monotonic()
    resp = await client.put(_BLOB_API, params={"pathname": pathname}, headers=headers, content=body)
    _classify_response(resp, pathname=pathname)
    ms = int((time.monotonic() - t0) * 1000)
    log.info("blob op=upload pathname=%s latency_ms=%d bytes=%d", pathname, ms, len(body))
    data: dict[str, Any] = resp.json()
    return BlobObject(
        url=data["url"],
        pathname=data.get("pathname", pathname),
        contentType=data.get("contentType", content_type),
        contentDisposition=data.get("contentDisposition", ""),
        downloadUrl=data.get("downloadUrl", data["url"]),
    )


async def delete(*, pathname: str) -> None:
    client = get_client()
    token = config.BLOB_READ_WRITE_TOKEN
    store_id = _store_id_from_token(token)
    private_url = f"https://{store_id}.private.blob.vercel-storage.com/{pathname}"
    public_url = f"https://{store_id}.public.blob.vercel-storage.com/{pathname}"
    headers = {**_auth_headers(), "Content-Type": "application/json"}
    t0 = time.monotonic()
    try:
        resp = await client.post(
            _BLOB_DELETE_API,
            headers=headers,
            json={"urls": [private_url, public_url]},
        )
    except httpx.TransportError as exc:
        log.warning("blob op=delete pathname=%s transport_error=%s", pathname, type(exc).__name__)
        return
    ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code == 404:
        log.info("blob op=delete pathname=%s status=404 latency_ms=%d (idempotent)", pathname, ms)
        return
    if resp.status_code >= 400:
        log.warning(
            "blob op=delete pathname=%s status=%d latency_ms=%d (idempotent — swallowed)",
            pathname, resp.status_code, ms,
        )
        return
    log.info("blob op=delete pathname=%s latency_ms=%d", pathname, ms)


@_blob_retry
async def head(*, pathname: str) -> BlobObject | None:
    client = get_client()
    token = config.BLOB_READ_WRITE_TOKEN
    store_id = _store_id_from_token(token)
    private_url = f"https://{store_id}.private.blob.vercel-storage.com/{pathname}"
    t0 = time.monotonic()
    resp = await client.get(_BLOB_API, params={"url": private_url}, headers=_auth_headers())
    ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code == 404 or resp.status_code == 410:
        log.info("blob op=head pathname=%s status=404 latency_ms=%d", pathname, ms)
        return None
    _classify_response(resp, pathname=pathname)
    log.info("blob op=head pathname=%s latency_ms=%d", pathname, ms)
    data: dict[str, Any] = resp.json()
    return BlobObject(
        url=data.get("url", private_url),
        pathname=data.get("pathname", pathname),
        contentType=data.get("contentType", ""),
        contentDisposition=data.get("contentDisposition", ""),
        downloadUrl=data.get("downloadUrl", data.get("url", private_url)),
    )
