"""Phase 8: observability scaffolding. Imported FIRST in backend/app.py.

Module-import side effects (run once on first import):
  - configure_logging()  — replaces logging.basicConfig with structlog dictConfig
  - init_sentry()        — gated on SENTRY_DSN; no-op when empty (D-16)

Plan 08-02 wires `from . import observability` at the top of backend/app.py
BEFORE `from . import config, db, events` so all subsequent log lines are JSON
(Pitfall 6 — logger init order bug).
"""

from .logging_config import configure_logging
from .sentry import init_sentry

configure_logging()
init_sentry()
