"""Phase 8 logging configuration — structlog dictConfig keystone.

configure_logging() replaces logging.basicConfig at backend/app.py:19 (Plan 08-02).
Both stdlib `logging.getLogger(__name__).info(...)` and native
`structlog.get_logger().info(...)` emit identical JSON (or console, in
LOG_FORMAT=console mode) with merged contextvars.

Bridge approach (D-01): structlog.stdlib.ProcessorFormatter feeds the existing
~70 logging.getLogger() callsites through the same pipeline as native structlog
calls — zero call-site rewrites in Phase 8.

Pitfall 2 (processor chain ordering): merge_contextvars MUST appear in BOTH
shared_processors (native side) AND foreign_pre_chain (stdlib bridge side) so
bridged logs pick up bound contextvars (D-02).

Pitfall 7: ExtraAdder() in foreign_pre_chain so `log.info("x", extra={"k": v})`
flows through to JSON output.
"""

import logging.config

import structlog

from .. import config


def configure_logging() -> None:
    """Configure stdlib logging + structlog with shared processor chain.

    Idempotent — safe to call multiple times. Should be called exactly once
    at module import of backend.observability (Plan 08-02 wires it).
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # Shared processors run on BOTH stdlib-bridged AND native-structlog log entries.
    # ORDER MATTERS — merge_contextvars must run before the renderer.
    shared_processors = [
        structlog.contextvars.merge_contextvars,           # D-02 — request_id/session_hash/clip_id
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,              # exception -> string in "exception" field
    ]

    # Renderer toggle (D-04, D-05) — read once at config time.
    renderer: object
    if config.LOG_FORMAT == "console":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    # ---- structlog side: native structlog calls flow through this chain.
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            # Terminal: hand off to the dictConfig formatter (which then runs the
            # ProcessorFormatter.processors chain below).
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ---- stdlib side: dictConfig with ProcessorFormatter as the formatter.
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,    # critical — keeps existing ~70 callsite refs alive
        "formatters": {
            "structlog": {
                "()": structlog.stdlib.ProcessorFormatter,
                # foreign_pre_chain runs on logs originating from stdlib logging
                # (i.e. the existing callsites). It mirrors shared_processors so
                # bridged events have the same shape as native structlog events.
                "foreign_pre_chain": [
                    structlog.contextvars.merge_contextvars,    # D-02; Pitfall 2
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.ExtraAdder(),              # Pitfall 7 fix
                    timestamper,
                    structlog.processors.format_exc_info,
                ],
                # processors runs on BOTH stdlib-bridged AND native-structlog events
                # after they unify into a common event_dict.
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    renderer,
                ],
            },
        },
        "handlers": {
            "default": {
                "level": "INFO",
                "class": "logging.StreamHandler",
                "formatter": "structlog",
            },
        },
        "loggers": {
            "": {
                "handlers": ["default"],
                "level": "INFO",
                "propagate": True,
            },
            # Quiet noisy third-party loggers down a notch (uvicorn.access is verbose).
            "uvicorn.access": {"level": "WARNING", "propagate": True},
        },
    })
