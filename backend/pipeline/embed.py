"""
backend/pipeline/embed.py

Marengo 3.0 embed stage for the Newz pipeline.

Public API:
    embed_worker(clip_id, conn) -> np.ndarray
        Called by run_pipeline(). Wraps _sync_embed in a thread-pool executor so
        the synchronous TwelveLabs SDK never blocks the FastAPI event loop.

Private helpers:
    _sync_embed(clip_path, clip_id) -> tuple[np.ndarray, int]
        Synchronous. Runs in thread pool. Either calls Marengo (real) or returns
        a deterministic mock vector.
    _mock_embedding(clip_id) -> np.ndarray
        Deterministic unit vector keyed by clip_id. Same output on every call for
        the same ID (stable across restarts).
"""

import asyncio
import logging
import time
from pathlib import Path

import numpy as np
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import config
import db as db_module

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock embedding (USE_MOCK_EMBEDDINGS=true)
# ---------------------------------------------------------------------------

def _mock_embedding(clip_id: str) -> np.ndarray:
    """
    Return a deterministic 512-d unit vector for clip_id.

    Seed derivation: int.from_bytes(clip_id.encode('utf-8')[:8], 'big') % 2**32
    This is stable across Python restarts (unlike hash() which uses PYTHONHASHSEED).
    """
    seed = int.from_bytes(clip_id.encode("utf-8")[:8], "big") % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.random(512).astype(np.float32)
    vec /= np.linalg.norm(vec) + 1e-12
    return vec


# ---------------------------------------------------------------------------
# Real Marengo embed (SDK v2 two-step: assets.create -> embed.v_2.create)
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_marengo(clip_path: str, clip_id: str) -> tuple[np.ndarray, int]:
    """
    Synchronous Marengo embed call. Run only inside run_in_executor.

    Two-step SDK v2 pattern:
      1. client.assets.create(method="direct", file=...) -> asset with .id
      2. client.embed.v_2.create(input_type="video", model_name="marengo3.0", video=...) -> response

    Returns (normalized 512-d float32 vector, latency_ms).

    NOTE: VideoInputRequest and MediaSource import from twelvelabs.types (not
    twelvelabs.models.embed — that module does not exist in SDK v1.2.3).
    """
    from twelvelabs import TwelveLabs
    from twelvelabs.types import MediaSource, VideoInputRequest

    # Never log the API key — T-02-01 mitigation.
    client = TwelveLabs(api_key=config.TWELVELABS_API_KEY)
    t0 = time.monotonic()

    # Step 1: Upload the local clip file as a TwelveLabs asset
    with open(clip_path, "rb") as f:
        asset = client.assets.create(method="direct", file=f)

    log.debug("embed asset_id=%s clip_id=%s upload_done", asset.id, clip_id)

    # Step 2: Synchronous embed (returns immediately for clips <10 min)
    response = client.embed.v_2.create(
        input_type="video",
        model_name="marengo3.0",  # lowercase, no hyphen — locked in CLAUDE.md
        video=VideoInputRequest(
            media_source=MediaSource(asset_id=asset.id),
            embedding_option=["visual", "audio", "transcription"],
            embedding_scope=["asset"],          # ONE vector per clip (not per ~6s segment)
            embedding_type=["fused_embedding"],  # single 512-d combined vector
        ),
    )

    latency_ms = int((time.monotonic() - t0) * 1000)

    # response.data[0].embedding is a Python list of 512 floats
    vec = np.array(response.data[0].embedding, dtype=np.float32)
    vec /= np.linalg.norm(vec) + 1e-12  # L2 normalize for cosine ops in Phase 3

    # Log clip_id and latency only — never log lat/lng or session_uuid (T-02-03 mitigation).
    log.info(
        "embed clip_id=%s latency_ms=%d dims=%d norm=%.4f",
        clip_id, latency_ms, len(vec), float(np.linalg.norm(vec)),
    )
    return vec, latency_ms


def _sync_embed(clip_path: str, clip_id: str) -> tuple[np.ndarray, int]:
    """
    Dispatcher called from run_in_executor.
    Routes to mock or real based on config.USE_MOCK_EMBEDDINGS (bool).
    """
    if config.USE_MOCK_EMBEDDINGS:
        log.info("embed mock clip_id=%s", clip_id)
        return _mock_embedding(clip_id), 0
    return _call_marengo(clip_path, clip_id)


# ---------------------------------------------------------------------------
# embed_worker — async entry point called by run_pipeline(clip_id)
# ---------------------------------------------------------------------------

async def embed_worker(clip_id: str, conn) -> np.ndarray:
    """
    Async embed stage. Called by run_pipeline(clip_id) in app.py.

    1. Reads clip path from DB (clips.path column).
    2. Runs _sync_embed in the default thread pool (keeps event loop unblocked).
    3. Calls store_embedding to persist BLOB + latency + status=done.
    4. Returns the 512-d numpy array for the next pipeline stage (cluster_worker).

    On failure: sets embedding_status='failed', re-raises so run_pipeline can
    broadcast pipeline_error.

    Security (T-02-02): clip_path comes from DB (not user input); Path.exists()
    validated before open; no path traversal possible since path written by ingest.
    """
    # Fetch clip path from DB
    clip = await db_module.get_clip(clip_id, conn)
    if clip is None:
        raise ValueError(f"embed_worker: clip {clip_id!r} not found in DB")

    clip_path = clip["path"]
    if not Path(clip_path).exists():
        raise FileNotFoundError(f"embed_worker: clip file missing at {clip_path!r}")

    try:
        loop = asyncio.get_event_loop()
        vec, latency_ms = await loop.run_in_executor(
            None,         # default ThreadPoolExecutor
            _sync_embed,  # synchronous function — safe in thread pool
            clip_path,
            clip_id,
        )
        await db_module.store_embedding(clip_id, vec, latency_ms, conn)
        return vec

    except Exception:
        # Mark as failed so the UI can show an error state
        await conn.execute(
            "UPDATE clips SET embedding_status = 'failed' WHERE id = ?",
            (clip_id,),
        )
        await conn.commit()
        raise
