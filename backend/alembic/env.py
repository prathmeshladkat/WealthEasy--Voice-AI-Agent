"""
alembic/env.py — tells Alembic how to connect to the database and
where to find our models.

Two things we changed from the auto-generated default:
  1. Read DATABASE_URL from our .env via app.config instead of
     the hardcoded sqlalchemy.url in alembic.ini
  2. Point target_metadata at our Base so autogenerate can compare
     models.py against the real database and write the SQL diff
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Import our app's config and models ────────────────────────────────────────
# This is the critical part — without these two imports:
#   - config: Alembic wouldn't know our DATABASE_URL
#   - Base:   Alembic wouldn't know what tables to generate SQL for
from app.config import settings
from app.models import Base   # noqa: F401 — imported so all models register on Base

# Alembic's own config object (reads alembic.ini)
config = context.config

# Override the sqlalchemy.url from alembic.ini with our real URL from .env
# This means we never hardcode the DB URL in alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up logging as configured in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what autogenerate reads to know what tables should exist.
# Because we imported Base above (which has all 5 models registered),
# Alembic can compare Base.metadata against the real database.
target_metadata = Base.metadata


# ── Offline mode ──────────────────────────────────────────────────────────────
# "Offline" = generate SQL to a file without connecting to the DB.
# We won't use this in day-to-day work but Alembic requires it to exist.

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────────────────
# "Online" = connect to the real DB and apply migrations.
# This is what actually runs when you do `alembic upgrade head`.
#
# Our engine is async (asyncpg driver) but Alembic's migration runner
# is synchronous. The do_run_migrations + run_async_migrations pattern
# bridges that gap: we create an async engine, get a sync connection
# from it, and hand that to Alembic's sync runner.

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # no pool needed for one-off migration runs
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()