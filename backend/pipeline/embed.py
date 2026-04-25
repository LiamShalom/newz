"""
backend/pipeline/embed.py — Marengo 3.0 embed stage.

Public API:
    embed_worker(clip_id) -> np.ndarray
        Async entry point. Called by run_pipeline(). Never blocks the event loop.

Private helpers:
    _sync_embed(clip_path, clip_id) -> tuple[np.ndarray, int]
        Synchronous dispatcher — runs in thread pool.
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
def _call_marengo(clip_path: str, clip_id: str) -> tuple[np.ndarray, int]:
    """Synchronous Marengo embed. Run only inside run_in_executor.

    SDK v2 two-step: assets.create -> embed.v_2.create.
    VideoInputRequest and MediaSource are in twelvelabs.types (not twelvelabs.models.embed).
    """
    from twelvelabs import TwelveLabs
    from twelvelabs.types import MediaSource, VideoInputRequest

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
            embedding_scope=["asset"],
            embedding_type=["fused_embedding"],
        ),
    )

    latency_ms = int((time.monotonic() - t0) * 1000)
    vec = np.array(response.data[0].embedding, dtype=np.float32)
    vec /= np.linalg.norm(vec) + 1e-12
    log.info("embed clip_id=%s latency_ms=%d dims=%d", clip_id, latency_ms, len(vec))
    return vec, latency_ms


def _sync_embed(clip_path: str, clip_id: str) -> tuple[np.ndarray, int]:
    if config.USE_MOCK_EMBEDDINGS:
        log.info("embed mock clip_id=%s", clip_id)
        return _mock_embedding(clip_id), 0
    return _call_marengo(clip_path, clip_id)


async def embed_worker(clip_id: str) -> np.ndarray:
    """Async embed stage. Called by run_pipeline(clip_id).

    Reads clip path from DB, runs _sync_embed in thread pool, persists BLOB.
    Returns 512-d vector for cluster_worker (Phase 3).
    """
    clip = await db.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"embed_worker: clip {clip_id!r} not found")

    clip_path = clip["path"]
    if not Path(clip_path).exists():
        raise FileNotFoundError(f"embed_worker: file missing at {clip_path!r}")

    try:
        loop = asyncio.get_event_loop()
        vec, latency_ms = await loop.run_in_executor(None, _sync_embed, clip_path, clip_id)
        await db.store_embedding(clip_id, vec, latency_ms)
        return vec
    except Exception:
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                "UPDATE clips SET embedding_status = 'failed' WHERE id = ?", (clip_id,)
            )
            await conn.commit()
        raise
