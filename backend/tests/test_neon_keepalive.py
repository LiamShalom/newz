"""Phase 9 (DEMO-03): Neon keepalive task tests.

_neon_keepalive(pool) loops: pool.fetchval('SELECT 1') → log → sleep(240s).
These tests mock the pool + sleep so we can validate the loop semantics in
under a second without a live Neon connection.

Note: `_neon_keepalive` is added by plan 09-07 (parallel wave 4). When this
worktree is run before 09-07 merges, the function is absent and these tests
skip cleanly. Post-merge the verifier sees them green.
"""
import asyncio
import unittest.mock as mock

import pytest


def _require_neon_keepalive():
    """Skip the test if 09-07's `_neon_keepalive` hasn't merged yet."""
    from backend import app
    if not hasattr(app, "_neon_keepalive"):
        pytest.skip(
            "_neon_keepalive not yet present in backend.app (09-07 dependency); "
            "post-merge the verifier exercises this test."
        )
    return app._neon_keepalive


@pytest.mark.asyncio
async def test_neon_keepalive_pings_pool_and_sleeps_at_interval(monkeypatch):
    """DEMO-03: keepalive pings via pool.fetchval('SELECT 1') and sleeps for
    config.KEEPALIVE_INTERVAL_S between iterations."""
    keepalive = _require_neon_keepalive()
    from backend import config

    # Mock the pool: fetchval returns 1 immediately.
    pool = mock.MagicMock()
    pool.fetchval = mock.AsyncMock(return_value=1)

    # Patch asyncio.sleep so we don't wait 240 real seconds. Each call records
    # the requested interval and returns immediately.
    sleep_calls = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        # Cancel the keepalive task after 3 iterations so the test terminates.
        if len(sleep_calls) >= 3:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    task = asyncio.create_task(keepalive(pool))
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Verify SELECT 1 was issued at least 3 times (one per iteration before cancel).
    assert pool.fetchval.await_count >= 3
    pool.fetchval.assert_any_await("SELECT 1")
    # Verify the configured interval was passed to asyncio.sleep.
    assert all(s == config.KEEPALIVE_INTERVAL_S for s in sleep_calls), (
        f"unexpected sleep intervals: {sleep_calls}"
    )


@pytest.mark.asyncio
async def test_neon_keepalive_warns_on_pool_failure_but_continues(monkeypatch):
    """DEMO-03: keepalive logs WARNING on pool failure but does NOT raise —
    transient Neon errors should not crash the backend."""
    keepalive = _require_neon_keepalive()

    pool = mock.MagicMock()
    # First call raises, second call succeeds — must continue past the failure.
    pool.fetchval = mock.AsyncMock(side_effect=[RuntimeError("simulated neon error"), 1])

    real_sleep = asyncio.sleep
    iteration = [0]

    async def fake_sleep(seconds):
        iteration[0] += 1
        if iteration[0] >= 2:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    task = asyncio.create_task(keepalive(pool))
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Both attempts should have been made — failure did not break the loop.
    assert pool.fetchval.await_count >= 2
