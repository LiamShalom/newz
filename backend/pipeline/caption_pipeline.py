"""
backend/pipeline/caption_pipeline.py — frame-based visual caption pipeline (Phase 4.5, CMP-08).

Public API:
    generate_caption(cluster_id, centroid, children) -> dict | None
        Async. Selects 2-3 children closest to centroid by cosine similarity.
        Extracts 3 JPEG frames per selected child.
        Sends frames to Claude Haiku for per-clip descriptions.
        Aggregates descriptions → Claude Sonnet for AP-wire headline.
        Returns {"caption": str, "location": str, "source": "vision"} on success.

        If USE_MOCK_EMBEDDINGS=true: skips all API calls, returns hardcoded test caption.
        On failure: returns None so the compile.py call site preserves the Track A
        (subagent) vision caption rather than overwriting it with a generic fallback.
"""

import asyncio
import base64
import logging
import os
from datetime import datetime, timezone

import numpy as np

from .. import config
from .frames import extract_frames

log = logging.getLogger(__name__)

_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"


def _select_caption_children(
    children: list[dict],
    centroid: np.ndarray,
    n: int = 3,
) -> list[dict]:
    """Return the n children with highest cosine similarity to centroid."""
    scored: list[tuple[float, dict]] = []
    for child in children:
        vec = child.get("vec")
        if vec is None:
            continue
        cos = float(np.dot(vec, centroid))
        scored.append((cos, child))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:n]]


async def _describe_child_frames(client, child: dict) -> str:
    """Extract 3 frames from child clip and ask Claude Haiku to describe them."""
    parent_path = child.get("parent_path", "")
    start = float(child.get("start_offset_sec", 0.0))
    end = float(child.get("end_offset_sec") or start + 3.0)

    frames: list[bytes] = []
    if parent_path:
        frames = await extract_frames(parent_path, start, end, n=3)

    if not frames:
        return "(no visual context available)"

    content = []
    for jpg in frames:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(jpg).decode(),
            },
        })
    content.append({
        "type": "text",
        "text": (
            "Describe what is visually happening in these frames in 1-2 sentences. "
            "Be specific and factual. Focus on observable actions and objects only."
        ),
    })

    msg = await client.messages.create(
        model=_HAIKU,
        max_tokens=150,
        messages=[{"role": "user", "content": content}],
    )
    return msg.content[0].text.strip()


async def generate_caption(
    cluster_id: str,
    centroid: np.ndarray,
    children: list[dict],
) -> dict | None:
    """Build AP-wire headline from visual frames of centroid-closest children.

    children: list of dicts, each must have keys:
        id, parent_path, start_offset_sec, end_offset_sec, lat, lng, ts, vec (np.ndarray or None)
    Returns: {"caption": str, "location": str, "source": "vision"} on success,
             None on fallback (Anthropic unavailable or errored) so the call site
             preserves Track A's vision caption.
    """
    if config.USE_MOCK_EMBEDDINGS:
        log.info("generate_caption mock cluster_id=%s", cluster_id)
        return {
            "caption": "Staged event captured from multiple angles at Caltech campus.",
            "location": "Pasadena, CA",
        }

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        log.warning("generate_caption: ANTHROPIC_API_KEY not set — using fallback caption")
        return _fallback_caption(cluster_id, children)

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=anthropic_key)

        selected = _select_caption_children(children, centroid, n=3)
        if not selected:
            selected = children[:3]

        descriptions = await asyncio.gather(
            *[_describe_child_frames(client, child) for child in selected],
            return_exceptions=True,
        )

        desc_texts = [
            d for d in descriptions
            if isinstance(d, str) and "(no visual" not in d
        ]
        if not desc_texts:
            return _fallback_caption(cluster_id, children)

        location = "Pasadena, CA"

        ts = selected[0].get("ts") if selected else None
        if ts:
            when = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %-d, %Y")
        else:
            when = datetime.now(tz=timezone.utc).strftime("%b %-d, %Y")

        aggregated = "\n".join(f"- {d}" for d in desc_texts)
        synthesis_prompt = (
            f"Write an AP-wire style news headline (200 characters or fewer) for footage "
            f"recorded on {when} in {location}. Ground it ONLY in these descriptions — "
            f"do not add participant counts, motives, or details not in the text:\n\n"
            f"{aggregated}\n\n"
            f"Return ONLY the headline text with no quotes or attribution."
        )

        result = await client.messages.create(
            model=_SONNET,
            max_tokens=80,
            messages=[{"role": "user", "content": synthesis_prompt}],
        )
        caption = result.content[0].text.strip()[:200]
        log.info("generate_caption ok cluster_id=%s caption_len=%d", cluster_id, len(caption))
        return {"caption": caption, "location": location, "source": "vision"}

    except Exception as exc:
        log.warning("generate_caption failed cluster_id=%s: %s — using fallback", cluster_id, exc)
        return _fallback_caption(cluster_id, children)


def _fallback_caption(cluster_id: str, children: list[dict]) -> dict | None:
    """Track C fallback — Anthropic unavailable or errored.

    Returns None so the compile.py call site preserves Track A's vision-grounded
    caption (RUNTIME-CAP-01). Previously emitted a generic "multi-angle event
    captured…" template that overwrote Track A's good output.
    """
    log.info("caption fallback (returning None) cluster_id=%s", cluster_id)
    return None
