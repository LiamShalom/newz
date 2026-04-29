"""Phase 10 (D-12, D-13, D-18): STORAGE_BACKEND dispatcher — module-import-time selection.

OFFLINE_DEMO=true hard-overrides to local regardless of STORAGE_BACKEND (D-18).
Mirrors backend/db.py:1-24 verbatim — same three-arm shape.

Per-request branching is FORBIDDEN (D-13 / PATTERNS Anti-Patterns). The if/elif
below runs once at import; downstream callers see exactly one function table.
"""
import logging

from .. import config

log = logging.getLogger(__name__)

if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
    from .blob import *  # noqa: F401, F403
    log.info("storage_backend=blob")
elif config.STORAGE_BACKEND == "blob" and config.OFFLINE_DEMO:
    from .local import *  # noqa: F401, F403
    log.info("storage_backend=local (forced by OFFLINE_DEMO=true; D-18)")
else:
    from .local import *  # noqa: F401, F403
    log.info("storage_backend=local")
