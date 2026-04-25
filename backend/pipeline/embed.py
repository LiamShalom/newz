"""
backend/pipeline/embed.py — Marengo 3.0 embed stage.

Public API:
    embed_worker(clip_id) -> list[tuple[str, np.ndarray]]
        Async entry point. Called by run_pipeline(). Never blocks the event loop.
        Returns [(child_id, vec), ...] for clips that produce children,
        or [(clip_id, parent_vec)] for short clips with no children.

Private helpers:
    _sync_embed(clip_path, clip_id) -> tuple[np.ndarray, list[dict], int]
        Synchronous dispatcher — runs in thread pool.
    _call_marengo(clip_path, clip_id) -> tuple[np.ndarray, list[dict], int]
        Synchronous Marengo embed with native segmentation. Run only inside run_in_executor.
    _mock_embedding(clip_id) -> np.ndarray
        Deterministic unit vector, stable across restarts (OFFLINE_DEMO safe).
"""

import asyncio
import logging
import time
from pathlib import Path

import numpy as np
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import config, db

log = logging.getLogger(__name__)


def _mock_embedding(clip_id: str) -> np.ndarray:
    """Deterministic 512-d unit vector keyed by clip_id (PYTHONHASHSEED-stable)."""
    seed = int.from_bytes(clip_id.encode("utf-8")[:8], "big") % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.random(512).astype(np.float32)
    vec /= np.linalg.norm(vec) + 1e-12
    return vec


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
    if config.USE_MOCK_EMBEDDINGS:
        log.info("embed mock clip_id=%s", clip_id)
        parent_vec = _mock_embedding(clip_id)
        # Generate 3 deterministic fake children at 0-3s, 3-6s, 6-9s
        children = []
        for i in range(3):
            child_id_key = f"{clip_id}_child_{i * 3}"
            cvec = _mock_embedding(child_id_key)
            children.append({
                "start_offset_sec": float(i * 3),
                "end_offset_sec": float(i * 3 + 3),
                "vec": cvec,
            })
        return parent_vec, children, 0
    return _call_marengo(clip_path, clip_id)


async def embed_worker(clip_id: str) -> list[tuple[str, np.ndarray]]:
    """Async embed stage. Called by run_pipeline(clip_id).

    Phase 4.5: returns list of (id, vec) pairs for cluster_worker.
    - If clip produces children: returns [(child_id, vec), ...] — children cluster, not parent.
    - If clip is short (<= 3s, no children returned): returns [(clip_id, parent_vec)].

    Reads clip path from DB, runs _sync_embed in thread pool, persists parent + child BLOBs.
    """
    clip = await db.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"embed_worker: clip {clip_id!r} not found")

    clip_path = clip["path"]
    if not Path(clip_path).exists():
        raise FileNotFoundError(f"embed_worker: file missing at {clip_path!r}")

    try:
        loop = asyncio.get_event_loop()
        parent_vec, children, latency_ms = await loop.run_in_executor(
            None, _sync_embed, clip_path, clip_id
        )
        # Always store parent embedding
        await db.store_embedding(clip_id, parent_vec, latency_ms)

        if not children:
            # Short clip — parent enters clustering directly
            return [(clip_id, parent_vec)]

        # Insert child rows and store their embeddings
        results: list[tuple[str, np.ndarray]] = []
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
            results.append((child_id, child["vec"]))
        return results

    except Exception:
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE clips SET embedding_status = 'failed' WHERE id = ?", (clip_id,)
            )
            await conn.commit()
        raise
