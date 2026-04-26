"""
Tests for backend/pipeline/compile.py — happy-path compile_segment.

The vision-enabled caption-writer makes one query() call (with image content
blocks) and the orchestrator chain makes another (subagents). The mocks below
patch query() with side_effects keyed off whether the prompt is a string
(orchestrator) or an AsyncIterable (caption-writer).
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


class FakeResultMessage:
    """Mimic ResultMessage's surface used by compile.py."""

    is_error = False
    errors = None
    num_turns = 1
    duration_ms = 100
    result = "ok"


class FakeAssistantMessage:
    """Mimic AssistantMessage with a single TextBlock for the caption JSON."""

    def __init__(self, text: str):
        from claude_agent_sdk import TextBlock
        self.content = [TextBlock(text=text)]
        self.model = "sonnet"


def _make_query_mock(caption_json: str):
    """Build a fake query() that branches on prompt shape.

    - AsyncIterable prompt → caption-writer → yield AssistantMessage(JSON) + ResultMessage
    - str prompt → orchestrator → yield ResultMessage only
    """
    captured = {"caption_user_msg": None}

    async def fake_query(prompt, options):
        if isinstance(prompt, str):
            yield FakeResultMessage()
            return
        # AsyncIterable: drain to capture the user message we sent
        async for msg in prompt:
            captured["caption_user_msg"] = msg
        yield FakeAssistantMessage(caption_json)
        yield FakeResultMessage()

    return fake_query, captured


@pytest.mark.asyncio
async def test_compile_segment_happy_path():
    """Vision caption-writer + orchestrator → segment_published with vision-derived caption."""
    fake_segment = {
        "id": "seg-abc123",
        "cluster_id": "cluster-xyz",
        "ordered_clip_ids": ["c1", "c2"],
        "caption": "People with signs gathered on a Pasadena street, April 25, 2026.",
        "location": "Pasadena, CA",
        "source_count": 2,
        "created_at": 1_000_000.0,
    }
    caption_json = (
        '{"caption": "People with signs gathered on a Pasadena street, April 25, 2026.",'
        ' "location": "Pasadena, CA"}'
    )
    fake_query, captured = _make_query_mock(caption_json)

    fake_clips = [
        {"id": "c1", "path": "/tmp/c1.mp4", "lat": 34.1, "lng": -118.1, "ts": 1_700_000_000.0},
        {"id": "c2", "path": "/tmp/c2.mp4", "lat": 34.11, "lng": -118.11, "ts": 1_700_000_010.0},
    ]
    fake_frames = [("c1", b"\x89PNG\r\n\x1a\n_fake_1"), ("c2", b"\x89PNG\r\n\x1a\n_fake_2")]

    with patch("backend.pipeline.compile.query", side_effect=fake_query), \
         patch("backend.pipeline.compile.extract_cluster_keyframes",
               new_callable=AsyncMock, return_value=fake_frames), \
         patch("backend.pipeline.compile.stitch_clips",
               new_callable=AsyncMock, return_value=""), \
         patch("backend.pipeline.compile.generate_caption",
               new_callable=AsyncMock, return_value=None), \
         patch("backend.pipeline.compile._get_children_with_vecs",
               new_callable=AsyncMock, return_value=[]), \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.fetch_cluster_clips = AsyncMock(return_value=fake_clips)
        mock_db.get_segment_for_cluster = AsyncMock(return_value=fake_segment)
        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-xyz")

        mock_db.set_compile_in_flight.assert_awaited_with("cluster-xyz", False)

        broadcast_calls = mock_events.broadcast.await_args_list
        event_types = [c.args[0]["type"] for c in broadcast_calls]
        assert "segment_published" in event_types, f"got {event_types}"

        pub_call = next(c for c in broadcast_calls if c.args[0]["type"] == "segment_published")
        assert pub_call.args[0]["segment_id"] == "seg-abc123"
        assert pub_call.args[0]["cluster_id"] == "cluster-xyz"

        # The caption-writer received a user message containing image content blocks.
        sent = captured["caption_user_msg"]
        assert sent is not None, "caption-writer never received a user message"
        assert sent["type"] == "user"
        content = sent["message"]["content"]
        assert isinstance(content, list)
        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 2, f"expected 2 image blocks, got {len(image_blocks)}"
        assert image_blocks[0]["source"]["media_type"] == "image/png"
        assert image_blocks[0]["source"]["type"] == "base64"


@pytest.mark.asyncio
async def test_compile_segment_partial_keyframe_failure():
    """ffmpeg fails on 1 of 3 clips → caption-writer still runs with N-1 frames."""
    fake_segment = {
        "id": "seg-partial",
        "cluster_id": "cluster-partial",
        "ordered_clip_ids": ["c1", "c3"],
        "caption": "Partial frames caption.",
        "location": "Pasadena, CA",
        "source_count": 2,
        "created_at": 1_000_000.0,
    }
    caption_json = '{"caption": "Partial frames caption.", "location": "Pasadena, CA"}'
    fake_query, captured = _make_query_mock(caption_json)

    fake_clips = [
        {"id": "c1", "path": "/tmp/c1.mp4", "lat": 34.1, "lng": -118.1, "ts": 1_700_000_000.0},
        {"id": "c2", "path": "/tmp/c2.mp4", "lat": 34.11, "lng": -118.11, "ts": 1_700_000_010.0},
        {"id": "c3", "path": "/tmp/c3.mp4", "lat": 34.12, "lng": -118.12, "ts": 1_700_000_020.0},
    ]
    # c2 dropped — ffmpeg failed
    partial_frames = [("c1", b"_png1"), ("c3", b"_png3")]

    with patch("backend.pipeline.compile.query", side_effect=fake_query), \
         patch("backend.pipeline.compile.extract_cluster_keyframes",
               new_callable=AsyncMock, return_value=partial_frames), \
         patch("backend.pipeline.compile.stitch_clips",
               new_callable=AsyncMock, return_value=""), \
         patch("backend.pipeline.compile.generate_caption",
               new_callable=AsyncMock, return_value=None), \
         patch("backend.pipeline.compile._get_children_with_vecs",
               new_callable=AsyncMock, return_value=[]), \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.fetch_cluster_clips = AsyncMock(return_value=fake_clips)
        mock_db.get_segment_for_cluster = AsyncMock(return_value=fake_segment)
        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-partial")

        sent = captured["caption_user_msg"]
        image_blocks = [b for b in sent["message"]["content"] if b.get("type") == "image"]
        assert len(image_blocks) == 2, "should have run with N-1 frames"

        broadcast_calls = mock_events.broadcast.await_args_list
        event_types = [c.args[0]["type"] for c in broadcast_calls]
        assert "segment_published" in event_types


@pytest.mark.asyncio
async def test_compile_segment_no_keyframes_falls_back():
    """When zero frames extract, caption-writer raises → fallback path runs."""
    fallback_id = "seg-fallback-novision"

    async def never_called_query(prompt, options):
        raise AssertionError("query() should not be called when no frames")
        yield  # pragma: no cover

    with patch("backend.pipeline.compile.query", side_effect=never_called_query), \
         patch("backend.pipeline.compile.extract_cluster_keyframes",
               new_callable=AsyncMock, return_value=[]), \
         patch("backend.pipeline.compile.stitch_clips",
               new_callable=AsyncMock, return_value=""), \
         patch("backend.pipeline.compile.generate_caption",
               new_callable=AsyncMock, return_value=None), \
         patch("backend.pipeline.compile._get_children_with_vecs",
               new_callable=AsyncMock, return_value=[]), \
         patch("backend.pipeline.compile._save_fallback_segment",
               new_callable=AsyncMock, return_value=fallback_id) as mock_fallback, \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.fetch_cluster_clips = AsyncMock(return_value=[])
        mock_db.get_segment_for_cluster = AsyncMock(return_value=None)
        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment("cluster-noframes")

        # _save_fallback_segment is called with (cluster_id, video_url) — the
        # parallel-track shape passes video_url even when stitch produced nothing.
        mock_fallback.assert_awaited_once()
        call_args = mock_fallback.await_args
        assert call_args.args[0] == "cluster-noframes"
        broadcast_calls = mock_events.broadcast.await_args_list
        pub_call = next(c for c in broadcast_calls if c.args[0]["type"] == "segment_published")
        assert pub_call.args[0]["segment_id"] == fallback_id


@pytest.mark.asyncio
async def test_track_c_fallback_does_not_overwrite_track_a_caption(tmp_path):
    """RUNTIME-CAP-01: when generate_caption returns None (Track C fallback),
    compile_segment must preserve Track A's vision-grounded caption on the row.
    """
    cluster_id = "cluster-trackc-fallback"
    track_a_caption = "VISION_CAPTION_FROM_TRACK_A"
    fake_segment = {
        "id": "seg-trackc-fallback",
        "cluster_id": cluster_id,
        "ordered_clip_ids": ["c1"],
        "caption": track_a_caption,
        "location": "Pasadena, CA",
        "source_count": 1,
        "video_url": None,
        "created_at": 1_000_000.0,
    }
    fake_clips = [
        {"id": "c1", "path": "/tmp/c1.mp4", "lat": 34.1, "lng": -118.1, "ts": 1_700_000_000.0},
    ]
    # stitch_clips needs to return a real existing file so video_url is set
    # and the re-insert branch runs.
    fake_stitch_path = tmp_path / "fake_stitch.mp4"
    fake_stitch_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    with patch("backend.pipeline.compile._run_agents",
               new_callable=AsyncMock, return_value=fake_segment["id"]) as mock_agents, \
         patch("backend.pipeline.compile.stitch_clips",
               new_callable=AsyncMock, return_value=str(fake_stitch_path)), \
         patch("backend.pipeline.compile.generate_caption",
               new_callable=AsyncMock, return_value=None), \
         patch("backend.pipeline.compile._get_children_with_vecs",
               new_callable=AsyncMock, return_value=[]), \
         patch("backend.pipeline.compile.db") as mock_db, \
         patch("backend.pipeline.compile.events") as mock_events:

        mock_db.fetch_cluster_clips = AsyncMock(return_value=fake_clips)
        mock_db.get_segment_for_cluster = AsyncMock(return_value=fake_segment)
        mock_db.insert_segment = AsyncMock(return_value=fake_segment["id"])
        mock_db.set_compile_in_flight = AsyncMock(return_value=True)
        mock_events.broadcast = AsyncMock()

        from backend.pipeline.compile import compile_segment
        await compile_segment(cluster_id)

        mock_agents.assert_awaited_once_with(cluster_id)
        # Track C returned None → caption_result is None → re-insert preserves seg.caption.
        # The re-insert call should have happened (video_url is set from stitch).
        assert mock_db.insert_segment.await_count >= 1, "expected re-insert to run"
        last_call = mock_db.insert_segment.await_args
        assert last_call.kwargs["caption"] == track_a_caption, (
            f"Track A caption was overwritten: got {last_call.kwargs['caption']!r}"
        )


@pytest.mark.asyncio
async def test_no_multi_angle_template_in_fallback_paths():
    """RUNTIME-CAP-01: _save_fallback_segment must NOT emit the forbidden
    cluster-framing template (substring check below catches it).
    """
    captured = {}
    fake_clips = [
        {"id": "c1", "path": "/tmp/c1.mp4", "lat": 34.1, "lng": -118.1, "ts": 1_700_000_000.0},
        {"id": "c2", "path": "/tmp/c2.mp4", "lat": 34.11, "lng": -118.11, "ts": 1_700_000_010.0},
    ]

    async def fake_insert_segment(**kwargs):
        captured.update(kwargs)
        return "seg-fallback-test"

    with patch("backend.pipeline.compile.db") as mock_db:
        mock_db.get_segment_for_cluster = AsyncMock(return_value=None)
        mock_db.fetch_cluster_clips = AsyncMock(return_value=fake_clips)
        mock_db.insert_segment = AsyncMock(side_effect=fake_insert_segment)

        from backend.pipeline.compile import _save_fallback_segment
        seg_id = await _save_fallback_segment("cluster-fallback-test")

        assert seg_id == "seg-fallback-test"
        caption = captured.get("caption", "")
        assert "multi-angle" not in caption.lower(), (
            f"forbidden template appeared in fallback caption: {caption!r}"
        )
        # Sanity: place + date framing instead of multi-angle.
        assert "Pasadena" in caption
        assert "contributor" in caption.lower()
