"""Anonymous comment content filter — Phase 01 (feature track).

Stub-grade: profanity blocklist (whole-word, case-insensitive) + URL/spam regex.
Wins now; iterate later. The Phase 11 backbone moderation gate covers video,
not text — comments are unlikely to ever route through that pipeline.

Design note: this is policy-light deliberately. Anonymous comments + heavy
moderation = a different product. Keep filters narrow enough that real users
don't get blocked; widen only if abuse data shows up.
"""
import re

# Word-prefix profanity match (catches inflections: fucking, shitty, retarded).
# Pilot list — extend with abuse data, accept some over-match for now.
_PROFANITY_RE = re.compile(
    r"\b(?:fuck|shit|bitch|cunt|nigger|faggot|retard)\w*",
    re.IGNORECASE,
)

# Crude URL/domain match — comments shouldn't be a link-spam vector.
_URL_RE = re.compile(
    r"(?:https?://|www\.|\b\w[\w-]*\.(?:com|net|org|io|co|ru|cn|biz|info|xyz|me|app|dev|ai)\b)",
    re.IGNORECASE,
)

# Repetition spam: ≥6 of the same character in a row, e.g. "aaaaaa".
_REPEAT_RE = re.compile(r"(.)\1{5,}")


class FilterResult:
    __slots__ = ("blocked", "reason")

    def __init__(self, blocked: bool, reason: str = ""):
        self.blocked = blocked
        self.reason = reason

    def __repr__(self) -> str:
        return f"FilterResult(blocked={self.blocked}, reason={self.reason!r})"


def check(text: str) -> FilterResult:
    if _PROFANITY_RE.search(text):
        return FilterResult(True, "profanity")
    if _URL_RE.search(text):
        return FilterResult(True, "links not allowed")
    if _REPEAT_RE.search(text):
        return FilterResult(True, "repetitive content")
    return FilterResult(False)
