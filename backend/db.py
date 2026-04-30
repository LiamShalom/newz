"""Single backend — Neon Postgres via asyncpg.

Phase 9 originally introduced a METADATA_BACKEND dispatcher that could route
to either SQLite (legacy v1.0 path) or Postgres. Once Neon stabilized in
production, the SQLite path was retired (this commit) and the dispatcher
collapsed to a single import. METADATA_BACKEND env var is no longer read.
OFFLINE_DEMO retains its non-DB effects (pre-warm skip, Sentry skip, /media
local mode override) but no longer affects DB routing — apps with
OFFLINE_DEMO=true and no DATABASE_URL fail at pool init.
"""
from .db_postgres import *  # noqa: F401, F403
