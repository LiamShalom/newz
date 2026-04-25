import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue] = []


async def broadcast(event: dict[str, Any]) -> None:
    """Phase 1: subscribers list is always empty (no SSE endpoint yet).
    Phase 4 wires GET /events to populate _subscribers and stream.
    """
    log.info("event %s", event.get("type"))
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
