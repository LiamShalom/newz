"""Phase 9 (D-08): METADATA_BACKEND dispatcher — module-import-time selection.

OFFLINE_DEMO=true hard-overrides to SQLite regardless of METADATA_BACKEND (D-11).
Mirrors backend/observability/sentry.py:25 graceful-skip pattern (empty env var
short-circuits to safe default).

Per-request branching is FORBIDDEN (D-08 / RESEARCH Anti-Patterns). The if/elif
below runs once at import; downstream callers see exactly one function table.
"""
import logging

from . import config

log = logging.getLogger(__name__)

if config.METADATA_BACKEND == "postgres" and not config.OFFLINE_DEMO:
    from .db_postgres import *  # noqa: F401, F403
    log.info("metadata_backend=postgres")
elif config.METADATA_BACKEND == "postgres" and config.OFFLINE_DEMO:
    from .db_sqlite import *  # noqa: F401, F403
    log.info("metadata_backend=sqlite (forced by OFFLINE_DEMO=true; D-11)")
else:
    from .db_sqlite import *  # noqa: F401, F403
    log.info("metadata_backend=sqlite")
