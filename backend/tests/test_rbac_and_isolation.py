from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db.postgres import get_session
from app.event_bus import EventBus
from app.main import app
from app.models.sqlmodels import Role, ScheduledPost, User, UserRole, UserStatus
from app.services.permission_service import permission_codes_for_user
from app.services.rbac_seed import seed_rbac
from app.services.scheduled_post_service import ScheduledPostNotFound, ScheduledPostService


@pytest.mark.asyncio
async def test_rbac_user_has_own_permissions_but_not_cross_tenant(session: AsyncSession) -> None:
    owner = User(username="rbac-owner", role="admin", status=UserStatus.ACTIVE)
    user = User(username="rbac-user", role="user", status=UserStatus.ACTIVE)
    session.add_all([owner, user])
    await session.flush()
    await seed_rbac(session)
    await session.flush()

    owner_permissions = await permission_codes_for_user(session, owner)
    user_permissions = await permission_codes_for_user(session, user)
    assert "tenant:read:any" in owner_permissions
    assert "facebook_account:read" in user_permissions
    assert "facebook_account:read:any" not in user_permissions


@pytest.mark.asyncio
async def test_explicit_empty_role_does_not_fall_back_to_legacy_permissions(session: AsyncSession) -> None:
    user = User(username="restricted-user", role="user", status=UserStatus.ACTIVE)
    role = Role(name="restricted", display_name="Restricted", is_system=False)
    session.add_all([user, role])
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()

    assert await permission_codes_for_user(session, user) == set()

    async def override_get_session():
        yield session

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/tasks")
        assert response.status_code == 403
        assert response.json()["detail"] == "Missing permission: task:read"
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_scheduled_post_cannot_be_read_by_another_user(session: AsyncSession) -> None:
    user_a = User(username="tenant-a", role="user", status=UserStatus.ACTIVE)
    user_b = User(username="tenant-b", role="user", status=UserStatus.ACTIVE)
    session.add_all([user_a, user_b])
    await session.flush()
    post = ScheduledPost(user_id=user_a.id, name="Private schedule", max_threads=1)
    session.add(post)
    await session.flush()
    service = ScheduledPostService(get_session=_session_context(session))

    with pytest.raises(ScheduledPostNotFound):
        await service.get_for_user(post.id, user_b.id)


@pytest.mark.asyncio
async def test_event_bus_only_delivers_matching_user_events() -> None:
    bus = EventBus()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    stream = bus.subscribe("log", user_id=user_a)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await bus.publish("log", "log", {"user_id": str(user_b), "message": "secret-b"})
    await bus.publish("log", "log", {"user_id": str(user_a), "message": "visible-a"})
    _, _, payload = await asyncio.wait_for(pending, timeout=1)
    assert payload["message"] == "visible-a"
    await stream.aclose()


def _session_context(session: AsyncSession):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def context():
        yield session

    return context
