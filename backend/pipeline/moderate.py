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
# Real path — Task 2 fills in
# ---------------------------------------------------------------------------

async def _moderate_real(clip_id: str) -> ModerationResult:
    """Real classifier path. Replaced fully by Task 2 — currently a placeholder."""
    raise NotImplementedError("filled in by Task 2")
