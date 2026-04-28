"""Phase 8 Sentry initialization — gated on SENTRY_DSN (D-16).

Empty SENTRY_DSN -> early-return BEFORE any sentry_sdk import, so OFFLINE_DEMO
startup makes zero outbound network calls (Pitfall 5).

Locked kwargs (D-13):
  - sample_rate=1.0          (capture all errors at hackathon scale)
  - traces_sample_rate=0.0   (Logfire owns spans in Phase 13; OBS-08 audit gate)
  - send_default_pii=False
  - max_request_body_size="never"
  - before_send=before_send_scrub  (D-14 recursive PII scrubber)
"""

import logging

from .. import config


def init_sentry() -> None:
    """Initialize Sentry if SENTRY_DSN is set; otherwise no-op (D-16).

    Called once at module import of backend.observability. Safe under
    OFFLINE_DEMO=true (skips entirely; zero outbound calls).
    """
    if not config.SENTRY_DSN:
        logging.getLogger(__name__).info("sentry skipped: SENTRY_DSN unset")
        return
    import sentry_sdk
    from .anonymity import before_send_scrub
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.SENTRY_ENVIRONMENT or "production",
        sample_rate=1.0,                       # D-13
        traces_sample_rate=0.0,                # D-13 — Logfire owns spans (Phase 13)
        send_default_pii=False,                # D-13
        max_request_body_size="never",         # D-13
        before_send=before_send_scrub,         # D-14 — recursive PII scrubber
        # FastApiIntegration auto-installs (D-15: sentry-sdk[fastapi])
    )
    logging.getLogger(__name__).info("sentry initialized")
