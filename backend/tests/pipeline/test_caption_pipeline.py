"""Quick task 260501-bet — caption_pipeline two-stage flow tests.

Covers:
  1. extract_evidence_for_parent returns the EvidenceJSON shape on success.
  2. extract_evidence_for_parent returns None when GEMINI_API_KEY is empty.
  3. synthesize_intent parses a Claude IntentJSON response and derives
     title + caption that meet the AP-wire shape constraints.
  4. synthesize_intent returns None on unparseable response.
  5. run_evidence_to_intent_pipeline skips parents whose evidence extraction
     failed (None) and synthesizes from the surviving evidence.
  6. run_evidence_to_intent_pipeline returns None when ALL parents fail.
  7. EVIDENCE_SYSTEM_PROMPT contains the anonymity guard verbatim — guards
     against accidental prompt regression.

NO real Gemini calls. NO real claude_agent_sdk calls. Per-test monkeypatch of:
  - google.genai.Client (Test 1) — stub a fake client whose chained call
    surface (.files.upload, .files.get, .files.delete, .models.generate_content)
    yields synthetic responses.
  - claude_agent_sdk.query (Tests 3-4) — replace with an async-generator
    factory that yields a single ResultMessage carrying canned text.
  - extract_evidence_for_parent (Tests 5-6) — replace at module scope so
    the orchestrator runs against deterministic per-parent outputs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend import config
from backend.pipeline import caption_pipeline as cap


# ---------------------------------------------------------------------------
# Shared synthetic payloads
# ---------------------------------------------------------------------------

_VALID_EVIDENCE: dict = {
    "signs": [
        {"text": "STIPEND NOW", "context": "held by 4 people in front row"},
        {"text": "PAY OUR GRADS", "context": "banner across gate"},
    ],
    "audio_transcript": "What do we want? Stipend! When do we want it? Now!",
    "visual_cues": [
        "approximately 30 people",
        "Caltech south gate visible",
        "early evening lighting",
    ],
    "affiliations": [
        "Caltech graduate student union banner",
        "United Auto Workers logo on shirt",
    ],
    "summary": "About 30 people gather at the Caltech south gate chanting for stipend increase.",
}


_VALID_INTENT: dict = {
    "topic": "Caltech grad student walkout",
    "what_is_happening": "About 30 graduate students rally at the Caltech south gate demanding a stipend increase.",
    "why_it_matters": "The walkout escalates an ongoing labor dispute between the graduate union and the institute.",
    "evidence_trail": [
        {
            "claim": "Walkout demands stipend increase",
            "supporting_evidence": ["STIPEND NOW", "Stipend! When do we want it?"],
        },
        {
            "claim": "Union-organized event",
            "supporting_evidence": ["Caltech graduate student union banner"],
        },
    ],
    "title": "Grad Students Rally At Caltech Gate",
    "caption": (
        "About thirty graduate students gather at the south gate chanting "
        "for a stipend increase. A union banner and audible call-and-response "
        "are visible in the early-evening light."
    ),
}


# ---------------------------------------------------------------------------
# Test 1 — extract_evidence_for_parent: schema-shaped happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_evidence_for_parent_returns_schema_shape(monkeypatch, tmp_path):
    """Stubbed Gemini SDK returns EvidenceJSON; function returns the validated dict."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")

    # Build a fake client whose method chain matches the real SDK:
    #   client.files.upload(file=...) -> obj with .name + .state.name
    #   client.files.get(name=...) -> obj with .state.name
    #   client.files.delete(name=...) -> noop
    #   client.models.generate_content(...) -> obj with .text (JSON string)
    class _FakeFile:
        def __init__(self, name="files/test", active=True):
            self.name = name
            self.state = SimpleNamespace(name="ACTIVE" if active else "PROCESSING")

    fake_response = SimpleNamespace(text=json.dumps(_VALID_EVIDENCE))

    class _FakeFiles:
        def upload(self, file=None):
            return _FakeFile(active=True)

        def get(self, name=None):
            return _FakeFile(name=name, active=True)

        def delete(self, name=None):
            return None

    class _FakeModels:
        def generate_content(self, model=None, contents=None, config=None):
            return fake_response

    class _FakeClient:
        def __init__(self, api_key=None, http_options=None):
            self.files = _FakeFiles()
            self.models = _FakeModels()

    # google.genai is imported INSIDE extract_evidence_for_parent.
    # Patch the symbol on the (already-imported) module so the late import sees it.
    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", _FakeClient)

    # Resolve a "local" parent_path that exists on disk so _resolve_parent_input_to_local
    # passes the existence check.
    local_video = tmp_path / "parent.mp4"
    local_video.write_bytes(b"fake-mp4-bytes")
    parent_clip = {
        "id": "p1",
        "parent_path": str(local_video),
        "parent_blob_url": None,
        "lat": 34.137,
        "lng": -118.125,
        "ts": 1714680000.0,
    }

    result = await cap.extract_evidence_for_parent(parent_clip)

    assert result is not None, "expected EvidenceJSON dict, got None"
    assert set(result.keys()) == {
        "signs", "audio_transcript", "visual_cues", "affiliations", "summary",
    }, f"unexpected keys: {set(result.keys())}"
    assert isinstance(result["signs"], list)
    assert all(isinstance(s, dict) and "text" in s and "context" in s for s in result["signs"])
    assert isinstance(result["audio_transcript"], str)
    assert isinstance(result["visual_cues"], list)
    assert all(isinstance(c, str) for c in result["visual_cues"])
    assert isinstance(result["affiliations"], list)
    assert all(isinstance(a, str) for a in result["affiliations"])
    assert isinstance(result["summary"], str)
    # Spot-check round-trip integrity.
    assert result["signs"][0]["text"] == "STIPEND NOW"
    assert "Stipend" in result["audio_transcript"]


# ---------------------------------------------------------------------------
# Test 2 — extract_evidence_for_parent returns None without API key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_evidence_for_parent_returns_none_when_no_api_key(monkeypatch, tmp_path):
    """Empty GEMINI_API_KEY -> early return None; no SDK touched."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")

    # Patch the import target to detonate if reached — confirms early exit.
    import google.genai as genai_mod

    def _boom(*a, **kw):
        raise AssertionError("Client must NOT be constructed when API key is empty")

    monkeypatch.setattr(genai_mod, "Client", _boom)

    parent_clip = {
        "id": "p1",
        "parent_path": str(tmp_path / "parent.mp4"),
        "parent_blob_url": None,
        "lat": 34.0,
        "lng": -118.0,
        "ts": 1.0,
    }
    result = await cap.extract_evidence_for_parent(parent_clip)
    assert result is None


# ---------------------------------------------------------------------------
# Test 3 — synthesize_intent parses + derives title/caption
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_intent_parses_response_and_derives_title_caption(monkeypatch):
    """Stubbed claude_agent_sdk.query yields ResultMessage with canned IntentJSON."""

    # Build a ResultMessage-ish stub. claude_agent_sdk.ResultMessage carries:
    #   is_error, num_turns, errors, duration_ms, result (the assistant text).
    class _StubResult:
        is_error = False
        num_turns = 1
        errors = None
        duration_ms = 100
        result = json.dumps(_VALID_INTENT)

    async def _fake_query(prompt=None, options=None):
        # Identify path: ResultMessage is the type cap.synthesize_intent tests via
        # `isinstance(msg, ResultMessage)`. Easiest: yield the actual class.
        from claude_agent_sdk import ResultMessage
        # ResultMessage is a dataclass-like class; build one with the needed fields.
        try:
            yield ResultMessage(
                subtype="result",
                duration_ms=100,
                duration_api_ms=100,
                is_error=False,
                num_turns=1,
                session_id="test",
                total_cost_usd=0.0,
                usage={},
                result=json.dumps(_VALID_INTENT),
            )
        except TypeError:
            # Fallback: yield a SimpleNamespace that passes isinstance via subclassing
            # is impossible — but synthesize_intent only reads .is_error and .result.
            # Replace ResultMessage with a permissive stand-in for isinstance().
            yield _StubResult()

    # Replace ResultMessage at the cap module's import binding so isinstance() check
    # is permissive (tolerates the SimpleNamespace fallback).
    import claude_agent_sdk
    real_rm = claude_agent_sdk.ResultMessage

    monkeypatch.setattr(cap, "query", _fake_query)
    # Make the isinstance() check accept _StubResult too — by setting cap.ResultMessage
    # to a tuple of acceptable types via __class__ swap is fragile; instead bind a
    # union-via-tuple by monkeypatching the binding to a class that covers both.
    # Cleanest path: keep ResultMessage as-is; the inner `try` succeeds when the
    # SDK accepts the kwargs we passed.

    result = await cap.synthesize_intent(
        evidence_list=[_VALID_EVIDENCE],
        location="Pasadena, CA",
        when_iso="May 1, 2026",
    )

    assert result is not None, "expected IntentJSON dict, got None"
    assert "title" in result and "caption" in result
    assert isinstance(result["title"], str)
    assert isinstance(result["caption"], str)
    assert len(result["title"]) <= 60, f"title over 60 chars: {result['title']!r}"
    assert 80 <= len(result["caption"]) <= 400, (
        f"caption length {len(result['caption'])} outside 80..400"
    )
    assert isinstance(result["evidence_trail"], list)
    assert len(result["evidence_trail"]) >= 1

    # Restore ResultMessage to the real value (defensive — monkeypatch teardown
    # would do this, but we never bound a replacement).
    assert claude_agent_sdk.ResultMessage is real_rm


# ---------------------------------------------------------------------------
# Test 4 — synthesize_intent returns None on unparseable response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_intent_returns_none_on_unparseable(monkeypatch):
    """Garbage response from query() -> None."""
    async def _fake_query(prompt=None, options=None):
        from claude_agent_sdk import ResultMessage
        try:
            yield ResultMessage(
                subtype="result",
                duration_ms=100,
                duration_api_ms=100,
                is_error=False,
                num_turns=1,
                session_id="test",
                total_cost_usd=0.0,
                usage={},
                result="this is not json and never will be {{{{",
            )
        except TypeError:
            yield SimpleNamespace(
                is_error=False,
                result="this is not json and never will be {{{{",
            )

    monkeypatch.setattr(cap, "query", _fake_query)

    result = await cap.synthesize_intent(
        evidence_list=[_VALID_EVIDENCE],
        location="Pasadena, CA",
        when_iso="May 1, 2026",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Test 5 — run_evidence_to_intent_pipeline skips failed-extraction parents
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_evidence_to_intent_pipeline_skips_failed_parents(monkeypatch):
    """[evidence, None, evidence] -> synthesize sees 2 items, returns dict."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")

    # Round-robin per-parent extraction: [ok, None, ok].
    extracted: list[dict | None] = [_VALID_EVIDENCE, None, _VALID_EVIDENCE]
    call_idx = {"i": 0}

    async def _fake_extract(parent_clip):
        i = call_idx["i"]
        call_idx["i"] = i + 1
        return extracted[i]

    monkeypatch.setattr(cap, "extract_evidence_for_parent", _fake_extract)

    seen_evidence: dict = {"value": None}

    async def _fake_synthesize(evidence_list, location, when_iso):
        seen_evidence["value"] = list(evidence_list)
        return _VALID_INTENT

    monkeypatch.setattr(cap, "synthesize_intent", _fake_synthesize)

    parents = [
        {"id": "p1", "parent_path": "/tmp/p1.mp4", "ts": 1.0},
        {"id": "p2", "parent_path": "/tmp/p2.mp4", "ts": 2.0},
        {"id": "p3", "parent_path": "/tmp/p3.mp4", "ts": 3.0},
    ]
    result = await cap.run_evidence_to_intent_pipeline("c1", parents, "Pasadena, CA")

    assert result is not None
    assert result["source"] == "vision"
    assert result["title"] == _VALID_INTENT["title"]
    assert result["caption"] == _VALID_INTENT["caption"]
    assert isinstance(result["evidence"], list)
    assert len(result["evidence"]) == 2, "expected 2 successful evidence items"
    assert seen_evidence["value"] is not None
    assert len(seen_evidence["value"]) == 2


# ---------------------------------------------------------------------------
# Test 6 — run_evidence_to_intent_pipeline returns None when ALL parents fail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_evidence_to_intent_pipeline_returns_none_when_all_evidence_fails(monkeypatch):
    """Every per-parent extraction returns None -> overall pipeline returns None."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-not-real")

    async def _fake_extract(parent_clip):
        return None

    monkeypatch.setattr(cap, "extract_evidence_for_parent", _fake_extract)

    # synthesize_intent must NEVER be called when there is no evidence.
    synth_calls: list[int] = []

    async def _fake_synthesize(*a, **kw):
        synth_calls.append(1)
        return _VALID_INTENT

    monkeypatch.setattr(cap, "synthesize_intent", _fake_synthesize)

    parents = [
        {"id": "p1", "parent_path": "/tmp/p1.mp4", "ts": 1.0},
        {"id": "p2", "parent_path": "/tmp/p2.mp4", "ts": 2.0},
    ]
    result = await cap.run_evidence_to_intent_pipeline("c1", parents, "Pasadena, CA")

    assert result is None
    assert synth_calls == [], "synthesize_intent must NOT be called with empty evidence"


# ---------------------------------------------------------------------------
# Test 7 — anonymity guard text present in EVIDENCE_SYSTEM_PROMPT
# ---------------------------------------------------------------------------

def test_anonymity_prompt_blocks_face_descriptions():
    """Static check: prompt regression sentinel.

    Codifies the anonymity guard from <constraints>: faces of bystanders +
    license plates + identifying private detail MUST NOT appear; public
    figures at podiums + visible affiliations + symbols/logos are reportable.
    """
    prompt = cap.EVIDENCE_SYSTEM_PROMPT
    assert "MUST NOT" in prompt, "anonymity guard MUST NOT clause missing"
    assert (
        "faces of bystanders" in prompt.lower()
        or "identifying details" in prompt.lower()
    ), "anonymity guard target phrasing missing"
    # Positive carve-out for public figures / affiliations should still be present.
    assert "podium" in prompt.lower(), "public-figure carve-out missing"
    # License plate prohibition.
    assert "license plate" in prompt.lower(), "license plate prohibition missing"
