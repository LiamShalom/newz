"""In-memory per-session rate limiter for anonymous comments (Phase 01 feature track).

Single-process FastAPI + --workers 1 makes process-local state authoritative.
Resets on restart — acceptable at pilot scale; revisit if we move beyond one worker
or persist this layer.
"""
import asyncio
import time
from collections import defaultdict, deque

# (max_count, window_seconds)
COMMENT_LIMITS: list[tuple[int, int]] = [
    (5, 300),     # 5 per 5 minutes
    (10, 3600),   # 10 per hour
]

_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()
_LARGEST_WINDOW = max(w for _, w in COMMENT_LIMITS)


async def check_and_record(session_id: str) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds).

    On allow, records the attempt timestamp (so subsequent calls see it).
    On block, retry_after is the minimum delay until at least one window has room.
    """
    now = time.time()
    async with _lock:
        bucket = _attempts[session_id]
        cutoff = now - _LARGEST_WINDOW
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        for max_count, window in COMMENT_LIMITS:
            since = now - window
            in_window = [ts for ts in bucket if ts >= since]
            if len(in_window) >= max_count:
                oldest = in_window[0]
                return False, max(1, int(oldest + window - now) + 1)
        bucket.append(now)
        return True, 0


def _reset_for_tests() -> None:
    """Test-only — flush in-memory state between cases."""
    _attempts.clear()
