"""
database.py — SQLAlchemy async engine + session factory.

Driver: psycopg (v3) instead of asyncpg.
Reason: asyncpg has SSL handshake issues on Windows with Neon's
channel_binding=require. psycopg handles it correctly.

EVENT LOOP NOTE:
  psycopg requires SelectorEventLoop on Windows.
  This is set in main.py before uvicorn starts.
  Do not use ProactorEventLoop (Windows default) with psycopg.

ENGINE vs SESSION:
  - engine: one pool of open connections, lives for the app's lifetime
  - session: one unit of work, opened per repository call, closed after
"""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


# ── Engine ─────────────────────────────────────────────────────────────────────
# DATABASE_URL in .env uses postgresql+psycopg:// scheme.
# psycopg handles sslmode=require and channel_binding=require natively
# via the URL query parameters — no extra connect_args needed.

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size     = 5,
    max_overflow  = 5,
    pool_pre_ping = True,
    echo          = False,
)


# ── Session factory ────────────────────────────────────────────────────────────

async_session_factory = async_sessionmaker(
    engine,
    class_           = AsyncSession,
    expire_on_commit = False,
)


# ── Session context manager ────────────────────────────────────────────────────

@asynccontextmanager
async def get_db_session():
    """
    Usage:
        async with get_db_session() as session:
            result = await session.execute(...)

    Auto-commits on success, auto-rolls back on error, always closes.
    """
    session: AsyncSession = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ── Health check ───────────────────────────────────────────────────────────────

async def check_db_connection() -> bool:
    """Called once on startup to verify Neon is reachable."""
    from sqlalchemy import text
    async with get_db_session() as session:
        result = await session.execute(text("SELECT 1"))
        return result.scalar() == 1