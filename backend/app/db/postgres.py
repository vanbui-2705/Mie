"""Async PostgreSQL engine and session factory using SQLAlchemy 2.0 async."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.config import settings

_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _async_session_factory


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency — yields an async DB session per-request."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_context() -> AsyncGenerator[AsyncSession]:
    """Async context manager for lifespan/background tasks."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """Create all ORM-mapped tables (for dev / first-run bootstrap)."""
    from app.models.sqlmodels import Base

    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE facebook_accounts "
            "ADD COLUMN IF NOT EXISTS browser_status VARCHAR(32) NOT NULL DEFAULT 'not_configured'"
        ))
        await conn.execute(text(
            "ALTER TABLE facebook_accounts "
            "ADD COLUMN IF NOT EXISTS browser_last_checked_at TIMESTAMP WITH TIME ZONE NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE facebook_accounts "
            "ADD COLUMN IF NOT EXISTS browser_last_error TEXT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE share_targets "
            "ADD COLUMN IF NOT EXISTS target_type VARCHAR(32) NOT NULL DEFAULT 'page'"
        ))
        await conn.execute(text(
            "ALTER TABLE share_targets "
            "ALTER COLUMN facebook_page_id DROP NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE share_targets "
            "ADD COLUMN IF NOT EXISTS facebook_group_id UUID NULL REFERENCES facebook_groups(id) ON DELETE CASCADE"
        ))
        await conn.execute(text(
            "ALTER TABLE share_targets "
            "ADD COLUMN IF NOT EXISTS external_page_id UUID NULL REFERENCES external_pages(id) ON DELETE CASCADE"
        ))
        await conn.execute(text(
            "ALTER TABLE share_targets "
            "ADD COLUMN IF NOT EXISTS facebook_account_id UUID NULL REFERENCES facebook_accounts(id) ON DELETE CASCADE"
        ))
        await conn.execute(text(
            "ALTER TABLE task_logs "
            "ALTER COLUMN action TYPE VARCHAR(32)"
        ))
        await conn.execute(text(
            "ALTER TABLE task_items "
            "ALTER COLUMN status TYPE VARCHAR(32)"
        ))
        await conn.execute(text(
            "ALTER TABLE task_items "
            "ALTER COLUMN action TYPE VARCHAR(32)"
        ))


async def close_db() -> None:
    """Dispose engine — call on shutdown."""
    global _engine, _async_session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
