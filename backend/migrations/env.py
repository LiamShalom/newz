"""Phase 9 (D-19): Alembic async env.py — no SQLAlchemy ORM at runtime.

Reads DATABASE_URL from environment (overrides alembic.ini placeholder).
Rewrites the URL prefix from postgres:// or postgresql:// to postgresql+asyncpg://
because SQLAlchemy 2.x requires the explicit driver suffix (RESEARCH Pitfall 4).

SQLAlchemy 2.x's asyncpg dialect does NOT translate libpq-style URL query
params (`sslmode`, `channel_binding`) — it forwards them as kwargs to
asyncpg.connect(), which rejects them with TypeError. So we strip both
from the URL and translate `sslmode` into a connect_args["ssl"] kwarg.
The runtime pool in db_postgres.py uses asyncpg.create_pool(dsn=...)
directly and asyncpg parses sslmode natively, so it's not affected.

Hand-written migrations use op.execute() raw SQL — no ORM models, no autogenerate.
target_metadata=None disables autogenerate.
"""
import asyncio
import os
import ssl
from logging.config import fileConfig
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the alembic.ini placeholder with the runtime DATABASE_URL.
db_url = os.environ.get("DATABASE_URL", "")
if not db_url:
    raise RuntimeError(
        "DATABASE_URL is empty — Alembic migrations require a live Neon connection string"
    )

# Strip libpq-style query params SQLAlchemy's asyncpg dialect can't translate.
# Capture sslmode so we can map it to connect_args["ssl"] below.
_parsed = urlparse(db_url)
_query = dict(parse_qsl(_parsed.query))
_sslmode = _query.pop("sslmode", None)
_query.pop("channel_binding", None)  # asyncpg has no parameter for this
db_url = urlunparse(_parsed._replace(query=urlencode(_query)))

# Pitfall 4: SQLAlchemy 2.x demands postgresql+asyncpg:// prefix.
db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
if not db_url.startswith("postgresql+asyncpg://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
config.set_main_option("sqlalchemy.url", db_url)

# Build connect_args for SQLAlchemy → asyncpg. Neon enforces TLS server-side;
# `sslmode=require` maps to a default SSL context. `disable` short-circuits
# to ssl=False; `verify-ca`/`verify-full` use the default verifying context.
_connect_args: dict = {}
if _sslmode in ("require", "verify-ca", "verify-full"):
    _connect_args["ssl"] = ssl.create_default_context()
elif _sslmode == "disable":
    _connect_args["ssl"] = False

# No ORM models → no autogenerate. Hand-write migrations with op.execute() raw SQL.
target_metadata = None


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # one-shot; preDeployCommand container is short-lived
        connect_args=_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    # Critical: dispose the engine cleanly (RESEARCH Anti-Patterns line 440).
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise RuntimeError(
        "Offline mode disabled — Phase 9 migrations always run against live Neon "
        "via Railway preDeployCommand"
    )
else:
    run_migrations_online()
