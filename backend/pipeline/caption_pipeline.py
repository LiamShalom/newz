"""
backend/pipeline/caption_pipeline.py — Gemini 2.5 Flash native-video caption pipeline.

Public API:
    generate_caption(cluster_id, centroid, children) -> dict | None
        Async. Steps:
          1. Pick the 3 children clips closest to the cluster centroid by cosine.
          2. ffmpeg-stitch them into one short composite mp4.
          3. Upload to Gemini Files API; poll until ACTIVE.
          4. Call gemini-2.5-flash with system prompt + JSON response_schema.
          5. Parse + return {"title", "caption", "location", "source": "gemini"}.
          6. Cleanup: delete uploaded Gemini file + temp stitch on disk.

        Returns None on any failure (caller falls back to a generic caption).

Replaces the prior Anthropic Haiku-per-child + Sonnet-synthesis pipeline.
Single LLM call vs. four; native video reasoning (audio + motion + temporal continuity)
vs. still frames + text aggregation. Strictly higher quality at equivalent latency.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import config
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
GOOD EXAMPLES (study the title-vs-caption split)
==============================
{"title": "Hacktech Letters Light Up Caltech",
 "caption": "Glowing white 'HACKTECH' signage lines a red-brick walkway after dusk, illuminating a small group of students walking past. Faint chatter and the steady hum of a portable generator carry through the warm evening air. A blue tarp sits folded near the curb.",
 "location": "Pasadena, CA"}

{"title": "Crowd Gathers At Caltech South Gate",
 "caption": "Roughly thirty people stand shoulder-to-shoulder near the entrance, several holding handmade cardboard signs. A bullhorn cuts in and out audibly, and a single bicycle leans against the gate post. Sky is overcast; daylight is fading.",
 "location": "Pasadena, CA"}

{"title": "Recycling Bins Topple On Lake Avenue",
 "caption": "A row of blue municipal bins lies overturned along the curb on Lake Avenue at first light. Loose paper and a torn cardboard box drift across the asphalt as a sedan passes by. No people are in the immediate vicinity; bird calls are audible.",
 "location": "Pasadena, CA"}

{"title": "Resident Paces In Pasadena Home",
 "caption": "A man in a dark hoodie walks between two rooms inside a residence, hand briefly touching the wall. A low fan hum is constant, punctuated by a single door creak. The lighting is dim and yellow-tinged, suggesting late evening indoors.",
 "location": "Pasadena, CA"}

==============================
BAD EXAMPLES (do NOT imitate)
==============================
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
rewrite that field. Do not emit JSON until all four pass:
  (a) Title word count is between 4 and 8 (count the words).
  (b) Title contains NONE of: video, clip, footage, frame, frames, camera,
      shot, filmed, recording, sequence.
  (c) Title and caption do NOT share more than 3 consecutive words.
  (d) Caption mentions at least TWO specific details (audio cue, color, count,
      object, action verb, weather, lighting, clothing) that are NOT in the title.
  (e) Caption is between 2 and 3 sentences and reaches at least 80 characters.
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


async def generate_caption(
    cluster_id: str,
    centroid: np.ndarray,
    children: list[dict],
) -> dict | None:
    """Run the full Gemini caption track. Returns dict on success, None on failure.

    children: list of dicts, each with keys: id, parent_path, start_offset_sec,
              end_offset_sec, lat, lng, ts, vec (np.ndarray or None).
    centroid: parent-scope cluster centroid (unit vector).
    """
    location = "Pasadena, CA"  # cluster reverse-geocode is a Phase 5 follow-up

    if not config.GEMINI_API_KEY:
        log.warning("generate_caption: GEMINI_API_KEY not set — skipping Gemini track")
        return None

    selected = _select_caption_children(children, centroid, n=3)
    if not selected:
        log.warning("generate_caption: no children with vectors for cluster %s", cluster_id)
        return None

    stitch_refs = _build_stitch_refs(selected)
    if not stitch_refs:
        log.warning("generate_caption: no stitchable refs for cluster %s", cluster_id)
        return None

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    composite_path = config.DATA_DIR / "clips" / f"{cluster_id}_caption_input.mp4"
    composite_path.parent.mkdir(parents=True, exist_ok=True)

    # Phase 10: Blob-mode refs carry HTTPS URLs that ffmpeg's `_sync_stitch`
    # can't ingest directly (private blobs require Authorization headers, and
    # the sync path doesn't pass them). Pre-download to a tempdir and rewrite
    # refs to local paths before calling stitch_clips. Local-mode refs pass
    # through unchanged. Mirrors compile.py:_download_refs_to_tempdir; kept
    # local here to avoid the compile↔caption_pipeline import cycle.
    needs_download = any(r["path"].startswith("http") for r in stitch_refs)
    import tempfile
    tmpdir_ctx = tempfile.TemporaryDirectory() if needs_download else None
    try:
        if needs_download and tmpdir_ctx is not None:
            from ..storage import blob_client
            tmpdir = tmpdir_ctx.name

            async def _dl_one(ref: dict, idx: int) -> dict:
                src_url = ref["path"]
                if not src_url.startswith("http"):
                    return ref
                local = f"{tmpdir}/cap-src-{idx}.mp4"
                client = blob_client.get_client()
                headers = ref.get("headers") or {}
                async with client.stream("GET", src_url, headers=headers) as resp:
                    resp.raise_for_status()
                    with open(local, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                            f.write(chunk)
                return {**ref, "path": local, "headers": None}

            stitch_refs = await asyncio.gather(
                *[_dl_one(r, i) for i, r in enumerate(stitch_refs)]
            )

        try:
            stitched = await stitch_clips(stitch_refs, str(composite_path))
            # CRITICAL: stitch_clips returns clip_refs[0]["path"] (a SOURCE FILE) on failure.
            # We must only proceed when stitched == composite_path; otherwise our finally
            # block would unlink the user's original recording. See the data-loss bug
            # documented in the cleanup section below.
            if stitched != str(composite_path) or not Path(composite_path).exists():
                log.warning(
                    "generate_caption: stitch did not produce composite at %s (got %r) — skipping Gemini",
                    composite_path, stitched,
                )
                return None
        except Exception:
            log.exception("generate_caption: stitch failed for cluster %s", cluster_id)
            return None
    finally:
        if tmpdir_ctx is not None:
            tmpdir_ctx.cleanup()

    ts = selected[0].get("ts")
    when_iso = (
        datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %-d, %Y")
        if ts else
        datetime.now(tz=timezone.utc).strftime("%b %-d, %Y")
    )

    user_prompt = (
        f"Date: {when_iso}\n"
        f"Location: {location}\n\n"
        f"Write the title, caption, and location for this footage. "
        f"Use the location string above verbatim."
    )

    try:
        from google import genai
        from google.genai import types

        # Set a transport-layer HTTP timeout on the client so a slow Gemini call
        # actually aborts the underlying request, not just the asyncio future.
        # Without this, asyncio.wait_for cancels the future but the executor
        # thread keeps blocking on the socket until the SDK default (>>300s)
        # eventually returns. See .planning/debug/compile-timeout-300s.md.
        client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=120_000),  # ms
        )

        # 1. Upload (sync SDK call wrapped in executor)
        loop = asyncio.get_running_loop()
        uploaded = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: client.files.upload(file=stitched)),
            timeout=30.0,
        )

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
                "generate_caption: file did not reach ACTIVE state cluster_id=%s state=%s",
                cluster_id, uploaded.state.name,
            )
            return None

        # 3. Generate content with system prompt + structured JSON.
        # Inner asyncio.wait_for is belt-and-suspenders alongside the SDK's
        # HttpOptions(timeout=120_000) — if HTTP doesn't abort, asyncio at
        # least surfaces the failure in time for the outer 300s budget.
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=config.GEMINI_MODEL,
                    contents=[uploaded, user_prompt],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        response_mime_type="application/json",
                        response_schema=RESPONSE_SCHEMA,
                    ),
                ),
            ),
            timeout=125.0,
        )

        # 4. Parse + Layer 2 sanitize (forbidden words, length cap, dup detection)
        parsed = json.loads(response.text)
        if not all(k in parsed for k in ("title", "caption", "location")):
            log.warning("generate_caption: missing required keys in JSON: %s", parsed)
            return None
        parsed = _sanitize_output(parsed, location)

        log.info(
            "generate_caption ok cluster_id=%s title=%r caption_len=%d",
            cluster_id, parsed.get("title"), len(parsed.get("caption", "")),
        )

        # 5. Cleanup uploaded file (best-effort)
        try:
            await loop.run_in_executor(None, lambda: client.files.delete(name=uploaded.name))
        except Exception as e:
            log.warning("generate_caption: file cleanup failed: %s", e)

        # NOTE: must be "vision" (not "gemini") to satisfy compile.py's discriminator
        # at line 404 — `if b_result.get("source") == "vision"`. Backward-compat
        # with the prior Anthropic-based pipeline that used the same gate.
        return {**parsed, "source": "vision"}

    except Exception:
        log.exception("generate_caption: Gemini call failed cluster_id=%s", cluster_id)
        return None
    finally:
        # Remove ONLY the composite we wrote — never `stitched`, which could be a
        # fallback to a user's source recording (stitch_clips returns clip_refs[0]
        # ["path"] on failure). Deleting that path destroys their original upload.
        try:
            composite_path.unlink(missing_ok=True)
        except Exception:
            pass
