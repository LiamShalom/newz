"""
Tests for backend/pipeline/compile.py — timeout + exception fallback paths.

Verifies:
  - asyncio.TimeoutError on the gather → outer except clause fires fallback
  - Branch A exception → inner fallback path
  Both paths must clear the in-flight flag and broadcast segment_published.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_compile_segment_timeout_uses_fallback():
    """asyncio.wait_for raises TimeoutError → outer except triggers fallback."""
    fallback_id = "seg-fallback-001"

    async def fake_wait_for(coro, timeout):
        # cleanly close the gather coroutine so we don't leak a warning
        if asyncio.iscoroutine(coro):
            coro.close()
        raise asyncio.TimeoutError()

    with patch("backend.pipeline.compile.asyncio.wait_for", side_effect=fake_wait_for), \
         patch("backend.pipeline.compile._save_fallback_segment",
               new_callable=AsyncMock, return_value=fallback_id) as mock_fallback, \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        # Phase 14: compile_segment now reads get_segment_for_cluster at the top
        # to detect first-publish vs recompile for the SSE payload + soft-warn
        # counter. Mock as None (first-publish path) so the timeout test stays
        # focused on the timeout fallback behavior.
        mock_db.get_segment_for_cluster = AsyncMock(return_value=None)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-timeout")

    mock_fallback.assert_awaited_once()
    assert mock_fallback.await_args.args[0] == "cluster-timeout"

    mock_db.set_compile_in_flight.assert_awaited_with("cluster-timeout", False)

    broadcast_calls = mock_events.broadcast.await_args_list
    event_types = [c.args[0]["type"] for c in broadcast_calls]
    assert "segment_published" in event_types

    pub_call = next(c for c in broadcast_calls if c.args[0]["type"] == "segment_published")
    assert pub_call.args[0]["segment_id"] == fallback_id


@pytest.mark.asyncio
async def test_compile_segment_branch_a_exception_uses_fallback():
    """Branch A raises → inner fallback path; flag cleared; segment_published broadcast."""
    fallback_id = "seg-fallback-002"

    async def failing_branch_a(cid):
        raise RuntimeError("orchestrator failed")

    async def passing_branch_b(cid):
        return None

    with patch("backend.pipeline.compile._run_orchestrator_chain",
               side_effect=failing_branch_a), \
         patch("backend.pipeline.compile._branch_caption",
               side_effect=passing_branch_b), \
         patch("backend.pipeline.compile._save_fallback_segment",
               new_callable=AsyncMock, return_value=fallback_id) as mock_fallback, \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_db.get_segment_for_cluster = AsyncMock(return_value=None)
        mock_db.insert_segment = AsyncMock(return_value=fallback_id)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-exception")

    mock_fallback.assert_awaited()
    assert mock_fallback.await_args.args[0] == "cluster-exception"

    mock_db.set_compile_in_flight.assert_awaited_with("cluster-exception", False)

    broadcast_calls = mock_events.broadcast.await_args_list
    event_types = [c.args[0]["type"] for c in broadcast_calls]
    assert "segment_published" in event_types

    pub_call = next(c for c in broadcast_calls if c.args[0]["type"] == "segment_published")
    assert pub_call.args[0]["segment_id"] == fallback_id
