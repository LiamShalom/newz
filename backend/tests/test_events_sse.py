"""
Tests for backend/events.py — subscribe/unsubscribe/broadcast lifecycle.
"""
import asyncio

import pytest

from backend import events


@pytest.fixture(autouse=True)
def clear_subscribers():
    """Isolate tests by clearing _subscribers before each test."""
    events._subscribers.clear()
    yield
    events._subscribers.clear()


@pytest.mark.asyncio
async def test_subscribe_returns_queue_and_adds_to_subscribers():
    """subscribe() returns a Queue and adds it to _subscribers."""
    assert len(events._subscribers) == 0
    q = await events.subscribe()
    assert isinstance(q, asyncio.Queue)
    assert q in events._subscribers
    assert len(events._subscribers) == 1


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_queues():
    """broadcast() delivers event to every subscribed queue."""
    q1 = await events.subscribe()
    q2 = await events.subscribe()

    event = {"type": "test_event", "data": "hello"}
    await events.broadcast(event)

    assert q1.qsize() == 1
    assert q2.qsize() == 1
    assert q1.get_nowait() == event
    assert q2.get_nowait() == event


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue_and_broadcast_does_not_raise():
    """unsubscribe() removes queue; subsequent broadcast doesn't raise."""
    q = await events.subscribe()
    assert q in events._subscribers

    await events.unsubscribe(q)
    assert q not in events._subscribers

    # broadcast to empty list must not raise
    await events.broadcast({"type": "after_unsub"})
    assert q.qsize() == 0  # nothing delivered to removed queue
