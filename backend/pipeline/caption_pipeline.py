"""
backend/pipeline/caption_pipeline.py — two-stage evidence + intent caption pipeline.

Public API (quick task 260501-bet):
    extract_evidence_for_parent(parent_clip) -> dict | None
        Per-parent Gemini call. Uploads the FULL parent video so audio is
        preserved. Returns structured EvidenceJSON (signs, audio_transcript,
        visual_cues, affiliations, summary) or None on failure.

    synthesize_intent(evidence_list, location, when_iso) -> dict | None
        Cluster-level Claude call. Takes the array of evidence dicts and emits
        an IntentJSON (topic, what_is_happening, why_it_matters, evidence_trail,
        title, caption). Title + caption are derived from intent so the
        downstream segment row keeps the existing Segment.title / Segment.caption
        contract green for the frontend.

    run_evidence_to_intent_pipeline(cluster_id, parents, location) -> dict | None
        Top-level: fan-out evidence extraction across parents, then synthesize.
        On success returns
            {"title", "caption", "location", "source": "vision",
             "evidence": [...], "intent": {...}}
        On total failure returns None.

    generate_caption(cluster_id, centroid, children) -> dict | None  # backward-compat
        Resolves parents from children and routes through
        run_evidence_to_intent_pipeline. compile.py:_branch_caption already
        calls this; the discriminator at compile.py:611 (source == "vision")
        keeps working unchanged.

Replaces the prior single-Gemini-call-on-stitched-composite pipeline. Two stages:
(1) per-parent structured evidence extraction (Gemini surfacing signs / chants
/ affiliations / visual cues), (2) cluster-level Claude synthesis turning that
evidence array into an event-level intent. Asking the vision model for evidence
rather than prose, then handing that evidence to a stronger reasoner, is what
turns "people walking with signs" into "Caltech grad students walk out
demanding stipend increase."
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
)

from .. import config
from .geocode import reverse_geocode
from .stitch import stitch_clips

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an AP-wire breaking-news writer for a hyperlocal news app.
Watch the footage and write a TITLE plus a CAPTION. They serve different jobs.

==============================
TITLE — the headline
==============================
- 4 to 8 words. HARD CAP: 60 characters total (count them).
- Present tense, active voice. No period. No quotes. Not a question.
- Names the EVENT in plain language. This is what a newspaper would print above the photo.
- Title Case ("Crowd Gathers At Caltech Gates"), not ALL CAPS, not sentence case.

==============================
CAPTION — the lede
==============================
- OPEN with an event-framing verb. The first clause must name WHAT HAPPENED
  (gathered, marched, blocked, demanded, dispersed, struck, deployed,
  intervened, cleared, arrived, rallied, walked out, occupied, evacuated,
  halted, confronted, assembled, picketed). Do NOT open with a descriptive
  tableau ("A row of...", "A man in...", "Roughly thirty people stand...") —
  that reads like a video transcript, not news.
- Front-load WHO and WHERE in sentence 1 when known. Save sensory detail
  (color, count, audio, weather, clothing) for sentences 2-3.
- 2 to 3 sentences. Aim for 250-350 characters. HARD CAP: 400 characters total.
- MUST add at least TWO specific details NOT in the title:
    audio cue, color, count, distinctive object, weather, action verb, motion,
    lighting, clothing, time-of-day.
- Third person, neutral tone.
- End with a period.
- The caption is NOT a rephrasing of the title. If you remove the title, the
  caption must still tell the reader something new.
- Use audio cues when they're informative (mechanical sounds, voices, ambient).

==============================
NEVER DO
==============================
- Never reference the medium itself: forbidden words include "video", "clip",
  "footage", "frame", "frames", "camera", "shot", "filmed", "recording",
  "sequence of frames".
- Never write "appears to" or "seems to" — state what's there or omit it.
- Never repeat the title's main noun phrase verbatim in the caption.
- Never make up a count of people if it isn't unambiguous (≤5 visible).
- Never write a title that exceeds 8 words OR 60 characters.

==============================
WHEN CONTENT IS AMBIGUOUS
==============================
If the footage is generic (a face, a wall, an ordinary indoor scene), prefer a
SHORT factual headline over a long creative one. Don't pad with adjectives to
seem newsworthy. "Resident Pauses In Doorway" beats "Young Man In Contemplative
Moment Inside Fluorescent-Lit Office".

==============================
LOCATION
==============================
Use the location string provided in the user message verbatim. Do not invent.

==============================
GOOD EXAMPLES (study the title-vs-caption split — every caption OPENS with an event verb)
==============================
{"title": "Crowd Rallies At Caltech South Gate",
 "caption": "Roughly thirty demonstrators gathered at Caltech's south entrance late Friday, several raising handmade cardboard signs as a bullhorn cut in and out. Sky overcast, daylight fading; a single bicycle leaned against the gate post.",
 "location": "Pasadena, CA"}

{"title": "Recycling Bins Toppled On Lake Avenue",
 "caption": "Vandals overturned a row of blue municipal bins along Lake Avenue overnight, scattering loose paper and a torn cardboard box across the asphalt. A sedan passed at first light; bird calls were the only ambient sound.",
 "location": "Pasadena, CA"}

{"title": "Hacktech Banner Lights Caltech Walkway",
 "caption": "Organizers lit a glowing white 'HACKTECH' marquee along the red-brick walkway at dusk Friday, drawing a small group of students past the warm-evening hum of a portable generator. A folded blue tarp sat at the curb.",
 "location": "Pasadena, CA"}

{"title": "Resident Paces In Pasadena Home",
 "caption": "A resident moved between two interior rooms of a Pasadena home late Thursday, briefly steadying a hand against the wall. A low fan hummed under a single door creak; lighting was dim and yellow-tinged.",
 "location": "Pasadena, CA"}

==============================
BAD EXAMPLES (do NOT imitate)
==============================
BAD — reads like a video description, not a news lede:
{"title": "Crowd Gathers At Caltech South Gate",
 "caption": "Roughly thirty people stand shoulder-to-shoulder near the entrance, several holding handmade cardboard signs. A bullhorn cuts in and out audibly."}
Why bad: caption opens with a static descriptive tableau ("Roughly thirty people stand..."). Reads like a vision model's narration, not a wire lede. The first verb must name the EVENT (rallied / gathered / overturned), not describe a frozen frame.
NEWS-LEDE REWRITE:
{"title": "Crowd Rallies At Caltech South Gate",
 "caption": "Roughly thirty demonstrators gathered at Caltech's south entrance late Friday, several raising handmade cardboard signs as a bullhorn cut in and out."}

BAD — reads like a video description, not a news lede:
{"title": "Recycling Bins Topple On Lake Avenue",
 "caption": "A row of blue municipal bins lies overturned along the curb on Lake Avenue at first light. Loose paper drifts across the asphalt."}
Why bad: caption opens with a static descriptive tableau ("A row of blue bins lies..."). Reads like a vision model's narration, not a wire lede. The first verb must name the EVENT (rallied / gathered / overturned), not describe a frozen frame.
NEWS-LEDE REWRITE:
{"title": "Recycling Bins Toppled On Lake Avenue",
 "caption": "Vandals overturned a row of blue municipal bins along Lake Avenue overnight, scattering loose paper across the asphalt at first light."}

BAD — title and caption identical, too long, forbidden words ("camera", "frame"):
{"title": "Pasadena Youth Captured On Elevator Camera In Series Of Poses, Final Frame Shows Hoodie Lifted",
 "caption": "Pasadena Youth Captured On Elevator Camera In Series Of Poses, Final Frame Shows Hoodie Lifted"}
GOOD alternative for the same content:
{"title": "Resident Pauses In Elevator",
 "caption": "A person in a hooded sweatshirt stands still as the elevator moves between floors. A mechanical hum is audible.",
 "location": "Pasadena, CA"}

BAD — title and caption say the same thing:
{"title": "Young Man In Office, Hand Drifting From Face",
 "caption": "Young man in office, hand drifting from face."}

BAD — title is too long, references the medium:
{"title": "Young Man Caught In Contemplative Moment Inside Fluorescent-Lit Office, Hand Drifting From Face In Sequence Of Frames",
 "caption": "..."}

BAD — caption is just a rephrase of the title with no new info:
{"title": "Crowd Gathers At Caltech Gates",
 "caption": "A crowd has gathered at the gates of Caltech."}

BAD — speculative hedging:
{"title": "Possible Protest Forming",
 "caption": "What appears to be the start of some kind of demonstration..."}

==============================
SELF-CHECK BEFORE EMITTING JSON
==============================
Before you finalize your output, silently verify ALL of these. If any fails,
rewrite that field. Do not emit JSON until all six pass:
  (a) Title word count is between 4 and 8 (count the words).
  (b) Title contains NONE of: video, clip, footage, frame, frames, camera,
      shot, filmed, recording, sequence.
  (c) Title and caption do NOT share more than 3 consecutive words.
  (d) Caption mentions at least TWO specific details (audio cue, color, count,
      object, action verb, weather, lighting, clothing) that are NOT in the title.
  (e) Caption is between 2 and 3 sentences and reaches at least 80 characters.
  (f) Caption sentence 1 opens with an event-framing verb naming WHAT HAPPENED
      — not a descriptive tableau ("A row of...", "A man in...", "Roughly
      thirty people stand..."). If sentence 1 reads like a video narration,
      rewrite it.
"""


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title":    {"type": "STRING", "minLength": 12, "maxLength": 60},
        "caption":  {"type": "STRING", "minLength": 80, "maxLength": 400},
        "location": {"type": "STRING"},
    },
    "required": ["title", "caption", "location"],
    "propertyOrdering": ["title", "caption", "location"],
}


_FORBIDDEN_TITLE_WORDS = {
    "video", "clip", "footage", "frame", "frames", "camera",
    "shot", "filmed", "recording", "sequence",
}

_TITLE_HARD_CAP = 60
_TITLE_MAX_WORDS = 8


def _strip_forbidden_words(text: str) -> str:
    """Remove forbidden vocabulary tokens from a string, preserving punctuation."""
    out_words = []
    for w in text.split():
        bare = w.lower().strip(",.;:!?'\"()[]")
        if bare in _FORBIDDEN_TITLE_WORDS:
            continue
        out_words.append(w)
    return " ".join(out_words).strip(" ,.;:")


def _truncate_to_word_boundary(text: str, max_chars: int, max_words: int) -> str:
    """Cut at the last word boundary that fits both caps."""
    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    out = " ".join(words)
    if len(out) <= max_chars:
        return out
    # binary-walk back word-by-word until we fit
    while words and len(" ".join(words)) > max_chars:
        words.pop()
    return " ".join(words).rstrip(" ,.;:-")


def _shares_long_run(a: str, b: str, n: int = 4) -> bool:
    """True if a and b share an n-word contiguous substring (case-insensitive)."""
    a_words = a.lower().split()
    b_lower = b.lower()
    for i in range(0, max(0, len(a_words) - n + 1)):
        run = " ".join(a_words[i:i + n])
        if run in b_lower:
            return True
    return False


def _sanitize_output(parsed: dict, location: str) -> dict:
    """Layer 2 deterministic guard. Mutates parsed in place + returns it.

    Catches Gemini misbehavior the prompt couldn't prevent:
      - Forbidden vocabulary in title (camera, frame, ...)
      - Title over 60 chars or 8 words
      - Title == caption or large overlap
      - Empty/missing location → use the canonical one we passed in
    """
    title_in = (parsed.get("title") or "").strip()
    caption_in = (parsed.get("caption") or "").strip()
    location_in = (parsed.get("location") or "").strip()

    # Strip forbidden words + cap length
    title = _strip_forbidden_words(title_in)
    title = _truncate_to_word_boundary(title, _TITLE_HARD_CAP, _TITLE_MAX_WORDS)
    if not title:
        title = "Footage Captured"

    caption = caption_in
    if not caption:
        caption = "Multi-angle event captured by local contributors."

    # Detect title ≈ caption (identical OR caption is a near-substring of title's stripped form OR vice versa)
    title_norm = title.lower().strip(" ,.;:")
    caption_norm = caption.lower().strip(" ,.;:")
    duplicate = (
        title_norm == caption_norm
        or title_norm in caption_norm
        or caption_norm in title_norm
        or _shares_long_run(title, caption, n=4)
    )

    if duplicate:
        log.warning(
            "sanitize: title≈caption duplicate detected — patching caption. "
            "title=%r caption=%r", title, caption
        )
        # Replace caption with a generic enrichment that at least differs from title.
        # Better than emitting two copies of the same string.
        caption = (
            "Multiple contributors recorded the scene from nearby vantage "
            "points. Background sound and ambient detail captured."
        )

    if not location_in:
        location_in = location

    parsed["title"] = title
    parsed["caption"] = caption
    parsed["location"] = location_in
    return parsed


# ---------------------------------------------------------------------------
# Quick task 260501-bet: per-parent evidence extraction (Stage 1 — Gemini)
# ---------------------------------------------------------------------------

EVIDENCE_SYSTEM_PROMPT = """You are a vision-and-audio evidence extractor for a hyperlocal news pipeline.
You are NOT writing prose. You are surfacing structured EVIDENCE so a downstream
reasoner (a separate model) can synthesize the event-level meaning.

==============================
WHAT TO EXTRACT
==============================
For each videorecording, return JSON with these fields:

- signs: list of objects, one per visible sign / placard / banner / poster /
  printed text. Each object has:
    {"text": "<exact words on the sign>", "context": "<who is holding it / where it is>"}
  If the same text appears on multiple identical signs, list it once with a
  count note in context (e.g. "held by 4 people in front row"). Empty list when
  no signs are visible.

- audio_transcript: a single string. Transcribe chants, speech, announcements,
  PA-system audio, public-figure remarks at podiums VERBATIM in their native
  language. AUDIO IS AT LEAST AS LOAD-BEARING AS ON-SCREEN TEXT. Crowd chants,
  speeches, and announcements are exactly the kind of evidence the downstream
  synthesizer needs. If there is no informative audio (only ambient sound),
  emit "" (empty string), NOT a description of silence.

- visual_cues: list of strings. Concrete observable tokens — clothing, colors,
  objects, weather, lighting, time-of-day, vehicles, setting type, posture,
  motion patterns, count estimates when unambiguous (<=10 visible).
  Examples: "approximately 30 people", "blue tarp on curb", "police barricade",
  "graduation gowns", "rainy / wet pavement", "early evening".

- affiliations: list of strings. Org names, flag designs, logos, banner text,
  uniform insignia, public-figure names visible at podiums or on speaker
  placards. ANONYMITY-SAFE TARGETS ONLY (see anonymity guard below).
  Examples: "Caltech graduate student union banner", "United Auto Workers",
  "Mayor Victor Gordo (visible at podium)", "rainbow Pride flag",
  "American flag".

- summary: ONE neutral sentence describing what is observable in this
  recording. Not editorial. Not predictive. Not "appears to" / "seems to".
  Just what is actually on the screen + audio.

==============================
ANONYMITY GUARD — STRICT
==============================
The following ARE reportable / required:
  - Public figures speaking at podiums or on stages
  - Visible affiliations: organization names, logos, banners, flags, insignia
  - Symbols (political, religious, commercial — describe what's depicted)
  - Sign / placard / banner text VERBATIM
  - Public officials in their official capacity

The following MUST NOT appear in the output:
  - Faces of bystanders or private individuals (no descriptions like "a man
    with a beard wearing glasses")
  - Identifying details of private individuals (clothing color of a bystander
    is OK as a count-cue; "the woman in the red sweater near the bus stop"
    is NOT — that's identifying)
  - License plate numbers or partial plates
  - Home addresses, apartment numbers, street numbers on private residences
  - Phone numbers, email addresses, social media handles visible in the
    recording (UNLESS they are an organization's published contact info)

When in doubt about a person: if they are speaking AT a podium / from a stage
/ in an official capacity, they are reportable. Otherwise treat them as an
anonymous bystander and describe ONLY count + setting context.

==============================
NEVER DO
==============================
- Never reference the medium itself: forbidden words include "video", "clip",
  "footage", "frame", "frames", "camera", "shot", "filmed", "recording".
- Never write "appears to" or "seems to" — state what's there or omit it.
- Never invent a count of people if it isn't unambiguous.
- Never paraphrase a sign — transcribe verbatim or omit it.
- Never editorialize. The downstream synthesizer does the reasoning, not you.
"""


EVIDENCE_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "signs": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "text":    {"type": "STRING"},
                    "context": {"type": "STRING"},
                },
                "required": ["text", "context"],
                "propertyOrdering": ["text", "context"],
            },
        },
        "audio_transcript": {"type": "STRING"},
        "visual_cues":      {"type": "ARRAY", "items": {"type": "STRING"}},
        "affiliations":     {"type": "ARRAY", "items": {"type": "STRING"}},
        "summary":          {"type": "STRING"},
    },
    "required": ["signs", "audio_transcript", "visual_cues", "affiliations", "summary"],
    "propertyOrdering": [
        "signs", "audio_transcript", "visual_cues", "affiliations", "summary",
    ],
}


def _validate_evidence_shape(parsed: dict) -> dict | None:
    """Coerce a parsed Gemini response to the EvidenceJSON contract or return None.

    Lightweight type-guard: required keys present, lists are lists, signs are
    list-of-dicts. Drops malformed sub-items rather than failing whole-evidence
    so a partial extraction is still useful to the synthesizer.
    """
    if not isinstance(parsed, dict):
        return None
    required = ("signs", "audio_transcript", "visual_cues", "affiliations", "summary")
    if not all(k in parsed for k in required):
        return None

    signs_in = parsed.get("signs") or []
    if not isinstance(signs_in, list):
        return None
    signs: list[dict] = []
    for s in signs_in:
        if isinstance(s, dict) and isinstance(s.get("text"), str):
            signs.append({
                "text": s.get("text", ""),
                "context": s.get("context", "") if isinstance(s.get("context"), str) else "",
            })

    audio = parsed.get("audio_transcript")
    audio = audio if isinstance(audio, str) else ""

    cues_in = parsed.get("visual_cues") or []
    cues: list[str] = [c for c in cues_in if isinstance(c, str)] if isinstance(cues_in, list) else []

    aff_in = parsed.get("affiliations") or []
    affs: list[str] = [a for a in aff_in if isinstance(a, str)] if isinstance(aff_in, list) else []

    summary = parsed.get("summary")
    summary = summary if isinstance(summary, str) else ""

    return {
        "signs": signs,
        "audio_transcript": audio,
        "visual_cues": cues,
        "affiliations": affs,
        "summary": summary,
    }


async def _resolve_parent_input_to_local(parent_clip: dict) -> tuple[str | None, object | None]:
    """Resolve parent_clip's source video to a local path Gemini Files API can ingest.

    Local-mode: parent_path is a local FS path; pass through.
    Blob-mode: parent_blob_url is an authorized HTTPS URL; download to a tempfile.

    Returns (local_path_or_none, tmpfile_handle_or_none). Caller must close the
    tmpfile_handle (a tempfile.NamedTemporaryFile) when done; pass None for the
    handle in local-mode (no cleanup needed).

    Mirrors the blob-download pattern in generate_caption (lines 365-389) but
    operates per-parent instead of per-stitched-composite.
    """
    import tempfile
    from urllib.parse import urlparse

    parent_blob_url = parent_clip.get("parent_blob_url") or parent_clip.get("blob_url")
    parent_path = parent_clip.get("parent_path") or parent_clip.get("path")

    # Local-mode happy path.
    if parent_path and not str(parent_path).startswith("http"):
        if Path(parent_path).exists():
            return parent_path, None
        log.warning("evidence: local parent_path missing on disk: %s", parent_path)
        return None, None

    if not parent_blob_url:
        return None, None

    try:
        from ..storage import blob_client
        from ..storage.blob import authorized_blob_input

        pathname = urlparse(parent_blob_url).path.lstrip("/")
        url, headers = authorized_blob_input(pathname)
        client = blob_client.get_client()
        tmp_handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        local_path = tmp_handle.name
        try:
            async with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                with open(local_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
        except Exception:
            tmp_handle.close()
            try:
                Path(local_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise
        return local_path, tmp_handle
    except Exception:
        log.exception("evidence: failed to download blob parent for evidence extraction")
        return None, None


async def extract_evidence_for_parent(parent_clip: dict) -> dict | None:
    """Per-parent Gemini call. Returns EvidenceJSON or None on failure.

    parent_clip: dict with at least {parent_path | path, parent_blob_url | blob_url}.
                 Same row shape used by run-resolution + clustering paths.

    Honors OFFLINE_DEMO / missing GEMINI_API_KEY by returning None — caller
    will skip this parent (and the run_evidence_to_intent_pipeline aggregator
    falls back to legacy when zero parents survive extraction).
    """
    if not config.GEMINI_API_KEY:
        log.warning("extract_evidence: GEMINI_API_KEY not set — skipping")
        return None

    local_path, tmp_handle = await _resolve_parent_input_to_local(parent_clip)
    if not local_path:
        log.warning("extract_evidence: could not resolve parent input for clip=%s",
                    parent_clip.get("id") or parent_clip.get("parent_id"))
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=120_000),
        )

        loop = asyncio.get_running_loop()

        # 1. Upload (sync SDK call wrapped in executor)
        try:
            uploaded = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: client.files.upload(file=local_path)),
                timeout=30.0,
            )
        except Exception:
            log.exception("extract_evidence: upload failed")
            return None

        # 2. Poll until ACTIVE
        for _ in range(30):  # ~30s ceiling
            if uploaded.state.name == "ACTIVE":
                break
            await asyncio.sleep(1)
            uploaded = await loop.run_in_executor(
                None, lambda: client.files.get(name=uploaded.name)
            )
        if uploaded.state.name != "ACTIVE":
            log.warning(
                "extract_evidence: file did not reach ACTIVE state state=%s",
                uploaded.state.name,
            )
            return None

        user_prompt = (
            "Extract structured evidence from this videorecording per the schema. "
            "Transcribe audio chants/speech VERBATIM. Surface every visible sign. "
            "Note affiliations / org names / public-figure speakers. "
            "DO NOT describe faces of bystanders or other identifying private detail."
        )

        # 3. generate_content with structured JSON response
        try:
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=config.GEMINI_MODEL,
                        contents=[uploaded, user_prompt],
                        config=types.GenerateContentConfig(
                            system_instruction=EVIDENCE_SYSTEM_PROMPT,
                            temperature=0.2,
                            response_mime_type="application/json",
                            response_schema=EVIDENCE_RESPONSE_SCHEMA,
                        ),
                    ),
                ),
                timeout=125.0,
            )
        except Exception:
            log.exception("extract_evidence: generate_content failed")
            return None

        # 4. Parse + validate shape
        try:
            parsed = json.loads(response.text)
        except (TypeError, ValueError):
            log.warning("extract_evidence: response not valid JSON: %r",
                        (getattr(response, "text", "") or "")[:200])
            return None

        evidence = _validate_evidence_shape(parsed)
        if evidence is None:
            log.warning("extract_evidence: response missing required keys: %s",
                        list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__)
            return None

        # 5. Cleanup uploaded Gemini file (best-effort)
        try:
            await loop.run_in_executor(
                None, lambda: client.files.delete(name=uploaded.name)
            )
        except Exception as e:
            log.warning("extract_evidence: file cleanup failed: %s", e)

        log.info(
            "extract_evidence ok signs=%d audio_chars=%d cues=%d affiliations=%d",
            len(evidence["signs"]),
            len(evidence["audio_transcript"]),
            len(evidence["visual_cues"]),
            len(evidence["affiliations"]),
        )
        return evidence

    except Exception:
        log.exception("extract_evidence: unexpected error")
        return None
    finally:
        # Clean up the tempfile we created for blob-mode downloads. Local-mode
        # passes the user's actual file through; we MUST NOT delete it.
        if tmp_handle is not None:
            try:
                tmp_handle.close()
            except Exception:
                pass
            try:
                Path(local_path).unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Quick task 260501-bet: cluster-level intent synthesis (Stage 2 — Claude)
# ---------------------------------------------------------------------------

INTENT_SYSTEM_INSTRUCTION = """You are an AP-wire breaking-news synthesizer.

Below is structured EVIDENCE extracted by a vision-and-audio model from N
independent recordings of (almost certainly) the same event. Each entry is a
JSON object with: signs (sign text + context), audio_transcript (verbatim
chants/speech), visual_cues, affiliations, summary.

YOUR JOB: synthesize the event-level intent. Then derive a 4-8 word AP-wire
headline TITLE and a 2-3 sentence neutral CAPTION.

==============================
SYNTHESIS RULES
==============================
- Ground every claim in the evidence array. Do not invent facts.
- Cite which evidence items support which claims (evidence_trail[]).
- Cross-reference: if 3 of 4 recordings show "Caltech grad union" affiliation
  and audio chants demand "stipend increase", the topic is the walkout, not
  "people walking with signs".
- If evidence is too thin to determine intent (e.g. only one summary line,
  no signs, no audio), prefer a CONSERVATIVE description over a confident one.

==============================
TITLE / CAPTION RULES
==============================
- Title: 4 to 8 words. HARD CAP: 60 characters total. Title Case.
  Present tense, active voice. No period. No quotes. Not a question.
  Must NOT contain: video, clip, footage, frame, frames, camera, shot,
  filmed, recording, sequence.
- Caption: 2 to 3 sentences. 80-400 characters. Third person, neutral tone.
  Ends with a period. Adds AT LEAST TWO specific details NOT in the title
  (audio cue, count, distinctive object, time-of-day, weather, action verb,
  affiliation name, sign text).
- Caption is NOT a rephrasing of the title.

==============================
ANONYMITY (carry-through)
==============================
- Public figures at podiums + organizational affiliations: REPORTABLE.
- Bystander descriptions / license plates / private addresses: DO NOT
  REPRODUCE — even if the upstream evidence accidentally included them.
  Strip them silently.

==============================
RESPONSE FORMAT — STRICT JSON
==============================
Return ONE JSON object, exactly these keys, in this order:

{
  "topic": "<short noun phrase, 2-6 words>",
  "what_is_happening": "<1-2 sentences, neutral, evidence-grounded>",
  "why_it_matters": "<1-2 sentences, evidence-grounded>",
  "evidence_trail": [
    {"claim": "<one claim from above>",
     "supporting_evidence": ["<verbatim phrase or paraphrase from evidence>", "..."]}
  ],
  "title": "<4-8 word headline>",
  "caption": "<2-3 sentence lede>"
}

Wrapping the object in a single ```json ... ``` fence is OK. Do not return
anything else after the JSON.
"""


def _extract_intent_json(text: str) -> dict | None:
    """Tolerant JSON extractor — direct parse, then fence-strip, then balanced-brace fallback.

    Mirrors compile.py:_extract_run_ids' fence-aware parser. Returns None on
    any unrecoverable parse failure.
    """
    if not text:
        return None

    # 1. Direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (TypeError, ValueError):
        pass

    candidates: list[str] = []

    # 2. ```json ... ``` fence (longest match wins)
    fence_re = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    candidates.extend(fence_re.findall(text))

    # 3. Last balanced top-level object
    last_brace = text.rfind("}")
    if last_brace != -1:
        depth = 0
        start = -1
        for i in range(last_brace, -1, -1):
            ch = text[i]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    start = i
                    break
        if start != -1:
            candidates.append(text[start:last_brace + 1])

    for raw in candidates:
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj

    return None


def _validate_intent_shape(parsed: dict | None) -> dict | None:
    """Coerce + sanitize an IntentJSON. Returns None if title/caption can't be salvaged.

    Applies:
      - required-key check (topic, what_is_happening, why_it_matters, title, caption)
      - title length / forbidden-word strip / word-boundary truncate
      - title-vs-caption duplicate detection (same handling as _sanitize_output)
      - evidence_trail defaulting to [] if missing/malformed
    """
    if not isinstance(parsed, dict):
        return None

    title_in = parsed.get("title")
    caption_in = parsed.get("caption")
    if not isinstance(title_in, str) or not isinstance(caption_in, str):
        return None
    title_in = title_in.strip()
    caption_in = caption_in.strip()
    if not title_in or not caption_in:
        return None

    # Reuse the existing sanitization helpers — same forbidden-word ladder
    # and length cap as the legacy single-call pipeline.
    title = _strip_forbidden_words(title_in)
    title = _truncate_to_word_boundary(title, _TITLE_HARD_CAP, _TITLE_MAX_WORDS)
    if not title:
        title = "Footage Captured"

    caption = caption_in
    title_norm = title.lower().strip(" ,.;:")
    caption_norm = caption.lower().strip(" ,.;:")
    duplicate = (
        title_norm == caption_norm
        or title_norm in caption_norm
        or caption_norm in title_norm
        or _shares_long_run(title, caption, n=4)
    )
    if duplicate:
        log.warning(
            "synthesize_intent: title≈caption duplicate detected — patching caption"
        )
        caption = (
            "Multiple contributors recorded the scene from nearby vantage "
            "points. Background sound and ambient detail captured."
        )

    topic = parsed.get("topic")
    topic = topic if isinstance(topic, str) else ""
    what = parsed.get("what_is_happening")
    what = what if isinstance(what, str) else ""
    why = parsed.get("why_it_matters")
    why = why if isinstance(why, str) else ""

    trail_in = parsed.get("evidence_trail")
    trail: list[dict] = []
    if isinstance(trail_in, list):
        for entry in trail_in:
            if not isinstance(entry, dict):
                continue
            claim = entry.get("claim")
            supports = entry.get("supporting_evidence") or []
            if not isinstance(claim, str):
                continue
            if isinstance(supports, list):
                supports = [s for s in supports if isinstance(s, str)]
            else:
                supports = []
            trail.append({"claim": claim, "supporting_evidence": supports})

    return {
        "topic": topic,
        "what_is_happening": what,
        "why_it_matters": why,
        "evidence_trail": trail,
        "title": title,
        "caption": caption,
    }


async def synthesize_intent(
    evidence_list: list[dict],
    location: str,
    when_iso: str,
) -> dict | None:
    """Cluster-level Claude synthesis. Returns IntentJSON dict or None.

    Calls claude_agent_sdk.query() with model='sonnet', no MCP tools (pure
    synthesis — the reasoner has all it needs in the prompt body).

    Wraps the SDK call in asyncio.wait_for(timeout=60s) so the cluster-level
    synthesis cannot blow the 300s compile budget regardless of SDK behaviour.
    """
    if not evidence_list:
        return None

    # Inline the evidence array as JSON in the prompt. The synthesizer doesn't
    # need a tool call — everything it needs is here.
    prompt_body = (
        f"Date: {when_iso}\n"
        f"Location: {location}\n\n"
        f"Number of independent recordings: {len(evidence_list)}\n\n"
        f"EVIDENCE (JSON array, one item per recording):\n"
        f"{json.dumps(evidence_list, indent=2, ensure_ascii=False)}\n\n"
        "Synthesize the event-level intent and emit one IntentJSON object per "
        "the schema in your system instruction."
    )

    options = ClaudeAgentOptions(
        model="sonnet",
        max_turns=3,
        system_prompt=INTENT_SYSTEM_INSTRUCTION,
    )

    final_text: str | None = None
    try:
        async def _run() -> str | None:
            text: str | None = None
            async for msg in query(prompt=prompt_body, options=options):
                if isinstance(msg, ResultMessage):
                    if msg.is_error:
                        log.error(
                            "synthesize_intent: SDK returned is_error=True turns=%s errors=%s",
                            msg.num_turns, msg.errors,
                        )
                        return None
                    text = msg.result
                    break
            return text

        final_text = await asyncio.wait_for(_run(), timeout=60.0)
    except asyncio.TimeoutError:
        log.warning("synthesize_intent: TIMEOUT after 60s")
        return None
    except Exception:
        log.exception("synthesize_intent: SDK call failed")
        return None

    if not final_text:
        log.warning("synthesize_intent: empty response")
        return None

    parsed = _extract_intent_json(final_text)
    intent = _validate_intent_shape(parsed)
    if intent is None:
        log.warning(
            "synthesize_intent: could not extract / validate IntentJSON text=%r",
            (final_text or "")[:300],
        )
        return None

    log.info(
        "synthesize_intent ok title=%r caption_len=%d trail_len=%d",
        intent.get("title"), len(intent.get("caption", "")),
        len(intent.get("evidence_trail", [])),
    )
    return intent


async def run_evidence_to_intent_pipeline(
    cluster_id: str,
    parents: list[dict],
    location: str,
) -> dict | None:
    """Top-level orchestration: fan-out evidence extraction, then synthesize intent.

    parents: list of parent-clip dicts (parent_id IS NULL rows from
             fetch_cluster_clips_with_children, or pre-resolved equivalents).

    Returns the standard caption_pipeline result shape:
        {"title", "caption", "location", "source": "vision",
         "evidence": [...], "intent": {...}}
    where source="vision" preserves the discriminator at compile.py:611.

    Returns None on total failure (zero successful evidence extractions OR
    intent synthesis failure). compile_segment then routes through the
    existing fallback path (CMP-06 / _save_fallback_segment).
    """
    if not parents:
        log.warning("evidence_to_intent: cluster %s has no parents", cluster_id)
        return None

    if not config.GEMINI_API_KEY:
        log.warning("evidence_to_intent: GEMINI_API_KEY not set — falling back")
        return None

    # Stage 1: per-parent extraction in parallel.
    tasks = [extract_evidence_for_parent(p) for p in parents]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    evidence_list: list[dict] = []
    for r in raw_results:
        if isinstance(r, Exception):
            log.warning("evidence_to_intent: per-parent extraction raised: %s", r)
            continue
        if isinstance(r, dict):
            evidence_list.append(r)

    if not evidence_list:
        log.warning(
            "evidence_to_intent: zero successful evidence extractions for cluster %s",
            cluster_id,
        )
        return None

    log.info(
        "evidence_to_intent: %d/%d parents produced evidence cluster=%s",
        len(evidence_list), len(parents), cluster_id,
    )

    # Determine when_iso for the synthesis prompt. Use the earliest parent ts
    # available (matches the legacy single-call pipeline's date stamp).
    ts_candidates: list[float] = [
        float(t) for p in parents if (t := p.get("ts")) is not None
    ]
    if ts_candidates:
        when_iso = datetime.fromtimestamp(min(ts_candidates), tz=timezone.utc).strftime("%b %-d, %Y")
    else:
        when_iso = datetime.now(tz=timezone.utc).strftime("%b %-d, %Y")

    # Stage 2: cluster-level Claude synthesis.
    intent = await synthesize_intent(evidence_list, location, when_iso)
    if intent is None:
        return None

    return {
        "title": intent["title"],
        "caption": intent["caption"],
        "location": location,
        "source": "vision",  # discriminator @ compile.py:611
        "evidence": evidence_list,
        "intent": intent,
    }


def _select_caption_children(
    children: list[dict],
    centroid: np.ndarray,
    n: int = 3,
) -> list[dict]:
    """Return the n children with highest cosine similarity to centroid."""
    scored: list[tuple[float, dict]] = []
    for child in children:
        vec = child.get("vec")
        if vec is None:
            continue
        cos = float(np.dot(vec, centroid))
        scored.append((cos, child))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:n]]


def _build_stitch_refs(selected: list[dict]) -> list[dict]:
    """Convert child rows to stitch_clips() ref dicts — one ref per child.

    Each child is a 3s Marengo slice of its parent. Emit refs unmerged so the
    Gemini composite is always exactly len(selected) * 3s regardless of how
    long the parent clips are. ffmpeg.input(path, ss=..., to=...) creates an
    independent input node per ref even when paths repeat — same-parent
    children do not collide in the filter graph.

    Earlier versions deduped by parent_path and merged into [min(start),
    max(end)]. That collapsed two same-parent picks into a window covering
    the FULL parent duration, so a 90s parent → 90s composite → slow Gemini
    call → 300s budget exhaustion. See .planning/debug/compile-timeout-300s.md.

    Blob mode (Phase 10): when parent_blob_url is populated and parent_path
    is None, emit the Blob URL as `path` plus the bearer-token headers so a
    downstream tempdir-download (see _resolve_caption_input_to_local) can
    fetch the source clip. Local mode is unchanged.
    """
    from urllib.parse import urlparse
    refs: list[dict] = []
    for child in selected:
        parent_blob_url = child.get("parent_blob_url")
        parent_path = child.get("parent_path")
        src: str | None = None
        ref_headers: dict[str, str] | None = None
        if parent_blob_url:
            from ..storage.blob import authorized_blob_input
            pathname = urlparse(parent_blob_url).path.lstrip("/")
            url, headers = authorized_blob_input(pathname)
            src = url
            ref_headers = headers
        elif parent_path:
            src = parent_path
        if not src:
            continue
        start = float(child.get("start_offset_sec") or 0.0)
        end = child.get("end_offset_sec")
        end = float(end) if end is not None else start + 3.0
        ref: dict = {
            "path": src,
            "start_offset_sec": start,
            "end_offset_sec": end,
        }
        if ref_headers is not None:
            ref["headers"] = ref_headers
        refs.append(ref)
    return refs


def _resolve_parents_from_children(children: list[dict]) -> list[dict]:
    """Re-derive the unique parent rows from a children-list.

    fetch_cluster_clips_with_children returns BOTH parent rows and child rows
    in one flat list (parents have parent_id=None; children carry parent_id).
    Our two-stage pipeline operates on parents only, so collapse-and-dedup by
    parent_id (or row id when parent_id is None).

    Each output row carries the keys extract_evidence_for_parent needs:
    parent_path, parent_blob_url, lat, lng, ts. Falls back to the row's own
    path / blob_url when parent_path / parent_blob_url is missing (the row
    IS the parent in that case).
    """
    by_parent: dict[str, dict] = {}
    for row in children:
        parent_id = row.get("parent_id") or row.get("id")
        if not parent_id or parent_id in by_parent:
            continue
        parent_path = row.get("parent_path") or row.get("path")
        parent_blob_url = row.get("parent_blob_url") or row.get("blob_url")
        by_parent[parent_id] = {
            "id": parent_id,
            "parent_path": parent_path,
            "parent_blob_url": parent_blob_url,
            "lat": row.get("lat"),
            "lng": row.get("lng"),
            "ts": row.get("ts"),
        }
    return list(by_parent.values())


async def generate_caption(
    cluster_id: str,
    centroid: np.ndarray,
    children: list[dict],
) -> dict | None:
    """Backward-compat shim. Routes through the two-stage evidence + intent pipeline.

    Quick task 260501-bet replaces the prior single-Gemini-call-on-stitched-
    composite pipeline with:
      Stage 1: per-parent extract_evidence_for_parent (Gemini, structured JSON)
      Stage 2: synthesize_intent (Claude, cluster-level reasoning)

    The legacy {title, caption, location, source: "vision"} contract at the
    top level is preserved verbatim so compile.py:_branch_caption + the
    discriminator at compile.py:611 keep working unchanged. New keys
    `evidence` (list[dict]) and `intent` (dict) are added so the segment
    row write at compile.py:692-701 can persist them.

    children: list of dicts as returned by fetch_cluster_clips_with_children.
              Both parent rows and child rows are present; the shim collapses
              to unique parents. centroid is now unused (the legacy
              centroid-closest selection logic was for the single-composite
              path; the two-stage pipeline runs on every parent).
    """
    # Compute location from children's GPS centroid (same fallback as legacy path).
    lats = [c["lat"] for c in children if c.get("lat") is not None]
    lngs = [c["lng"] for c in children if c.get("lng") is not None]
    if lats and lngs:
        location = await reverse_geocode(sum(lats) / len(lats), sum(lngs) / len(lngs))
    else:
        location = "Pasadena, CA"

    parents = _resolve_parents_from_children(children)
    if not parents:
        log.warning("generate_caption: no parents resolvable for cluster %s", cluster_id)
        return None

    return await run_evidence_to_intent_pipeline(cluster_id, parents, location)
