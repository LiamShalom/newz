"""
backend/pipeline/embed.py — Marengo 3.0 embed stage.

Public API:
    embed_worker(clip_id) -> tuple[str, np.ndarray]
        Async entry point. Called by run_pipeline(). Never blocks the event loop.
        Returns exactly one (parent_clip_id, parent_vec) pair.
        Phase 4.6 pivot: clustering operates on the parent (asset-scope) vector
        only — children are still inserted + embedded for compile-time slicing,
        but they do NOT enter the clustering loop.

Private helpers:
    _sync_embed(clip_path, clip_id) -> tuple[np.ndarray, list[dict], int]
        Synchronous dispatcher — runs in thread pool.
    _call_marengo(clip_path, clip_id) -> tuple[np.ndarray, list[dict], int]
        Synchronous Marengo embed with native segmentation. Run only inside run_in_executor.
"""

import asyncio
import logging
import tempfile
import time
from pathlib import Path

import numpy as np
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import config, db

log = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_marengo(
    clip_path: str, clip_id: str
) -> tuple[np.ndarray, list[dict], int]:
    """Synchronous Marengo embed with native segmentation. Run only inside run_in_executor.

    Returns (parent_vec, children, latency_ms).
    children = [{"start_offset_sec": float, "end_offset_sec": float, "vec": np.ndarray}, ...]
    children is empty list if API returns no clip-scope items (clip too short).
    """
    from twelvelabs import TwelveLabs
    from twelvelabs.types import (
        MediaSource,
        VideoInputRequest,
        VideoSegmentation_Fixed,
        VideoSegmentationFixedFixed,
    )

    client = TwelveLabs(api_key=config.TWELVELABS_API_KEY)
    t0 = time.monotonic()

    with open(clip_path, "rb") as f:
        asset = client.assets.create(method="direct", file=f)

    response = client.embed.v_2.create(
        input_type="video",
        model_name="marengo3.0",
        video=VideoInputRequest(
            media_source=MediaSource(asset_id=asset.id),
            embedding_option=["visual", "audio", "transcription"],
            embedding_scope=["clip", "asset"],
            embedding_type=["fused_embedding"],
            segmentation=VideoSegmentation_Fixed(
                fixed=VideoSegmentationFixedFixed(duration_sec=3)
            ),
        ),
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    parent_vec: np.ndarray | None = None
    children: list[dict] = []

    for item in response.data:
        raw = np.array(item.embedding, dtype=np.float32)
        raw /= np.linalg.norm(raw) + 1e-12
        if item.embedding_scope == "asset":
            parent_vec = raw
        elif item.embedding_scope == "clip":
            children.append({
                "start_offset_sec": float(item.start_sec or 0),
                "end_offset_sec": float(item.end_sec or 0),
                "vec": raw,
            })

    if parent_vec is None:
        # Fallback: use first child as parent if asset-scope missing
        if children:
            parent_vec = children[0]["vec"]
        else:
            raise RuntimeError(f"Marengo returned no embeddings for clip {clip_id!r}")

    log.info(
        "embed clip_id=%s latency_ms=%d parent_dims=%d children=%d",
        clip_id, latency_ms, len(parent_vec), len(children),
    )
    return parent_vec, children, latency_ms


def _sync_embed(
    clip_path: str, clip_id: str
) -> tuple[np.ndarray, list[dict], int]:
    return _call_marengo(clip_path, clip_id)


async def embed_worker(clip_id: str) -> tuple[str, np.ndarray]:
    """Async embed stage. Called by run_pipeline(clip_id).

    Phase 4.6: returns (parent_clip_id, parent_vec) — exactly one pair.
    Children are still inserted + embedded but cluster on the parent only
    (per locked architectural pivot). Children remain in the DB for
    compile-time slicing (Angle Selector / Caption Writer / stitch).

    Reads clip path from DB, runs _sync_embed in thread pool, persists parent + child BLOBs.
    """
    clip = await db.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"embed_worker: clip {clip_id!r} not found")

    blob_url = clip.get("blob_url")
    db_path = clip.get("path")

    tmp_path: str | None = None
    if blob_url:
        # Phase 10 blob mode: download private blob to a tempfile so the
        # synchronous Marengo SDK (open(clip_path, "rb")) has a real fd.
        # Mirrors the compile.py:42-67 _download_refs_to_tempdir streaming
        # pattern (chunk_size=64 KiB) to avoid loading 100 MiB clips into RAM.
        from ..storage import blob_client
        client = blob_client.get_client()
        headers = {"Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}"}
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
            async with client.stream("GET", blob_url, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    tmp.write(chunk)
        clip_path = tmp_path
    elif db_path and Path(db_path).exists():
        clip_path = db_path
    else:
        raise FileNotFoundError(
            f"embed_worker: clip {clip_id!r} has no readable source "
            f"(path={db_path!r}, blob_url={'set' if blob_url else 'unset'})"
        )

    try:
        loop = asyncio.get_event_loop()
        parent_vec, children, latency_ms = await loop.run_in_executor(
            None, _sync_embed, clip_path, clip_id
        )
        # Always store parent embedding on the parent row
        await db.store_embedding(clip_id, parent_vec, latency_ms)

        # Insert child rows and store their embeddings (compile-time slicing
        # metadata only — children do NOT enter clustering).
        for child in children:
            child_id = await db.insert_child_clip(
                parent_id=clip_id,
                start_offset_sec=child["start_offset_sec"],
                end_offset_sec=child["end_offset_sec"],
                lat=clip["lat"],
                lng=clip["lng"],
                ts=clip["ts"],
                session_id=clip.get("session_id"),
            )
            await db.store_embedding(child_id, child["vec"], latency_ms)

        # Pivot 1: always surface the parent for clustering. Short-clip branch
        # (no children) and long-clip branch both return the same shape.
        return clip_id, parent_vec

    except Exception:
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE clips SET embedding_status = 'failed' WHERE id = ?", (clip_id,)
            )
            await conn.commit()
        raise
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
