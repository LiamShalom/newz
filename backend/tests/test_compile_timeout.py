"""
Tests for backend/pipeline/compile.py — timeout + exception fallback paths.

Verifies:
  - asyncio.TimeoutError path calls _save_fallback_segment, clears flag, broadcasts segment_published
  - Exception path same guarantees
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_compile_segment_timeout_uses_fallback():
    """On asyncio.TimeoutError, fallback segment is used and flag cleared."""
    fallback_id = "seg-fallback-001"

    async def fake_query_timeout(prompt, options):
        raise asyncio.TimeoutError()
        # unreachable but needed to make this an async generator
        yield  # noqa: unreachable

    with patch("backend.pipeline.compile.query", side_effect=fake_query_timeout), \
         patch("backend.pipeline.compile._run_agents",
               side_effect=asyncio.TimeoutError()) as mock_run, \
         patch("backend.pipeline.compile._save_fallback_segment",
               new_callable=AsyncMock, return_value=fallback_id) as mock_fallback, \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-timeout")

        # Fallback was called
        mock_fallback.assert_awaited_once_with("cluster-timeout")

        # Flag cleared in finally
        mock_db.set_compile_in_flight.assert_awaited_with("cluster-timeout", False)

        # segment_published was still broadcast (with fallback id)
        broadcast_calls = mock_events.broadcast.await_args_list
        event_types = [c.args[0]["type"] for c in broadcast_calls]
        assert "segment_published" in event_types

        pub_call = next(c for c in broadcast_calls if c.args[0]["type"] == "segment_published")
        assert pub_call.args[0]["segment_id"] == fallback_id


@pytest.mark.asyncio
async def test_compile_segment_exception_uses_fallback():
    """On unexpected Exception, fallback is used, flag cleared, segment_published broadcast."""
    fallback_id = "seg-fallback-002"

    with patch("backend.pipeline.compile._run_agents",
               side_effect=RuntimeError("agent failed")) as mock_run, \
         patch("backend.pipeline.compile._save_fallback_segment",
               new_callable=AsyncMock, return_value=fallback_id) as mock_fallback, \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-exception")

        mock_fallback.assert_awaited_once_with("cluster-exception")
        mock_db.set_compile_in_flight.assert_awaited_with("cluster-exception", False)

        broadcast_calls = mock_events.broadcast.await_args_list
        event_types = [c.args[0]["type"] for c in broadcast_calls]
        assert "segment_published" in event_types
