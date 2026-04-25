import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue] = []
_LOCK = asyncio.Lock()


async def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber. Returns a bounded Queue to read events from."""
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    async with _LOCK:
        _subscribers.append(q)
    log.info("sse subscribe total=%d", len(_subscribers))
    return q


async def unsubscribe(q: asyncio.Queue) -> None:
    """Deregister a subscriber queue (called on SSE client disconnect)."""
    async with _LOCK:
        if q in _subscribers:
            _subscribers.remove(q)
    log.info("sse unsubscribe total=%d", len(_subscribers))


async def broadcast(event: dict[str, Any]) -> None:
    """Fan-out event to all SSE subscribers. Drops events for slow clients (QueueFull)."""
    log.info("event %s", event.get("type"))
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("sse subscriber queue full — dropping event %s", event.get("type"))
