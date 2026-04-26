"""Tests for save_segment MCP tool — accepts ordered_run_ids and title."""
from unittest.mock import AsyncMock, patch

import pytest

from backend.pipeline.compile_tools import save_segment


@pytest.mark.asyncio
async def test_save_segment_passes_run_ids_and_title():
    insert_mock = AsyncMock(return_value="seg-xyz")
    with patch("backend.pipeline.compile_tools.db.insert_segment", insert_mock):
        # @tool decorator may wrap the function — call the underlying handler.
        handler = getattr(save_segment, "handler", None) or save_segment
        result = await handler({
            "cluster_id": "c1",
            "ordered_run_ids": ["p1_run_0", "p2_run_0"],
            "title": "Multi-angle gathering",
            "caption": "Two contributors filmed people gathered with signs.",
            "location": "Pasadena, CA",
            "source_count": 2,
        })
    text = result["content"][0]["text"]
    assert text == "saved:seg-xyz"
    insert_mock.assert_awaited_once()
    kwargs = insert_mock.await_args.kwargs
    assert kwargs["ordered_clip_ids"] == ["p1_run_0", "p2_run_0"]
    assert kwargs["title"] == "Multi-angle gathering"
    assert kwargs["caption"].startswith("Two contributors")
