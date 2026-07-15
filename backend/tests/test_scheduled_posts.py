from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import ScheduledPost, TaskRun, User
from app.routers import scheduled_posts
from app.services.scheduled_post_service import ScheduledPostService, enqueue_due_posts


def _session_provider(session: AsyncSession):
    @asynccontextmanager
    async def _ctx() -> AsyncGenerator[AsyncSession, None]:
        yield session

    return _ctx


def _service(session: AsyncSession) -> ScheduledPostService:
    return ScheduledPostService(get_session=_session_provider(session))


async def _ensure_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    result = await session.execute(select(User).where(User.id == user_id))
    if result.scalar_one_or_none() is None:
        session.add(User(id=user_id, username=f"test-{user_id.hex[:8]}", password_hash=None))
        await session.commit()


@pytest.mark.asyncio
async def test_create_future_schedule_is_scheduled_not_paused(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _ensure_user(session, user_id)
    start = datetime.now(timezone.utc) + timedelta(hours=1)

    item = await _service(session).create(
        user_id=user_id,
        name="Future post",
        action="post_page",
        targets=["page:abc"],
        message="hello",
        link=None,
        media_paths=[],
        max_threads=3,
        start_at=start,
        interval_seconds=3600,
        stop_at=None,
    )

    assert item.status == "scheduled"
    assert item.next_fire_at is not None
    assert item.next_fire_at.replace(tzinfo=timezone.utc) == start


@pytest.mark.asyncio
async def test_pause_resume_and_list_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _ensure_user(session, user_id)
    item = await _service(session).create(
        user_id=user_id,
        name="Daily",
        action="post_page",
        targets=["page:abc"],
        message="hello",
        link="https://example.test",
        media_paths=[],
        max_threads=2,
        start_at=None,
        interval_seconds=86400,
        stop_at=None,
    )

    paused = await _service(session).set_status(item.id, user_id, "paused")
    assert paused.status == "paused"
    assert paused.next_fire_at is None

    resumed = await _service(session).set_status(item.id, user_id, "scheduled")
    assert resumed.status == "scheduled"
    assert resumed.next_fire_at is not None

    rows = await _service(session).list_for_user(user_id)
    assert [row.id for row in rows] == [item.id]


@pytest.mark.asyncio
async def test_enqueue_due_posts_creates_task_run_without_running_real_job(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _ensure_user(session, user_id)
    now = datetime.now(timezone.utc)
    item = ScheduledPost(
        user_id=user_id,
        name="Due",
        action="post_page",
        targets_json='["page:abc"]',
        message="hello",
        max_threads=3,
        status="scheduled",
        next_fire_at=now - timedelta(seconds=1),
        interval_seconds=None,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    fired = await enqueue_due_posts(
        now=now,
        get_session=_session_provider(session),
        create_background_task=lambda coro: coro.close(),
    )

    assert fired[0]["scheduled_post_id"] == str(item.id)
    run = await session.get(TaskRun, uuid.UUID(fired[0]["run_id"]))
    assert run is not None
    await session.refresh(item)
    assert item.status == "completed"
    assert item.next_fire_at is None


@pytest.mark.asyncio
async def test_enqueue_due_posts_cycles_post_items(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _ensure_user(session, user_id)
    now = datetime.now(timezone.utc)
    item = await _service(session).create(
        user_id=user_id,
        name="Rotating posts",
        action="post_page",
        targets=["page:abc"],
        message="first",
        link=None,
        media_paths=[],
        max_threads=3,
        start_at=now - timedelta(seconds=1),
        interval_seconds=60,
        stop_at=None,
        post_items=[
            {"message": "first", "link": "", "media_paths": ["/tmp/first.jpg"]},
            {"message": "second", "link": "https://example.test/2", "media_paths": ["/tmp/second.jpg"]},
        ],
    )

    fired_first = await enqueue_due_posts(
        now=now + timedelta(seconds=2),
        get_session=_session_provider(session),
        create_background_task=lambda coro: coro.close(),
    )
    first_run = await session.get(TaskRun, uuid.UUID(fired_first[0]["run_id"]))
    await session.refresh(item)

    fired_second = await enqueue_due_posts(
        now=now + timedelta(seconds=63),
        get_session=_session_provider(session),
        create_background_task=lambda coro: coro.close(),
    )
    second_run = await session.get(TaskRun, uuid.UUID(fired_second[0]["run_id"]))
    await session.refresh(item)

    assert fired_first[0]["post_item_index"] == 0
    assert fired_second[0]["post_item_index"] == 1
    assert first_run is not None
    assert second_run is not None
    assert first_run.text_input_enc == "first"
    assert second_run.text_input_enc == "second"
    assert item.next_item_index == 0


@pytest.mark.asyncio
async def test_scheduled_posts_routes_exist(session: AsyncSession, user_id: uuid.UUID) -> None:
    await _ensure_user(session, user_id)
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    app.dependency_overrides[current_user] = lambda: user
    async def override_get_session():
        yield session
    app.dependency_overrides[get_session] = override_get_session
    original_session_context = scheduled_posts.session_context
    scheduled_posts.session_context = _session_provider(session)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "name": "Route smoke",
                "targets": ["page:abc"],
                "post_items": [
                    {"message": "hello", "link": ""},
                    {"message": "hello 2", "link": "https://example.test"},
                ],
                "interval_seconds": None,
            }
            created = await client.post("/api/scheduled-posts", json=payload)
            assert created.status_code == 201
            sp_id = created.json()["id"]
            assert created.json()["post_count"] == 2

            listed = await client.get("/api/scheduled-posts")
            assert listed.status_code == 200
            assert any(row["id"] == sp_id for row in listed.json())

            paused = await client.post(f"/api/scheduled-posts/{sp_id}/pause")
            assert paused.status_code == 200

            deleted = await client.delete(f"/api/scheduled-posts/{sp_id}")
            assert deleted.status_code == 200
    finally:
        scheduled_posts.session_context = original_session_context
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)
