"""Shared pytest fixtures for FlowMeta backend tests."""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import JSON, String
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.postgres import close_db
from app.models.sqlmodels import Base, User, FacebookAccount, FacebookGroup
from app.models.clip_models import ClipJob, Clip, ClipEdit
from sqlalchemy.dialects.postgresql import CITEXT, JSONB

# Use SQLite for tests to avoid needing a running PostgreSQL
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    # Swap Postgres-specific column types so SQLite can create the tables
    original_types: list[tuple] = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, CITEXT):
                original_types.append((col, col.type))
                col.type = String()
            elif isinstance(col.type, JSONB):
                original_types.append((col, col.type))
                # Generic JSON, not Text: SQLite's driver cannot bind a raw dict,
                # and JSONB columns (e.g. clip_jobs.params) hold dicts.
                col.type = JSON()

    try:
        async with engine.begin() as conn:
            from app.models.sqlmodels import (
        OAuthAccount, PasswordResetToken, Permission, Role, RolePermission,
                GoogleSheetConnection, SheetCampaign, SheetSourceItem, ScheduledPost, TaskRun, TaskItem, TaskLog, UserRole,
        FacebookAccount, FacebookGroup, ExternalPage, FacebookPage,
                RentalConfig, RentalRoom, PublicationJob, RentalSheetMirrorJob, SheetWritebackJob,
            )
            for tbl in (
        User, Role, Permission, RolePermission, UserRole,
                GoogleSheetConnection, SheetCampaign, SheetSourceItem, ScheduledPost, TaskRun, TaskItem, TaskLog, OAuthAccount, PasswordResetToken,
                FacebookAccount, FacebookGroup, ExternalPage, FacebookPage,
                RentalConfig, RentalRoom, PublicationJob, RentalSheetMirrorJob, SheetWritebackJob,
                ClipJob, Clip, ClipEdit,
            ):
                await conn.run_sync(tbl.__table__.create, checkfirst=True)

        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise
    finally:
        for col, typ in original_types:
            col.type = typ
        try:
            await engine.dispose()
        except RuntimeError:
            pass


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def _ensure_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    from sqlalchemy import select
    result = await session.execute(select(User).where(User.id == user_id))
    if result.scalar_one_or_none() is None:
        session.add(User(id=user_id, username=f"test-{user_id.hex[:8]}", password_hash=None))
        await session.flush()


@pytest.fixture
def session_factory(session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _factory():
        yield session

    return _factory
