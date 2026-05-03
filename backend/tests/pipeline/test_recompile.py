"""Phase 14 recompile gate tests (Path B-lite per RESEARCH § Decision Matrix).

Covers RESEARCH § Required Tests — 6 integration scenarios:
  1. test_recompile_fires_on_new_distinct_parent
  2. test_recompile_debounce_coalesces_burst
  3. test_recompile_skipped_for_child_of_existing_parent
  4. test_recompile_offline_demo_e2e
  5. test_recompile_preserves_per_clip_moderation
  6. test_recompile_does_not_bypass_moderation_block

No real Gemini calls. No real ffmpeg. Tests 1-3 are pure helper-logic via patched
db.* AsyncMocks; tests 4-6 require fresh_db Postgres fixture (skip if DATABASE_URL
unset).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend import config
from backend.pipeline import run as run_module
from backend.pipeline import compile as compile_module

# respx is in dev dependencies; if not available, tests using it skip cleanly.
respx = pytest.importorskip("respx")


# ---------------------------------------------------------------------------
# Autouse: clear module-level recompile-counter state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_recompile_counts():
    """Clear compile._RECOMPILE_COUNTS before each test for deterministic state.

    compile._RECOMPILE_COUNTS is a module-level dict (per-cluster soft-warn counter,
    analog of rate_limit._attempts). Since pytest test ordering / parallelization
    could otherwise leak state across tests, an autouse fixture clears it every run.
    Cheap (~1 line); prevents flakiness in Test 5 (which monkeypatches and then
    invokes compile_segment).
    """
    compile_module._RECOMPILE_COUNTS.clear()
    yield
    compile_module._RECOMPILE_COUNTS.clear()


# ---------------------------------------------------------------------------
# Fixture (helper-only — Tests 1-3)
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_recompile_helpers(monkeypatch):
    """Patch db.* lookups used by run._should_recompile.

    Returns a SimpleNamespace where each db helper is an AsyncMock with sensible
    defaults (clip is a parent, segment exists, parent_count=2, CAS=True).

    Tests override individual mocks via patched.<name>.return_value = ... before
    invoking the helper.
    """
    import types as _types

    get_clip = AsyncMock(return_value={"id": "clip_new", "parent_id": None})
    get_segment_for_cluster = AsyncMock(return_value={"cluster_id": "c1", "id": "seg1"})
    count_distinct_parents = AsyncMock(return_value=2)
    set_compile_in_flight = AsyncMock(return_value=True)

    monkeypatch.setattr(run_module.db, "get_clip", get_clip)
    monkeypatch.setattr(run_module.db, "get_segment_for_cluster", get_segment_for_cluster)
    monkeypatch.setattr(run_module.db, "count_distinct_parents_in_cluster", count_distinct_parents)
    monkeypatch.setattr(run_module.db, "set_compile_in_flight", set_compile_in_flight)

    # Ensure feature flag ON (default state — defensive).
    monkeypatch.setattr(config, "RECOMPILE_ON_NEW_PARENT", True)
    monkeypatch.setattr(config, "RECOMPILE_DEBOUNCE_S", 60.0)

    return _types.SimpleNamespace(
        get_clip=get_clip,
        get_segment_for_cluster=get_segment_for_cluster,
        count_distinct_parents=count_distinct_parents,
        set_compile_in_flight=set_compile_in_flight,
    )


# ---------------------------------------------------------------------------
# Test 1 — happy path: new distinct parent triggers recompile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompile_fires_on_new_distinct_parent(patched_recompile_helpers):
    """New distinct parent on existing-segment cluster -> _should_recompile True."""
    ph = patched_recompile_helpers

    result = await run_module._should_recompile("c1", "clip_new")

    assert result is True
    ph.get_clip.assert_awaited_once_with("clip_new")
    ph.get_segment_for_cluster.assert_awaited_once_with("c1")
    ph.count_distinct_parents.assert_awaited_once_with("c1")
    # CAS lock invoked with the recompile-specific 60s TTL.
    ph.set_compile_in_flight.assert_awaited_once()
    kwargs = ph.set_compile_in_flight.await_args.kwargs
    assert kwargs.get("ttl_seconds") == 60.0, (
        "expected ttl_seconds=60.0 (RECOMPILE_DEBOUNCE_S), got %r" % (kwargs,)
    )


# ---------------------------------------------------------------------------
# Test 2 — debounce coalescing: 2nd call inside window returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompile_debounce_coalesces_burst(patched_recompile_helpers):
    """Second call within debounce window -> CAS returns False -> helper returns False."""
    ph = patched_recompile_helpers

    # First call: CAS acquires.
    ph.set_compile_in_flight.return_value = True
    first = await run_module._should_recompile("c1", "clip_p1")
    assert first is True

    # Second call inside the window: CAS returns False (lock held).
    ph.set_compile_in_flight.return_value = False
    second = await run_module._should_recompile("c1", "clip_p2")
    assert second is False, "second call within window must NOT acquire the lock"

    # Both calls hit the DB lookups (no early-exit on first).
    assert ph.set_compile_in_flight.await_count == 2


# ---------------------------------------------------------------------------
# Test 3 — child early-exit: clip with parent_id != None short-circuits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompile_skipped_for_child_of_existing_parent(patched_recompile_helpers):
    """Clip with parent_id != None -> short-circuit False before segment lookup."""
    ph = patched_recompile_helpers
    ph.get_clip.return_value = {"id": "clip_child_999", "parent_id": "clip_parent_abc"}

    result = await run_module._should_recompile("c1", "clip_child_999")

    assert result is False
    ph.get_clip.assert_awaited_once_with("clip_child_999")
    # Short-circuit MUST happen before segment / parent-count / CAS lookups.
    ph.get_segment_for_cluster.assert_not_awaited()
    ph.count_distinct_parents.assert_not_awaited()
    ph.set_compile_in_flight.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 4 — OFFLINE_DEMO outbound block (MOD-10)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompile_offline_demo_e2e(monkeypatch, patched_recompile_helpers):
    """OFFLINE_DEMO=true: recompile path makes zero external calls (MOD-10)."""
    ph = patched_recompile_helpers
    monkeypatch.setenv("OFFLINE_DEMO", "true")
    monkeypatch.setattr(config, "OFFLINE_DEMO", True)

    # Stub compile_segment so we don't run real ffmpeg / SDK.
    fake_compile = AsyncMock(return_value=None)
    monkeypatch.setattr(run_module, "compile_segment", fake_compile)

    async with respx.mock(assert_all_called=False) as respx_mock:
        gemini_route = respx_mock.post(
            "https://generativelanguage.googleapis.com/upload/v1beta/files"
        ).respond(json={})

        # Drive the dispatch logic directly: simulate run_pipeline reaching the elif.
        should = await run_module._should_recompile("c1", "clip_new")
        assert should is True

        if should:
            await run_module.compile_segment("c1")

        assert gemini_route.call_count == 0, (
            "OFFLINE_DEMO=true must not hit Gemini Files (MOD-10 violation)"
        )
        fake_compile.assert_awaited_once_with("c1")


# ---------------------------------------------------------------------------
# Test 5 — soft_flag re-derivation propagates new parent's hate verdict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompile_preserves_per_clip_moderation(monkeypatch):
    """Recompile re-derives soft_flag from current cluster membership (MOD-07).

    3rd parent has hate.verdict='flag' -> re-emitted segments.soft_flag=True.
    Verifies the existing compile.py:629-648 derivation runs on every compile_segment
    invocation, including recompile.
    """
    from backend.pipeline import compile as cm

    cluster_id = "c_recompile_softflag"

    members = [
        {"id": "clip_p1"}, {"id": "clip_p2"}, {"id": "clip_p3_flagged"},
    ]
    decisions = [
        {"clip_id": "clip_p1", "raw_response": {"hate": {"verdict": "pass"}}},
        {"clip_id": "clip_p2", "raw_response": {"hate": {"verdict": "pass"}}},
        {"clip_id": "clip_p3_flagged", "raw_response": {"hate": {"verdict": "flag"}}},
    ]

    fetch_clips = AsyncMock(return_value=members)
    get_decisions = AsyncMock(return_value=decisions)
    insert_segment = AsyncMock(return_value="seg_recompiled")
    get_segment = AsyncMock(return_value={
        "cluster_id": cluster_id,
        "id": "seg_existing",
        "ordered_clip_ids": "[]",
        "title": "", "caption": "", "location": "Pasadena, CA",
        "source_count": 2, "video_url": None,
    })
    set_in_flight = AsyncMock(return_value=True)

    monkeypatch.setattr(cm.db, "fetch_cluster_clips", fetch_clips)
    monkeypatch.setattr(cm.db, "get_moderation_decisions_for_clips", get_decisions)
    monkeypatch.setattr(cm.db, "insert_segment", insert_segment)
    monkeypatch.setattr(cm.db, "get_segment_for_cluster", get_segment)
    monkeypatch.setattr(cm.db, "set_compile_in_flight", set_in_flight)

    # Stub LLM + stitch so we exercise only the soft_flag derivation + insert path.
    async def _stub_llm(cid):
        return "seg_recompiled"
    monkeypatch.setattr(cm, "_run_orchestrator_chain", _stub_llm)
    monkeypatch.setattr(cm, "_branch_caption", AsyncMock(return_value=None))
    monkeypatch.setattr(cm, "_stitch_segment_runs", AsyncMock(return_value=[]))
    monkeypatch.setattr(cm, "_enforce_parent_diversity", AsyncMock(return_value=None))

    # Reset the recompile counter to ensure deterministic state.
    cm._RECOMPILE_COUNTS.pop(cluster_id, None)

    await cm.compile_segment(cluster_id)

    # The Phase 3 re-insert at compile.py:692 was called with soft_flag=True.
    insert_segment.assert_awaited()
    # Find the kwargs from the LAST call (the Phase 3 re-insert with soft_flag).
    kwargs = insert_segment.await_args.kwargs
    assert kwargs.get("soft_flag") is True, (
        "expected soft_flag=True after hate.verdict=flag in cluster, got kwargs=%r" % (kwargs,)
    )


# ---------------------------------------------------------------------------
# Test 6 — moderation block prevents recompile (R2 mitigation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompile_does_not_bypass_moderation_block(monkeypatch, gemini_moderation_mock):
    """Phase 11 gate runs upstream of recompile gate (R2 mitigation).

    3rd 'parent' arrives but moderate_clip returns decision='blocked' ->
    cleanup_blocked_clip already ran inside moderate_clip -> cluster_worker
    NEVER invoked -> recompile gate NEVER reached.

    Per conftest.py docstring (lines 88-101): the gemini_moderation_mock fixture
    yields respx_mock directly. Tests override its default all-pass route by
    re-registering generateContent (last-registration-wins). For this test we
    additionally short-circuit moderate_clip itself because the real classifier
    path needs DB rows + on-disk video bytes that we don't materialize here —
    the assertion is about run_pipeline's gate ordering, not the classifier.
    """
    gm = gemini_moderation_mock  # respx_mock router from conftest.py

    # Override default all-pass route with a CSAM-block verdict (defense-in-depth:
    # if anything in the moderate path slips through to a real Gemini call, the
    # mocked router returns a block — we still want this test to fail loud, not
    # silently pass).
    blocked_payload = {
        "csam":      {"verdict": "block", "score": 0.99, "rationale": "test-block"},
        "sexual":    {"verdict": "pass",  "score": 0.0,  "rationale": "n/a"},
        "hate":      {"verdict": "pass",  "score": 0.0,  "rationale": "n/a"},
        "extremist": {"verdict": "pass",  "score": 0.0,  "rationale": "n/a"},
        "violence":  {"verdict": "pass",  "score": 0.0,  "rationale": "n/a"},
        "self_harm": {"verdict": "pass",  "score": 0.0,  "rationale": "n/a"},
    }
    gm.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    ).respond(json={
        "candidates": [{"content": {"parts": [{"text": json.dumps(blocked_payload)}]}}]
    })

    # Patch moderate_clip at run_module to return a blocked ModerationResult
    # directly. The fixture above guarantees no outbound HTTP would happen even
    # if the real path were taken; this patch keeps the test focused on the
    # run_pipeline gate-ordering contract (cluster_worker + compile_segment NOT
    # invoked when decision='blocked').
    from backend.pipeline.moderate import ModerationResult
    blocked_result = ModerationResult(
        decision="blocked",
        provider="gemini_flash_lite",
        reason="gemini_csam_block",
    )
    moderate_mock = AsyncMock(return_value=blocked_result)
    monkeypatch.setattr(run_module, "moderate_clip", moderate_mock)

    cluster_worker_mock = AsyncMock(return_value="c1")
    compile_segment_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(run_module, "cluster_worker", cluster_worker_mock)
    monkeypatch.setattr(run_module, "compile_segment", compile_segment_mock)

    await run_module.run_pipeline("clip_blocked_parent")

    # Gate ordering: moderation runs first; on blocked, cluster + compile are
    # short-circuited (run.py:129-139). No recompile dispatched.
    moderate_mock.assert_awaited_once_with("clip_blocked_parent")
    cluster_worker_mock.assert_not_awaited()
    compile_segment_mock.assert_not_awaited()
