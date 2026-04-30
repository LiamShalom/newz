"""Phase 8 anonymity helpers — pure functions, no state.

Provides:
  - session_hash(uuid: str) -> str — D-06: constant sha256 of session UUID.
  - before_send_scrub(event, hint) -> dict — D-14: Sentry before_send hook
    that recursively redacts REDACT_KEYS from the event dict.

D-07 note: this hash is intentionally NOT HMAC'd. session_hash lives only in
append-only logs and must remain constant across days for cross-day debugging
correlation. The Phase 12 REPORT-03 reporter_ip_hash uses daily-rotated HMAC
because it lives in the long-lived `reports` DB table — different threat model,
different anonymity window. Do NOT re-litigate this in Phase 12.
"""

import hashlib
from typing import Any

# D-14 — extend list one-liner-cheap; Phase 11/12 will append e.g. "ip", "raw_address".
REDACT_KEYS: frozenset[str] = frozenset({
    "session_uuid",
    "gps_lat",
    "gps_lng",
    "blob_url",
    # Phase 11 (D-27 reconciled): classifier raw response + prompt version may surface
    # in error contexts (Gemini 4xx/5xx with reflected payload). Redact at the Sentry
    # boundary; primary sink is the moderation_decisions.raw_response JSONB column.
    "raw_response",
    "prompt_version",
})
REDACTED = "[REDACTED]"


def session_hash(session_uuid: str) -> str:
    """D-06: constant sha256 of session UUID. Pure function, no key, no rotation.
    Same input -> same output forever. Used in log contextvars only (PRIV-02).
    """
    return hashlib.sha256(session_uuid.encode("utf-8")).hexdigest()


def _scrub(obj: Any) -> Any:
    """Recursively redact REDACT_KEYS from dict/list values.

    Returns a new structure (does not mutate in place during iteration — Pitfall 8).
    Leaves scalars unchanged. Handles dict, list, tuple, set; passes through everything else.
    """
    if isinstance(obj, dict):
        return {
            k: REDACTED if k in REDACT_KEYS else _scrub(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_scrub(item) for item in obj)
    if isinstance(obj, set):
        return {_scrub(item) for item in obj}
    return obj


def before_send_scrub(event: dict, hint: dict) -> dict:
    """Sentry before_send hook (D-14): walk the event dict and redact PII keys.

    Returning the event (possibly modified) lets it through; returning None drops it.
    We always return — we never want to drop legitimate errors.
    """
    return _scrub(event)
