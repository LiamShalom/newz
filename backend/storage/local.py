"""Phase 10 (D-12): local-FS lift-and-shift.

Source-of-truth for the lifted logic:
  - db_sqlite.py:168  (path = CLIPS_DIR / f"{clip_id}.{ext}"; path.write_bytes)
  - db_postgres.py:167 (same)
  - db_sqlite.py:202-205 (f"/media/{filename}" URL builder)

Public surface matches backend/storage/blob.py byte-for-byte (D-12 parity).
This is the OFFLINE_DEMO + STORAGE_BACKEND=local rollback path; kept
indefinitely (mirrors Phase 9 D-09 db_sqlite.py posture).
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import config
from . import _url

log = logging.getLogger(__name__)

CLIPS_DIR = config.DATA_DIR / "clips"

__all__ = [
    "save_clip_bytes",
    "delete_clip",
    "get_playable_url",
    "cleanup_blocked_clip",
    "stitch_input_for",
    "authorized_blob_input",
]


async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLIPS_DIR / f"{clip_id}.{ext}"
    path.write_bytes(contents)
    log.info("save_clip id=%s bytes=%d", clip_id, len(contents))
    return str(path)


async def delete_clip(path_or_url: str) -> None:
    if not path_or_url:
        return
    if _url.is_absolute_url(path_or_url):
        # Mixed-mode rollback window: a blob_url showing up while in local mode.
        # Local backend can't authenticate to Vercel; admin/reset already swallows
        # per-path errors (app.py:_delete_paths_async).
        return
    try:
        p = Path(path_or_url)
        if p.is_file():
            p.unlink()
    except FileNotFoundError:
        pass


def get_playable_url(row: dict) -> str | None:
    blob_url = row.get("blob_url")
    if blob_url:
        return blob_url
    path = row.get("path")
    if not path:
        return None
    return f"/media/{Path(path).name}"


async def cleanup_blocked_clip(clip_id: str) -> None:
    # D-20: Phase 11 calls this after writing moderation_status='blocked'.
    # Local mode: best-effort unlink. Idempotent.
    from .. import db
    row = await db.get_clip(clip_id)
    if row is None:
        return
    target = row.get("path") or row.get("blob_url")
    if target:
        await delete_clip(target)


def stitch_input_for(run_row: dict) -> tuple[str, dict[str, str] | None]:
    return (run_row["parent_path"], None)


def authorized_blob_input(pathname: str) -> tuple[str, dict[str, str] | None]:
    return (str(CLIPS_DIR / Path(pathname).name), None)
