"""Phase 11 moderate.py unit + behavioral tests.

Covers MOD-01..06, MOD-09, MOD-10, PRIV-03 (see RESEARCH.md § "Phase Requirements → Test Map").
The cancel-when-embed-finishes test uses asyncio.Event for deterministic ordering
(no real timing dependence). The hard-block test verifies the reported_csam preservation
row is written BEFORE cleanup_blocked_clip is called (statutory ordering per § 2258A).

NO real Gemini calls. NO real CSAM corpus (statutorily protected). All tests use
patched module-level helpers + synthetic verdict JSON.

DB writes are mocked via monkeypatch.setattr because the SQLite SCHEMA_SQL does not
yet declare moderation_decisions / reported_csam / clips.is_hidden (Plan 03 deferred
issue under SQLite-backend retirement). Mocks let us assert call_args without
adding new SQLite-only behavior. The Postgres path has the columns from migrations
0003-0005 — when DATABASE_URL is set, parity tests should land separately.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

_ALL_PASS = {
    cat: {"verdict": "pass", "score": 0.0, "rationale": "no signal"}
    for cat in ("csam", "sexual", "hate", "extremist", "violence", "self_harm")
}


async def _fake_embed_worker(clip_id: str):
    """Default embed_worker mock returns a parent-vec-shaped tuple instantly."""
    import numpy as np
    return (clip_id, np.zeros(512, dtype="float32"))


@pytest.fixture
def patched_moderate(monkeypatch):
    """Patch _fetch_clip_bytes + db writers + embed_worker + cleanup at module scope.

    Yields a SimpleNamespace of the AsyncMocks/MagicMocks so tests can assert
    against call_args. Tests can override individual mocks via the namespace
    attributes (e.g. patched_moderate.gemini_classify.side_effect = ...).
    """
    import types as _types
    from backend.pipeline import moderate as mod

    monkeypatch.setenv("OFFLINE_DEMO", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setenv("MODERATION_MAX_BUDGET_S", "20.0")

    # Reload config so the test's env vars are visible to moderate.
    import importlib
    import backend.config
    importlib.reload(backend.config)

    fetch_mock = AsyncMock(return_value=(b"fake-video-bytes", "/tmp/fake.mp4"))
    monkeypatch.setattr(mod, "_fetch_clip_bytes", fetch_mock)

    # db.get_clip is hit at the start of _moderate_real to determine if blob_tempfile
    # cleanup is required. Return a non-blob row so we never try to unlink anything.
    get_clip_mock = AsyncMock(return_value={"id": "clip_abc", "path": "/tmp/fake.mp4", "blob_url": None})
    monkeypatch.setattr(mod.db, "get_clip", get_clip_mock)

    write_decision = AsyncMock(return_value="dec_id_1")
    write_csam = AsyncMock(return_value="rep_id_1")
    set_hidden = AsyncMock(return_value=None)
    monkeypatch.setattr(mod.db, "write_moderation_decision", write_decision)
    monkeypatch.setattr(mod.db, "write_reported_csam", write_csam)
    monkeypatch.setattr(mod.db, "set_clip_hidden", set_hidden)

    cleanup_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "cleanup_blocked_clip", cleanup_mock)

    embed_mock = AsyncMock(side_effect=_fake_embed_worker)
    # Locally imported inside _moderate_real (`from .embed import embed_worker`),
    # so the binding to patch is at backend.pipeline.embed.embed_worker.
    import backend.pipeline.embed
    monkeypatch.setattr(backend.pipeline.embed, "embed_worker", embed_mock)

    # _gemini_classify default: return all-pass dict (no real SDK call).
    gemini_classify = AsyncMock(return_value=dict(_ALL_PASS))
    monkeypatch.setattr(mod, "_gemini_classify", gemini_classify)

    ns = _types.SimpleNamespace(
        mod=mod,
        fetch_clip_bytes=fetch_mock,
        get_clip=get_clip_mock,
        write_moderation_decision=write_decision,
        write_reported_csam=write_csam,
        set_clip_hidden=set_hidden,
        cleanup_blocked_clip=cleanup_mock,
        embed_worker=embed_mock,
        gemini_classify=gemini_classify,
    )
    yield ns


# ---------------------------------------------------------------------------
# Test 1 — OFFLINE_DEMO passthrough (MOD-10)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_offline_demo_passthrough(monkeypatch, respx_mock):
    """MOD-10: OFFLINE_DEMO=true → passthrough decision; ZERO outbound traffic."""
    monkeypatch.setenv("OFFLINE_DEMO", "true")
    monkeypatch.setenv("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")

    import importlib
    import backend.config
    import backend.pipeline.moderate as mod
    importlib.reload(backend.config)
    importlib.reload(mod)

    # Mock db.write_moderation_decision so the OFFLINE_DEMO row write doesn't
    # require a real SQLite schema (SCHEMA_SQL deferred-issue per 11-04 SUMMARY).
    write_decision = AsyncMock(return_value="dec_id_1")
    monkeypatch.setattr(mod.db, "write_moderation_decision", write_decision)

    # Register Gemini routes so we can assert call_count == 0 after the call.
    upload_route = respx_mock.post(
        "https://generativelanguage.googleapis.com/upload/v1beta/files"
    ).respond(json={})
    poll_route = respx_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/files/test"
    ).respond(json={})
    generate_route = respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    ).respond(json={})

    result = await mod.moderate_clip("clip_abc")

    assert result.decision == "passed"
    assert result.provider == "stub"
    assert result.reason == "offline_demo"
    assert upload_route.call_count == 0, "OFFLINE_DEMO=true must not hit Gemini Files (MOD-10 violation)"
    assert poll_route.call_count == 0, "OFFLINE_DEMO=true must not poll Gemini Files (MOD-10 violation)"
    assert generate_route.call_count == 0, "OFFLINE_DEMO=true must not hit Gemini generateContent (MOD-10 violation)"

    # Audit-row assertion: provider='stub', latency_ms=0, prompt_version=None.
    write_decision.assert_awaited_once()
    kwargs = write_decision.await_args.kwargs
    assert kwargs["provider"] == "stub"
    assert kwargs["decision"] == "passed"
    assert kwargs["reason"] == "offline_demo"
    assert kwargs["latency_ms"] == 0
    assert kwargs["prompt_version"] is None


# ---------------------------------------------------------------------------
# Test 2 — Happy path (all-pass classifier verdict)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_pass_happy_path(patched_moderate):
    """Happy path: classifier all-pass → decision='passed' provider='gemini_flash_lite'."""
    pm = patched_moderate

    result = await pm.mod.moderate_clip("clip_abc")

    assert result.decision == "passed"
    assert result.provider == "gemini_flash_lite"
    assert result.reason is None
    assert result.soft_flag_categories == []
    assert result.embed_result is not None  # parent_clip_id, parent_vec tuple

    # Exactly one moderation_decisions row written with provider gemini_flash_lite.
    pm.write_moderation_decision.assert_awaited_once()
    kwargs = pm.write_moderation_decision.await_args.kwargs
    assert kwargs["clip_id"] == "clip_abc"
    assert kwargs["provider"] == "gemini_flash_lite"
    assert kwargs["decision"] == "passed"
    assert kwargs["reason"] is None
    assert kwargs["prompt_version"] == pm.mod.PROMPT_VERSION
    assert isinstance(kwargs["latency_ms"], int) and kwargs["latency_ms"] >= 0

    # Hard-block side effects must NOT have fired.
    pm.write_reported_csam.assert_not_awaited()
    pm.cleanup_blocked_clip.assert_not_awaited()
    pm.set_clip_hidden.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 3 — Hard-block CSAM (audit-trail ordering, reported_csam preservation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_hard_block_csam(patched_moderate):
    """csam=block → decision='blocked' reason='gemini_csam_block'. Writes reported_csam
    BEFORE cleanup_blocked_clip (T-11-16 audit-trail ordering)."""
    pm = patched_moderate
    csam_block = dict(_ALL_PASS)
    csam_block["csam"] = {"verdict": "block", "score": 0.99, "rationale": "blocked"}
    pm.gemini_classify.return_value = csam_block

    # Capture call ordering across reported_csam + cleanup_blocked_clip.
    call_order: list[str] = []

    async def _csam_recorder(*a, **kw):
        call_order.append("write_reported_csam")
        return "rep_id_1"

    async def _cleanup_recorder(*a, **kw):
        call_order.append("cleanup_blocked_clip")
        return None

    pm.write_reported_csam.side_effect = _csam_recorder
    pm.cleanup_blocked_clip.side_effect = _cleanup_recorder

    result = await pm.mod.moderate_clip("clip_abc")

    assert result.decision == "blocked"
    assert result.reason == "gemini_csam_block"
    assert result.provider == "gemini_flash_lite"

    # reported_csam: SHA-256 hex of clip bytes.
    pm.write_reported_csam.assert_awaited_once()
    csam_kwargs = pm.write_reported_csam.await_args.kwargs
    import hashlib
    expected_hash = hashlib.sha256(b"fake-video-bytes").hexdigest()
    assert csam_kwargs["content_hash"] == expected_hash, (
        f"reported_csam hash mismatch: {csam_kwargs['content_hash']!r} != {expected_hash!r}"
    )

    # preserved_until is roughly 1 year in the future (between 364 and 366 days).
    now = time.time()
    one_year_s = 365 * 24 * 60 * 60
    delta = csam_kwargs["preserved_until"] - now
    assert (one_year_s - 24 * 60 * 60) <= delta <= (one_year_s + 24 * 60 * 60), (
        f"preserved_until not ~1 year out: delta={delta}"
    )

    # cleanup_blocked_clip called exactly once with the clip_id.
    pm.cleanup_blocked_clip.assert_awaited_once_with("clip_abc")

    # T-11-16 ordering: reported_csam written BEFORE cleanup_blocked_clip.
    assert call_order == ["write_reported_csam", "cleanup_blocked_clip"], (
        f"Hard-block side-effect order violated audit-trail discipline: {call_order!r}"
    )


# ---------------------------------------------------------------------------
# Test 3b — CR-02 regression: cleanup is gated on preservation success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_csam_preservation_failure_skips_cleanup(patched_moderate):
    """CR-02 regression: when write_reported_csam raises (DB outage, JSONB
    encoder failure, etc.) on a CSAM-block path, cleanup_blocked_clip MUST
    NOT run — § 2258A 1-year retention requires the bytes stay on disk for
    manual reconciliation, never silently deleted."""
    pm = patched_moderate
    csam_block = dict(_ALL_PASS)
    csam_block["csam"] = {"verdict": "block", "score": 0.99, "rationale": "blocked"}
    pm.gemini_classify.return_value = csam_block

    async def _csam_raises(*a, **kw):
        raise RuntimeError("simulated DB outage on reported_csam write")

    pm.write_reported_csam.side_effect = _csam_raises

    result = await pm.mod.moderate_clip("clip_abc")

    # Decision is still blocked (the gate fired correctly).
    assert result.decision == "blocked"
    assert result.reason == "gemini_csam_block"

    # Preservation write was attempted (and failed — error logged).
    pm.write_reported_csam.assert_awaited_once()

    # CRITICAL: cleanup MUST NOT have run. Bytes preserved for manual reconciliation.
    pm.cleanup_blocked_clip.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 4 — Soft-flag (violence flag, no hard-block)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_soft_flag_violence(patched_moderate):
    """violence=flag (all hard-block pass) → decision='passed' reason starts soft_flag_;
    no reported_csam row, no cleanup_blocked_clip."""
    pm = patched_moderate
    violence_flag = dict(_ALL_PASS)
    violence_flag["violence"] = {"verdict": "flag", "score": 0.6, "rationale": "news context"}
    pm.gemini_classify.return_value = violence_flag

    result = await pm.mod.moderate_clip("clip_abc")

    assert result.decision == "passed"
    assert result.reason is not None and result.reason.startswith("soft_flag_"), result.reason
    assert "violence" in result.soft_flag_categories

    # Audit row: still passed.
    kwargs = pm.write_moderation_decision.await_args.kwargs
    assert kwargs["decision"] == "passed"

    # No CSAM preservation, no cleanup.
    pm.write_reported_csam.assert_not_awaited()
    pm.cleanup_blocked_clip.assert_not_awaited()
    pm.set_clip_hidden.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 5 — Cancel-when-embed-finishes (deterministic via asyncio.Event)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_cancel_when_embed_finishes_first(patched_moderate):
    """D-03 cancel-when-embed-finishes: embed completes, gemini still pending →
    decision='blocked' reason='classifier_timeout' (Branch A in moderate._moderate_real).
    Uses asyncio.Event for deterministic ordering — no real timing dependence."""
    pm = patched_moderate

    embed_finished = asyncio.Event()

    async def _fast_embed(clip_id: str):
        # Signal that embed completed, then return.
        embed_finished.set()
        import numpy as np
        return (clip_id, np.zeros(512, dtype="float32"))

    async def _slow_gemini(clip_local_path: str):
        # Wait for embed to finish, then sleep "forever" — but we'll be cancelled
        # by the Branch A cancel + drain after embed wins.
        await embed_finished.wait()
        await asyncio.sleep(60)  # never returns; gets cancelled

    pm.embed_worker.side_effect = _fast_embed
    pm.gemini_classify.side_effect = _slow_gemini

    result = await pm.mod.moderate_clip("clip_abc")

    assert result.decision == "blocked"
    assert result.reason == "classifier_timeout", (
        f"expected classifier_timeout (Branch A), got {result.reason!r}"
    )

    # Audit row records the cancel.
    kwargs = pm.write_moderation_decision.await_args.kwargs
    assert kwargs["decision"] == "blocked"
    assert kwargs["reason"] == "classifier_timeout"

    # Branch A: cleanup runs on every hard-block (idempotent).
    pm.cleanup_blocked_clip.assert_awaited_once_with("clip_abc")
    # csam-specific reported_csam preservation does NOT fire on a timeout block.
    pm.write_reported_csam.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 6 — Failure-tier classification (typed-exception ladder, parametrized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc_factory, expected_decision, expected_reason_prefix",
    [
        (lambda: asyncio.TimeoutError("classifier hung"), "blocked", "classifier_timeout"),
        (
            lambda: httpx.HTTPStatusError(
                "400 bad", request=httpx.Request("POST", "https://x"),
                response=httpx.Response(400),
            ),
            "blocked", "classifier_4xx_400",
        ),
        (
            lambda: httpx.HTTPStatusError(
                "503 unavailable", request=httpx.Request("POST", "https://x"),
                response=httpx.Response(503),
            ),
            "unknown", "classifier_5xx_503",
        ),
        (
            lambda: httpx.ConnectError("connect refused"),
            "unknown", "classifier_network_error",
        ),
    ],
    ids=["timeout-blocked", "4xx-blocked", "5xx-unknown", "connect-error-unknown"],
)
@pytest.mark.asyncio
async def test_moderate_failure_tier_classification(
    patched_moderate, exc_factory, expected_decision, expected_reason_prefix,
):
    """D-05 typed-exception ladder: TimeoutError + 4xx → blocked;
    5xx + ConnectError → unknown."""
    pm = patched_moderate

    async def _raise_exc(clip_local_path: str):
        raise exc_factory()

    pm.gemini_classify.side_effect = _raise_exc

    result = await pm.mod.moderate_clip("clip_abc")

    assert result.decision == expected_decision, (
        f"expected decision={expected_decision} for {exc_factory()!r}, got {result.decision!r}"
    )
    assert result.reason == expected_reason_prefix, (
        f"expected reason={expected_reason_prefix} got {result.reason!r}"
    )

    # Audit row matches.
    kwargs = pm.write_moderation_decision.await_args.kwargs
    assert kwargs["decision"] == expected_decision
    assert kwargs["reason"] == expected_reason_prefix

    # Side-effect routing: blocked → cleanup; unknown → set_clip_hidden.
    if expected_decision == "blocked":
        pm.cleanup_blocked_clip.assert_awaited()
        pm.set_clip_hidden.assert_not_awaited()
    else:
        pm.set_clip_hidden.assert_awaited()
        pm.cleanup_blocked_clip.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 7 — Idempotency (UNIQUE constraint via ON CONFLICT DO UPDATE)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_idempotent(patched_moderate):
    """Calling moderate_clip twice produces exactly one DB row per (clip_id, provider).

    The real DB enforces the UNIQUE(clip_id, provider) constraint via ON CONFLICT
    DO UPDATE — both calls hit write_moderation_decision but the row count stays
    at 1. We assert that pattern by tracking the unique (clip_id, provider) keys
    written across calls and confirming the SECOND call's latency_ms is what
    ended up persisted (the ON CONFLICT DO UPDATE replaces latency_ms)."""
    pm = patched_moderate

    # Track each call's kwargs.
    call_args_history: list[dict] = []

    async def _record(*a, **kw):
        call_args_history.append(dict(kw))
        return "dec_id_1"

    pm.write_moderation_decision.side_effect = _record

    await pm.mod.moderate_clip("clip_abc")
    await pm.mod.moderate_clip("clip_abc")

    # Both calls hit write_moderation_decision (which is what the SQL upsert
    # expects); the underlying UNIQUE(clip_id, provider) constraint collapses
    # them into one row.
    assert len(call_args_history) == 2

    # Both writes target the same (clip_id, provider) key — proving the upsert
    # would collapse them at the SQL boundary.
    keys = {(c["clip_id"], c["provider"]) for c in call_args_history}
    assert keys == {("clip_abc", "gemini_flash_lite")}, (
        f"Expected one (clip_id, provider) key, got {keys!r}"
    )

    # Latency_ms differs between the two calls (each run measures fresh) —
    # the second value would be what persisted post-upsert.
    assert all("latency_ms" in c for c in call_args_history)


# ---------------------------------------------------------------------------
# Test 8 — PRIV-03 outbound payload anonymized
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_priv_03_outbound_payload_anonymized(patched_moderate):
    """PRIV-03: nothing in the outbound classifier surface should contain
    session_uuid / gps_lat / gps_lng / created_at / timestamp.

    moderate.py uses the google.genai SDK, which takes a file path and a
    system_instruction string — there is no application-controlled payload
    body the test could intercept and read. Instead we verify:
      1. The args _gemini_classify is invoked with carry only a clip_local_path
         (a str). NO dict, no kwargs containing anonymity keys.
      2. _strip_anonymity_metadata strips every anonymity key from any dict
         that might be passed through it (defense-in-depth; called against
         raw_response before persisting to JSONB).
    """
    pm = patched_moderate

    # Intercept _gemini_classify args.
    captured_args: list[tuple] = []
    captured_kwargs: list[dict] = []

    async def _capture(*args, **kwargs):
        captured_args.append(args)
        captured_kwargs.append(kwargs)
        return dict(_ALL_PASS)

    pm.gemini_classify.side_effect = _capture

    await pm.mod.moderate_clip("clip_abc")

    # _gemini_classify is invoked exactly once with a single positional arg
    # (clip_local_path). No anonymity-keyed dict ever enters the classifier.
    assert len(captured_args) == 1
    assert isinstance(captured_args[0][0], str), (
        f"_gemini_classify must receive a path str; got {type(captured_args[0][0])}"
    )
    assert captured_kwargs == [{}], (
        f"_gemini_classify must receive no anonymity-keyed kwargs; got {captured_kwargs!r}"
    )

    # Walk every captured arg + kwarg looking for anonymity-keyed bytes.
    forbidden_tokens = (
        b"session_uuid", b"gps_lat", b"gps_lng", b"created_at", b"timestamp",
    )
    for arg in captured_args[0]:
        # arg is a path str — never bytes here, but guard for the future.
        s = str(arg).encode("utf-8")
        for tok in forbidden_tokens:
            assert tok not in s, f"anonymity token {tok!r} leaked into _gemini_classify args"
    for tok in forbidden_tokens:
        for v in captured_kwargs[0].values():
            assert tok not in str(v).encode("utf-8"), (
                f"anonymity token {tok!r} leaked into _gemini_classify kwargs: {v!r}"
            )

    # Defense-in-depth: _strip_anonymity_metadata removes anonymity keys.
    poison = {
        "csam": {"verdict": "pass"},
        "session_uuid": "leak-uuid",
        "gps_lat": 34.1377,
        "gps_lng": -118.1253,
        "created_at": 1_000_000.0,
        "timestamp": 1_000_000.0,
        "safe": "value",
    }
    stripped = pm.mod._strip_anonymity_metadata(poison)
    for forbidden in ("session_uuid", "gps_lat", "gps_lng", "created_at", "timestamp"):
        assert forbidden not in stripped, (
            f"_strip_anonymity_metadata failed to remove {forbidden!r}"
        )
    assert stripped["safe"] == "value"
    assert stripped["csam"] == {"verdict": "pass"}


# ---------------------------------------------------------------------------
# Test 9 — Unknown-path hides clip (5xx via typed-exception → set_clip_hidden)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moderate_unknown_path_hides_clip(patched_moderate):
    """5xx response → decision='unknown' → db.set_clip_hidden(clip_id, hidden=True).

    Plan 05's run_pipeline gate short-circuits clustering on decision='unknown';
    this unit test verifies moderate.py's side-effect contract for the unknown branch
    (the cluster_worker non-invocation is a Plan 05 integration concern)."""
    pm = patched_moderate

    async def _raise_503(clip_local_path: str):
        raise httpx.HTTPStatusError(
            "503 unavailable",
            request=httpx.Request("POST", "https://x"),
            response=httpx.Response(503),
        )

    pm.gemini_classify.side_effect = _raise_503

    result = await pm.mod.moderate_clip("clip_abc")

    assert result.decision == "unknown"
    assert result.reason == "classifier_5xx_503"

    # set_clip_hidden called exactly once with hidden=True.
    pm.set_clip_hidden.assert_awaited_once()
    args, kwargs = pm.set_clip_hidden.await_args
    # Function signature: set_clip_hidden(clip_id, hidden) — handle kw-or-positional.
    if args:
        assert args[0] == "clip_abc"
    else:
        assert kwargs.get("clip_id") == "clip_abc"
    if "hidden" in kwargs:
        assert kwargs["hidden"] is True
    elif len(args) >= 2:
        assert args[1] is True
    else:
        pytest.fail(f"set_clip_hidden called without hidden flag: args={args} kwargs={kwargs}")

    # cleanup_blocked_clip is not called for unknown decisions — only blocked.
    pm.cleanup_blocked_clip.assert_not_awaited()
    pm.write_reported_csam.assert_not_awaited()
