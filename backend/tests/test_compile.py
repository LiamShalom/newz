"""
Tests for backend/pipeline/compile.py — happy-path compile_segment.

Mocks:
  - claude_agent_sdk.query() yields a ResultMessage with result="ok"
  - db.get_segment_for_cluster returns a fake segment dict
  - db.set_compile_in_flight called with False in finally
  - events.broadcast called with segment_published
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# We need to mock claude_agent_sdk before compile.py is imported in tests
# so patch at the module level where it's used.


@pytest.mark.asyncio
async def test_compile_segment_happy_path():
    """compile_segment calls set_compile_in_flight(False) in finally and broadcasts segment_published."""
    fake_segment = {
        "id": "seg-abc123",
        "cluster_id": "cluster-xyz",
        "ordered_clip_ids": ["c1", "c2"],
        "caption": "Test caption",
        "location": "Pasadena, CA",
        "source_count": 2,
        "created_at": 1_000_000.0,
    }

    # Build an async generator that yields a ResultMessage then stops
    class FakeResultMessage:
        result = "ok"

    async def fake_query(prompt, options):
        yield FakeResultMessage()

    with patch("backend.pipeline.compile.query", side_effect=fake_query), \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.get_segment_for_cluster = AsyncMock(return_value=fake_segment)
        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-xyz")

        # finally block must clear compile_in_flight
        mock_db.set_compile_in_flight.assert_awaited_with("cluster-xyz", False)

        # segment_published must be broadcast
        broadcast_calls = mock_events.broadcast.await_args_list
        event_types = [c.args[0]["type"] for c in broadcast_calls]
        assert "segment_published" in event_types, f"Expected segment_published, got {event_types}"

        # segment_published payload contains segment_id
        pub_call = next(c for c in broadcast_calls if c.args[0]["type"] == "segment_published")
        assert pub_call.args[0]["segment_id"] == "seg-abc123"
        assert pub_call.args[0]["cluster_id"] == "cluster-xyz"
