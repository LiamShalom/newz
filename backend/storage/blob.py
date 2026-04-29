"""Phase 10 (D-01, D-12, D-20; amendments 1, 2, 5): Vercel Blob storage interface.

Signatures match backend/storage/local.py byte-for-byte (D-12 parity). HTTP
details deferred to backend/storage/blob_client (D-25) — this module never
imports httpx directly.

Access policy (amendment 2): uploads/* is private (Authorization-bearer reads
only); runs/* is public (CDN-direct browser reads). authorized_blob_input
replaces D-03 mint_signed_url (amendment 1) — pure function, no network.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import config
from . import _url, blob_client

log = logging.getLogger(__name__)

__all__ = [
    "save_clip_bytes",
    "delete_clip",
    "get_playable_url",
    "cleanup_blocked_clip",
    "stitch_input_for",
    "authorized_blob_input",
]


async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str:
    mime = f"video/{ext}" if ext in ("mp4", "webm") else "application/octet-stream"
    obj = await blob_client.upload(
        pathname=f"uploads/{clip_id}.{ext}",
        body=contents,
        content_type=mime,
        access="private",
    )
    return obj["url"]


async def delete_clip(path_or_url: str) -> None:
    if not path_or_url:
        return
    if not _url.is_absolute_url(path_or_url):
        # Legacy filesystem path during mixed-mode rollback — ignore.
        return
    pathname = _url.pathname_of_blob_url(path_or_url)
    try:
        await blob_client.delete(pathname=pathname)
    except Exception as exc:
        log.warning(
            "blob delete failed pathname=%s err=%s (idempotent — ignored)",
            pathname, type(exc).__name__,
        )


def get_playable_url(row: dict) -> str | None:
    blob_url = row.get("blob_url")
    if blob_url:
        return blob_url
    path = row.get("path")
    if path:
        return f"/media/{Path(path).name}"
    return None


async def cleanup_blocked_clip(clip_id: str) -> None:
    # D-20 BLOB-08 hook — Phase 11 caller. Idempotent.
    from .. import db
    row = await db.get_clip(clip_id)
    if row is None:
        return
    target = row.get("blob_url") or row.get("path")
    if target:
        await delete_clip(target)


def stitch_input_for(run_row: dict) -> tuple[str, dict[str, str] | None]:
    # Pure function — no network call (amendment 1 supersedes D-06 mint logic).
    parent_blob_url = run_row.get("parent_blob_url")
    if not parent_blob_url:
        # Migration window: row only has path. Fall back to local-mode-style ref.
        return (run_row["parent_path"], None)
    headers = {"Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}"}
    return (parent_blob_url, headers)


def authorized_blob_input(pathname: str) -> tuple[str, dict[str, str]]:
    # Pure helper — replaces D-03 mint_signed_url. No network. Token interpolation only.
    token = config.BLOB_READ_WRITE_TOKEN
    store_id = blob_client._store_id_from_token(token)
    url = f"https://{store_id}.private.blob.vercel-storage.com/{pathname}"
    headers = {"Authorization": f"Bearer {token}"}
    return (url, headers)
