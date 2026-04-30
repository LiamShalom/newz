"""backend/pipeline/moderate.py — Gemini 2.5 Flash-Lite moderation classifier (Phase 11).

Public API:
    moderate_clip(clip_id) -> ModerationResult
        Async entry point. Called from run_pipeline() at run.py:79.
        Runs Gemini classifier in parallel with embed_worker via
        asyncio.wait FIRST_COMPLETED (cancel-when-embed-finishes, D-03).

Constants:
    SYSTEM_PROMPT       — locked classifier prompt (D-12; see RESEARCH §"Recommended SYSTEM_PROMPT").
    PROMPT_VERSION      — semver string persisted on every moderation_decisions row.
    HARD_BLOCK_CATEGORIES — csam, sexual, extremist, self_harm.
    SOFT_FLAG_CATEGORIES  — hate, violence (broadened per D-08, no corroboration gating).

Per the 2026-04-29 Option-4 reconciliation, this module is classifier-only — no
Cloudflare CSAM hash dispatcher, no CSAM_PROVIDER env var, no httpx singleton.
The csam category in the locked Gemini taxonomy is the operative CSAM detection
signal; on hit, we write a reported_csam preservation row (SHA-256 of clip bytes,
1-year retention per 2024 REPORT Act) and call cleanup_blocked_clip(clip_id).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

import httpx

from .. import config, db
from ..observability.metrics import STAGE_DURATION
from ..storage import cleanup_blocked_clip

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked SYSTEM_PROMPT (RESEARCH.md § "Recommended SYSTEM_PROMPT" — verbatim)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a content moderation classifier. Your task is to evaluate a short
video clip and return a JSON object with one entry per safety category. You
do not write captions, headlines, or commentary. You do not judge whether
content is on-topic for any platform. You only assess safety categories.

Your response MUST be a JSON object with EXACTLY these six keys:
  csam, sexual, hate, extremist, violence, self_harm

Each value MUST be an object with EXACTLY three keys:
  verdict   — one of "pass", "flag", or "block"
  score     — a float between 0.0 and 1.0 indicating confidence
  rationale — a single short sentence explaining the verdict

Category definitions:
  csam       — sexual content involving minors, in any depiction. Verdict
               "block" on any signal, however slight. No exceptions.
  sexual     — adult sexual content, nudity, or sexually suggestive material
               outside of a clearly journalistic / educational context.
  hate       — content targeting a protected class with slurs, dehumanizing
               imagery, or coded extremist symbology. News-context coverage
               of hate-crime events should be marked "flag", not "block",
               since journalistic documentation is in scope for this platform.
  extremist  — content promoting, glorifying, or recruiting for terrorist,
               white-supremacist, or other violent extremist movements.
               Documenting an extremist event for journalistic purposes
               should be "flag" — promoting it should be "block".
  violence   — depictions of physical violence, injury, weapons being used
               against people. News-context (street incidents, protest
               clashes, accident aftermath) should be "flag" rather than
               "block" — the platform shows newsworthy footage with viewer
               warnings, not graphic content for shock value.
  self_harm  — depictions of suicide, self-injury, or content that
               encourages or instructs self-harm. Verdict "block" on any
               clear signal — there is no journalistic defense for showing
               this content on a public hyperlocal feed.

Verdict semantics:
  "pass"  — no signal in this category
  "flag"  — non-zero signal but not certain; or signal present but in
            news/journalistic context where a viewer warning is appropriate
  "block" — high-confidence signal warranting removal

Be conservative. When uncertain between "pass" and "flag", choose "flag".
When uncertain between "flag" and "block" for csam / sexual / extremist /
self_harm, choose "block". When uncertain between "flag" and "block" for
hate / violence, choose "flag" — the platform's downstream policy soft-
flags rather than blocks these categories, and over-blocking news content
defeats the platform's purpose.

Return ONLY the JSON object. No prose, no markdown fences, no commentary.
"""

# Bumped on prompt or category changes. Persisted via prompt_version column.
PROMPT_VERSION = "1.0.0"

USER_PROMPT = "Classify this clip per the locked taxonomy."


# ---------------------------------------------------------------------------
# Response schema (TypedDict — passed to GenerateContentConfig.response_schema)
# ---------------------------------------------------------------------------

class CategoryVerdict(TypedDict):
    verdict: Literal["pass", "flag", "block"]
    score: float
    rationale: str


class ModerationResponse(TypedDict):
    csam: CategoryVerdict
    sexual: CategoryVerdict
    hate: CategoryVerdict
    extremist: CategoryVerdict
    violence: CategoryVerdict
    self_harm: CategoryVerdict


# Ordered for verdict-routing precedence (csam first matters for the reported_csam preservation path).
HARD_BLOCK_CATEGORIES: tuple[str, ...] = ("csam", "sexual", "extremist", "self_harm")
SOFT_FLAG_CATEGORIES: tuple[str, ...] = ("hate", "violence")
ALL_CATEGORIES: tuple[str, ...] = HARD_BLOCK_CATEGORIES + SOFT_FLAG_CATEGORIES


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ModerationResult:
    decision: Literal["passed", "blocked", "unknown"]
    provider: str = "gemini_flash_lite"
    reason: str | None = None
    raw_response: dict | None = None
    latency_ms: int | None = None
    embed_result: tuple[str, Any] | None = None  # (parent_clip_id, parent_vec) when decision='passed'
    soft_flag_categories: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_hash(clip_bytes: bytes) -> str:
    """SHA-256 hex of clip bytes — used for reported_csam preservation only.

    NOT a perceptual hash. NOT a vendor-format hash. Just the standard library
    digest, mirroring observability/anonymity.session_hash style. Per the
    reconciliation, we ship classifier-only CSAM detection; the hash is the
    de-duplication fingerprint for the preservation row.
    """
    return hashlib.sha256(clip_bytes).hexdigest()


def _strip_anonymity_metadata(payload: Any) -> Any:
    """PRIV-03: ensure outbound classifier payloads carry only video bytes.

    The Gemini SDK's files.upload + generate_content paths take the file handle
    + system_instruction + user_prompt — NO session_uuid / gps / timestamp ever
    enters the request. This helper exists as a defense-in-depth for any future
    code path that might serialize a request body manually; if it sees a dict
    containing anonymity-relevant keys, it strips them.
    """
    if isinstance(payload, dict):
        return {
            k: _strip_anonymity_metadata(v)
            for k, v in payload.items()
            if k not in ("session_uuid", "gps_lat", "gps_lng", "created_at", "timestamp")
        }
    if isinstance(payload, list):
        return [_strip_anonymity_metadata(item) for item in payload]
    return payload


def _now_unix() -> float:
    return time.time()


def _one_year_from_now_unix() -> float:
    """1-year retention per 2024 REPORT Act amendment to 18 U.S.C. § 2258A (D-19)."""
    return _now_unix() + (365 * 24 * 60 * 60)


# ---------------------------------------------------------------------------
# Public entry point — moderate_clip
# ---------------------------------------------------------------------------

async def moderate_clip(clip_id: str) -> ModerationResult:
    """Phase 11 gate. Called from run_pipeline at run.py:79.

    OFFLINE_DEMO=true short-circuits to passthrough decision; one moderation_decisions
    row is written with provider='stub'. No Gemini HTTP call is attempted (MOD-10).

    Real path: SHA-256 of clip bytes → fire embed_task + gemini_task in parallel →
    asyncio.wait FIRST_COMPLETED → cancel-when-embed-finishes → route on Gemini verdict.
    """
    if config.OFFLINE_DEMO:
        # MOD-10: passthrough decision, single audit row, zero outbound traffic.
        await db.write_moderation_decision(
            clip_id=clip_id,
            provider="stub",
            decision="passed",
            reason="offline_demo",
            raw_response=None,
            latency_ms=0,
            prompt_version=None,
        )
        log.info("moderate offline_demo passthrough clip_id=%s", clip_id)
        return ModerationResult(decision="passed", provider="stub", reason="offline_demo")

    # Real path: delegate to _moderate_real (Task 2 lands the rest).
    return await _moderate_real(clip_id)


# ---------------------------------------------------------------------------
# Real classifier path
# ---------------------------------------------------------------------------

async def _fetch_clip_bytes(clip_id: str) -> tuple[bytes, str, bool]:
    """Read clip bytes once and return (bytes, local_path, is_owned_tempfile).

    Mirrors backend/pipeline/embed.py:113-152. In Blob mode the bytes are
    streamed from Vercel Blob (private, bearer-auth) into a tempfile so the
    Gemini SDK has a real fd to upload + so we can compute the SHA-256 hash.
    In local mode the row's path is read directly.

    Returns:
      clip_bytes — the full video payload (used for hashlib.sha256)
      local_path — a path on disk the caller can hand to client.files.upload(file=...)
      is_owned_tempfile — True iff the local_path is a tempfile this function
                          created (blob mode) and the caller MUST unlink at
                          end-of-task. Local-FS mode returns False — the path
                          is the canonical row.path and cleanup_blocked_clip
                          owns its lifecycle.

    WR-02: returning the ownership flag avoids a duplicate db.get_clip()
    roundtrip in _moderate_real (the caller used to fetch the row a SECOND
    time just to inspect blob_url for the same purpose).
    """
    import tempfile
    from pathlib import Path

    clip = await db.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"_fetch_clip_bytes: clip {clip_id!r} not found")

    blob_url = clip.get("blob_url")
    db_path = clip.get("path")

    if blob_url:
        # Blob mode: stream the private blob to a tempfile (we own it; caller unlinks).
        from ..storage import blob_client
        client = blob_client.get_client()
        headers = {"Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}"}
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
            async with client.stream("GET", blob_url, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    tmp.write(chunk)
        clip_bytes = Path(tmp_path).read_bytes()
        return clip_bytes, tmp_path, True

    if db_path and Path(db_path).exists():
        # Local-FS mode. We do NOT copy the file — the Gemini upload reads it
        # directly from its canonical location and we never unlink it.
        clip_bytes = Path(db_path).read_bytes()
        return clip_bytes, db_path, False

    raise FileNotFoundError(
        f"_fetch_clip_bytes: clip {clip_id!r} has no readable source "
        f"(path={db_path!r}, blob_url={'set' if blob_url else 'unset'})"
    )


async def _gemini_classify(clip_local_path: str) -> dict:
    """Gemini 2.5 Flash-Lite call: upload-poll-generate-cleanup.

    Mirrors backend/pipeline/caption_pipeline.py:424-499 with four parameter swaps:
      - model=config.GEMINI_MODERATION_MODEL
      - system_instruction=SYSTEM_PROMPT
      - response_schema=ModerationResponse (TypedDict)
      - temperature=0.0
      - inner asyncio.wait_for(..., timeout=config.MODERATION_MAX_BUDGET_S)

    Returns the parsed JSON dict (json.loads(response.text)).

    Raises:
      asyncio.TimeoutError    — wait_for ceiling exceeded
      httpx.HTTPStatusError   — Gemini control-plane 4xx / 5xx surfaced via SDK
      httpx.ConnectError      — network unreachable
      httpx.ReadError         — network read interrupted
      httpx.TransportError    — other transport failure
    Any other exception is re-raised; the caller's typed-exception ladder routes
    it into decision='unknown'.
    """
    if not config.GEMINI_API_KEY:
        # Without an API key there is no way to make the call. Surface as a
        # transport-class error so the caller routes to decision='unknown'
        # rather than 'blocked'. (The OFFLINE_DEMO short-circuit is upstream.)
        raise httpx.ConnectError("GEMINI_API_KEY unset")

    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=120_000),  # ms
    )

    loop = asyncio.get_running_loop()
    uploaded = None
    try:
        # 1. Upload (sync SDK call wrapped in executor).
        uploaded = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: client.files.upload(file=clip_local_path)),
            timeout=config.MODERATION_MAX_BUDGET_S,
        )

        # 2. Poll until ACTIVE (~30s ceiling, but capped overall by MODERATION_MAX_BUDGET_S
        #    via the surrounding asyncio.wait outer cap in _moderate_real).
        for _ in range(30):
            if uploaded.state.name == "ACTIVE":
                break
            await asyncio.sleep(1)
            uploaded = await loop.run_in_executor(
                None, lambda: client.files.get(name=uploaded.name)
            )
        if uploaded.state.name != "ACTIVE":
            raise asyncio.TimeoutError(
                f"gemini file did not reach ACTIVE state (state={uploaded.state.name})"
            )

        # 3. generate_content with system_instruction + structured JSON.
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=config.GEMINI_MODERATION_MODEL,
                    contents=[uploaded, USER_PROMPT],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=ModerationResponse,
                    ),
                ),
            ),
            timeout=config.MODERATION_MAX_BUDGET_S,
        )

        # 4. Parse JSON. Schema enforcement is server-side — but if Gemini still
        #    returns malformed JSON, json.loads raises and the caller routes to
        #    decision='unknown'.
        parsed = json.loads(response.text)
        return parsed
    finally:
        # Best-effort cleanup of the uploaded Gemini file (PRIV-03 / D-26).
        if uploaded is not None:
            try:
                await loop.run_in_executor(
                    None, lambda: client.files.delete(name=uploaded.name)
                )
            except Exception as exc:
                log.warning("gemini file cleanup failed: %s", type(exc).__name__)


def _route_verdict(parsed: dict) -> tuple[str, str | None, list[str]]:
    """Map a Gemini ModerationResponse dict → (decision, reason, soft_flag_categories).

    Precedence:
      1. Any HARD_BLOCK_CATEGORIES verdict in {flag, block} → ('blocked', f'gemini_{cat}_block', soft_flag_categories)
         csam first (for reported_csam preservation precedence).
      2. Else if SOFT_FLAG_CATEGORIES non-empty
         → ('passed', f'soft_flag_{first_cat}', soft_flag_categories).
      3. Else → ('passed', None, []).

    WR-06: soft_flag_categories is now ALWAYS populated from the parsed JSON,
    even on hard-block. Previously a CSAM-block + violence-flag verdict would
    return [] for soft_flag_categories on the in-memory ModerationResult,
    making the dataclass field inconsistent with the persisted raw_response
    JSONB (which compile.py reads to derive segments.soft_flag).
    """
    soft_flag_categories = [
        cat for cat in SOFT_FLAG_CATEGORIES
        if (parsed.get(cat) or {}).get("verdict") in ("flag", "block")
    ]

    for cat in HARD_BLOCK_CATEGORIES:
        node = parsed.get(cat) or {}
        v = node.get("verdict")
        if v in ("flag", "block"):
            return ("blocked", f"gemini_{cat}_block", soft_flag_categories)

    if soft_flag_categories:
        return ("passed", f"soft_flag_{soft_flag_categories[0]}", soft_flag_categories)

    return ("passed", None, [])


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """D-05: typed-exception → (decision, reason).

    asyncio.TimeoutError + 4xx → 'blocked'
    5xx + httpx.ConnectError + httpx.ReadError + httpx.TransportError → 'unknown'
    Anything else → 'unknown' (defense-in-depth).

    CR-03: the production Gemini path raises google.genai.errors.ClientError
    (4xx) / ServerError (5xx), NOT raw httpx.HTTPStatusError. We branch on
    the genai SDK exception types FIRST (real-prod path) and keep the httpx
    branches for forward-compat / direct-callsite tests. Both genai errors
    expose `code` (an int HTTP status) — see google/genai/errors.py.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return ("blocked", "classifier_timeout")

    # google.genai SDK errors — local import keeps this module load-safe under
    # OFFLINE_DEMO (no genai dep needed in that branch). Defensive: if the
    # SDK is somehow unavailable, fall through to the httpx ladder.
    try:
        from google.genai import errors as genai_errors  # type: ignore[import-untyped]
    except ImportError:
        genai_errors = None  # type: ignore[assignment]

    if genai_errors is not None:
        # ClientError covers 400-499 from the SDK's own error wrapping.
        # ServerError covers 500-599. Both are subclasses of APIError; we
        # check the more specific types first.
        if isinstance(exc, genai_errors.ClientError):
            status = getattr(exc, "code", 0) or 400
            return ("blocked", f"classifier_4xx_{status}")
        if isinstance(exc, genai_errors.ServerError):
            status = getattr(exc, "code", 0) or 500
            return ("unknown", f"classifier_5xx_{status}")

    if isinstance(exc, httpx.HTTPStatusError):
        # Forward-compat / direct-callsite path. Real Gemini SDK calls do NOT
        # surface raw httpx.HTTPStatusError — they are wrapped in genai.errors
        # above. Kept for tests that synthesize httpx errors directly.
        status = exc.response.status_code if exc.response is not None else 0
        if 400 <= status < 500:
            return ("blocked", f"classifier_4xx_{status}")
        if 500 <= status < 600:
            return ("unknown", f"classifier_5xx_{status}")
        return ("unknown", "classifier_network_error")
    # ConnectError / ReadError both subclass TransportError; ConnectError check first
    # is purely cosmetic. The reason string is unified.
    if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.TransportError)):
        return ("unknown", "classifier_network_error")
    return ("unknown", "classifier_unknown_error")


async def _drain_task(task: asyncio.Task) -> None:
    """Re-await a cancelled task; suppress CancelledError + downstream exceptions.

    asyncio.wait FIRST_COMPLETED leaves pending tasks alive — they MUST be
    cancelled and awaited or Python emits "Task was destroyed but it is
    pending!" warnings and may leak resources (RESEARCH § asyncio.wait).

    CR-01: do NOT swallow BaseException blanket-style — that catches
    KeyboardInterrupt / SystemExit (deliberately carved out from Exception)
    and breaks asyncio cancellation propagation when the OUTER scope is itself
    being cancelled. We propagate CancelledError when the current task is
    being cancelled by the outer scope (Python 3.11+ via cancelling()), so the
    parent's cancel reaches all the way up.
    """
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        # The drained task was cancelled (expected — we just cancelled it).
        # If WE are also being cancelled by the outer scope, propagate.
        current = asyncio.current_task()
        if current is not None and current.cancelling() > 0:
            raise
    except Exception:
        # Drained task's own non-cancel exception — swallow, the caller has
        # already inspected gemini_task.exception() / embed_task.result().
        pass


async def _moderate_real(clip_id: str) -> ModerationResult:
    """Classifier-only moderation path (D-02 reconciled).

    Sequence:
      1. Fetch clip bytes (and a local path for Gemini upload).
      2. Spawn embed_task + gemini_task in parallel.
      3. asyncio.wait FIRST_COMPLETED with outer cap = MODERATION_MAX_BUDGET_S.
      4. Branch on which finished first; cancel + drain the other.
      5. Map Gemini verdict → decision + reason.
      6. Write moderation_decisions row (always).
      7. On hard-block: csam-hit → write reported_csam BEFORE cleanup_blocked_clip
         (audit-trail ordering, T-11-16). All hard-blocks → cleanup_blocked_clip.
      8. On unknown: also call set_clip_hidden(clip_id, hidden=True) so the
         clip doesn't surface in the feed while Plan 05 short-circuits clustering.
      9. On passed: ModerationResult includes embed_result for Plan 05 to use.

    Defense-in-depth: any unhandled exception falls through to decision='unknown'.
    """
    from pathlib import Path
    from .embed import embed_worker

    t0 = time.monotonic()
    clip_bytes: bytes | None = None
    clip_local_path: str | None = None
    blob_tempfile_to_unlink: str | None = None

    try:
        # ----- Stage 1: fetch clip bytes -----
        # WR-02: _fetch_clip_bytes now returns is_owned_tempfile, so we don't
        # have to do a second db.get_clip() round-trip just to check blob_url.
        clip_bytes, clip_local_path, is_owned_tempfile = await _fetch_clip_bytes(clip_id)
        if is_owned_tempfile:
            blob_tempfile_to_unlink = clip_local_path

        # ----- Stage 2: spawn parallel tasks -----
        embed_task = asyncio.create_task(embed_worker(clip_id))
        gemini_task = asyncio.create_task(_gemini_classify(clip_local_path))

        # ----- Stage 3: race them with outer cap -----
        done, pending = await asyncio.wait(
            {embed_task, gemini_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=config.MODERATION_MAX_BUDGET_S,
        )

        decision: str
        reason: str | None
        soft_flag_categories: list[str] = []
        raw_response: dict | None = None
        embed_result: tuple[str, Any] | None = None

        # ----- Stage 4: branch on race outcome -----
        if not done:
            # Branch C — wait timed out, both still pending.
            await _drain_task(embed_task)
            await _drain_task(gemini_task)
            decision = "blocked"
            reason = "max_budget_exceeded"
            log.info(
                "moderate gate decision=%s provider=%s reason=%s latency_ms=%d",
                decision, "gemini_flash_lite", reason,
                int((time.monotonic() - t0) * 1000),
            )
        elif embed_task in done and gemini_task not in done:
            # Branch A — embed finished first; gemini still pending.
            # Cancel-when-embed-finishes (D-03) → classifier_timeout.
            try:
                embed_result = embed_task.result()
            except BaseException:
                embed_result = None
            await _drain_task(gemini_task)
            decision = "blocked"
            reason = "classifier_timeout"
        else:
            # Branch B — gemini finished first (with or without embed already done).
            # Drain embed: re-await it to get the real result if not done; if it's
            # also done, .result() / await returns immediately.
            #
            # WR-01: when embed fails (Marengo 5xx, file vanished, etc.) under
            # Branch B, surface a structured warning so ops can see the retry
            # that run_pipeline.py:124 will perform OUTSIDE the moderate stage
            # span. We don't change the decision routing — Gemini's verdict is
            # the gate, embed is a parallel cache-fill — but we DO log the
            # failure type so the metric muddling (embed retry attributed to
            # stage="embed" in run.py vs the in-gate failure under stage="moderate")
            # is at least visible.
            try:
                embed_result = await embed_task
            except asyncio.CancelledError:
                # Outer-scope cancel — propagate (mirrors CR-01 _drain_task posture).
                raise
            except Exception as exc:
                log.warning(
                    "moderate embed_worker failed under gemini-done branch clip_id=%s: %s — "
                    "run_pipeline will retry embed_worker outside moderation stage",
                    clip_id, type(exc).__name__,
                )
                embed_result = None

            # Inspect gemini outcome.
            gemini_exc = gemini_task.exception()
            if gemini_exc is not None:
                decision, reason = _classify_exception(gemini_exc)
            else:
                parsed = gemini_task.result()
                raw_response = parsed
                decision, reason, soft_flag_categories = _route_verdict(parsed)

        latency_ms = int((time.monotonic() - t0) * 1000)
        STAGE_DURATION.labels(stage="moderate").observe(latency_ms / 1000.0)

        # ----- Stage 6: persist moderation_decisions row (always) -----
        # _strip_anonymity_metadata is a defense-in-depth no-op against the
        # Gemini-shaped raw_response (it never carries session_uuid keys), but
        # we apply it before persisting so any future change to upstream
        # response shape can't leak metadata into the JSONB column.
        sanitized_raw = _strip_anonymity_metadata(raw_response) if raw_response else None
        await db.write_moderation_decision(
            clip_id=clip_id,
            provider="gemini_flash_lite",
            decision=decision,
            reason=reason,
            raw_response=sanitized_raw,
            latency_ms=latency_ms,
            prompt_version=PROMPT_VERSION,
        )

        # ----- Stage 7: hard-block side effects -----
        if decision == "blocked":
            # CR-02: § 2258A audit-trail integrity. On a CSAM hit, cleanup
            # MUST NOT run unless the reported_csam preservation write
            # succeeded — otherwise we destroy the only copy of the bytes
            # the 1-year retention obligation depends on. If the preservation
            # write fails, log loudly and leave the blob on disk for manual
            # reconciliation; a non-CSAM hard-block (sexual / extremist /
            # self_harm / classifier_timeout / max_budget_exceeded) has no
            # preservation requirement and proceeds to cleanup unconditionally.
            safe_to_cleanup = True
            if reason == "gemini_csam_block" and clip_bytes is not None:
                try:
                    await db.write_reported_csam(
                        content_hash=_content_hash(clip_bytes),
                        preserved_until=_one_year_from_now_unix(),
                    )
                except Exception:
                    log.exception(
                        "moderate write_reported_csam FAILED clip_id=%s — "
                        "preserving bytes (cleanup deferred for manual reconciliation)",
                        clip_id,
                    )
                    safe_to_cleanup = False
            # All hard-blocks (gated on preservation success for CSAM):
            # idempotent cleanup of the stored blob/file.
            if safe_to_cleanup:
                try:
                    await cleanup_blocked_clip(clip_id)
                except Exception:
                    log.exception("moderate cleanup_blocked_clip failed clip_id=%s", clip_id)

        # ----- Stage 8: unknown side effects -----
        if decision == "unknown":
            try:
                await db.set_clip_hidden(clip_id, hidden=True)
            except Exception:
                log.exception("moderate set_clip_hidden failed clip_id=%s", clip_id)

        # ----- Stage 9: structured INFO log (D-26) — never log raw_response/prompt_version (L-10) -----
        log.info(
            "moderate gate decision=%s provider=%s reason=%s latency_ms=%d",
            decision, "gemini_flash_lite", reason, latency_ms,
        )

        return ModerationResult(
            decision=decision,  # type: ignore[arg-type]
            provider="gemini_flash_lite",
            reason=reason,
            raw_response=raw_response,
            latency_ms=latency_ms,
            embed_result=embed_result if decision == "passed" else None,
            soft_flag_categories=soft_flag_categories,
        )
    except Exception:
        # Defense in depth: any unhandled error → decision='unknown' + hide clip.
        log.exception("moderate _moderate_real unhandled exception clip_id=%s", clip_id)
        latency_ms = int((time.monotonic() - t0) * 1000)
        try:
            await db.write_moderation_decision(
                clip_id=clip_id,
                provider="gemini_flash_lite",
                decision="unknown",
                reason="classifier_unknown_error",
                raw_response=None,
                latency_ms=latency_ms,
                prompt_version=PROMPT_VERSION,
            )
            await db.set_clip_hidden(clip_id, hidden=True)
        except Exception:
            log.exception("moderate fallback decision write failed clip_id=%s", clip_id)
        return ModerationResult(
            decision="unknown",
            provider="gemini_flash_lite",
            reason="classifier_unknown_error",
            latency_ms=latency_ms,
        )
    finally:
        # Only unlink tempfiles we created (blob mode). Local-mode clip_local_path
        # IS the canonical row.path — never delete that here. cleanup_blocked_clip
        # owns the canonical blob delete.
        if blob_tempfile_to_unlink:
            try:
                Path(blob_tempfile_to_unlink).unlink(missing_ok=True)
            except Exception:
                pass
