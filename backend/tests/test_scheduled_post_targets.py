"""A schedule must only ever post to targets its own owner controls.

Every other publishing path resolves targets against the caller: the immediate
post endpoint goes through `_load_user_pages`, and Sheet sync goes through
`_resolve_targets`, both of which filter on `user_id`. The scheduled-post path
stores whatever target strings the request carried and hands the bare ids to
`_run_page_post_task`, which looks them up by primary key alone.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.crypto import encrypt
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import FacebookAccount, FacebookPage, ScheduledPost, User
from app.routers import scheduled_posts
from app.services.scheduled_post_service import enqueue_due_posts


def _session_provider(session: AsyncSession):
    @asynccontextmanager
    async def _ctx() -> AsyncGenerator[AsyncSession, None]:
        yield session

    return _ctx


async def _make_user(session: AsyncSession, name: str) -> User:
    user = User(id=uuid.uuid4(), username=name, password_hash=None)
    session.add(user)
    await session.flush()
    return user


async def _make_page(session: AsyncSession, owner: User, page_id: str) -> FacebookPage:
    account = FacebookAccount(
        id=uuid.uuid4(), user_id=owner.id, uid=f"uid-{page_id}", user_token_enc=encrypt("t"),
    )
    session.add(account)
    await session.flush()
    page = FacebookPage(
        id=uuid.uuid4(),
        user_id=owner.id,
        facebook_account_id=account.id,
        page_id=page_id,
        page_name=f"Page {page_id}",
        page_access_token_enc=encrypt(f"token-{page_id}"),
    )
    session.add(page)
    await session.flush()
    return page


async def _fire(session: AsyncSession) -> list[dict]:
    """Fire everything due, recording what reached the publisher."""
    dispatched: list[dict] = []

    # Deliberately synchronous: enqueue_due_posts builds the coroutine and hands
    # it to the task creator without awaiting it, so an async double would record
    # nothing. Recording at call time is what proves the ids were passed on.
    def fake_runner(**kwargs):
        dispatched.append(kwargs)
        return None

    import app.routers.page_tasks as page_tasks

    original = page_tasks._run_page_post_task
    page_tasks._run_page_post_task = fake_runner
    try:
        await enqueue_due_posts(
            get_session=_session_provider(session),
            create_background_task=lambda _coro: None,
        )
    finally:
        page_tasks._run_page_post_task = original
    return dispatched


@pytest.mark.asyncio
async def test_a_schedule_drops_a_page_its_owner_does_not_hold(session: AsyncSession) -> None:
    """A foreign page id in targets must never reach the publisher.

    The publisher loads pages by primary key and posts with the stored page
    token, so carrying the id through is enough to post as the victim.
    """
    victim = await _make_user(session, f"victim-{uuid.uuid4().hex[:8]}")
    attacker = await _make_user(session, f"attacker-{uuid.uuid4().hex[:8]}")
    stolen = await _make_page(session, victim, "victim-page-1")
    own = await _make_page(session, attacker, "attacker-page-1")

    session.add(ScheduledPost(
        id=uuid.uuid4(),
        user_id=attacker.id,
        name="mixed",
        action="post_page",
        targets_json=f'["page:{own.id}", "page:{stolen.id}"]',
        message="hijacked",
        max_threads=1,
        next_fire_at=datetime.now(timezone.utc),
        status="scheduled",
    ))
    await session.commit()

    dispatched = await _fire(session)

    assert dispatched, "the schedule never fired, so the test proves nothing"
    carried = [str(value) for call in dispatched for value in (call.get("page_ids") or [])]
    assert str(stolen.id) not in carried, "schedule dispatched another user's page"
    assert str(own.id) in carried, "the owner's own page must still be posted"


@pytest.mark.asyncio
async def test_a_schedule_with_only_foreign_targets_stops_instead_of_firing(
    session: AsyncSession,
) -> None:
    victim = await _make_user(session, f"victim-{uuid.uuid4().hex[:8]}")
    attacker = await _make_user(session, f"attacker-{uuid.uuid4().hex[:8]}")
    stolen = await _make_page(session, victim, "victim-page-2")

    schedule = ScheduledPost(
        id=uuid.uuid4(),
        user_id=attacker.id,
        name="stolen only",
        action="post_page",
        targets_json=f'["page:{stolen.id}"]',
        message="hijacked",
        max_threads=1,
        next_fire_at=datetime.now(timezone.utc),
        status="scheduled",
    )
    session.add(schedule)
    await session.commit()

    dispatched = await _fire(session)

    assert dispatched == []
    refreshed = (
        await session.execute(select(ScheduledPost).where(ScheduledPost.id == schedule.id))
    ).scalar_one()
    # Stopped and explained, not retried every minute forever.
    assert refreshed.status == "error"
    assert refreshed.next_fire_at is None
    assert str(stolen.id) in (refreshed.last_error or "")


@pytest.mark.asyncio
async def test_creating_a_schedule_for_a_foreign_page_is_refused(session: AsyncSession) -> None:
    victim = await _make_user(session, f"victim-{uuid.uuid4().hex[:8]}")
    attacker = await _make_user(session, f"attacker-{uuid.uuid4().hex[:8]}")
    stolen = await _make_page(session, victim, "victim-page-3")
    await session.commit()

    app.dependency_overrides[current_user] = lambda: attacker

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    original_context = scheduled_posts.session_context
    scheduled_posts.session_context = _session_provider(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/scheduled-posts", json={
                "name": "stolen",
                "targets": [f"page:{stolen.id}"],
                "message": "hijacked",
                "interval_seconds": None,
            })
            assert response.status_code == 400
            assert str(stolen.id) in response.json()["detail"]
    finally:
        scheduled_posts.session_context = original_context
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)
