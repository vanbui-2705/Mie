from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, hash_password
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import User, UserStatus


async def _session_override(session: AsyncSession):
    yield session


@pytest.mark.asyncio
async def test_admin_can_create_list_update_and_delete_users(session: AsyncSession) -> None:
    admin = User(
        username="admin",
        password_hash=hash_password("adminpass"),
        role="admin",
        status=UserStatus.ACTIVE,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)

    async def override_get_session():
        async for item in _session_override(session):
            yield item

    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/auth/users",
                json={"username": "operator", "password": "secret123", "role": "user"},
            )
            assert created.status_code == 201
            created_body = created.json()
            assert created_body["username"] == "operator"
            assert created_body["role"] == "user"
            assert created_body["status"] == "active"

            listed = await client.get("/api/auth/users")
            assert listed.status_code == 200
            assert {row["username"] for row in listed.json()} == {"admin", "operator"}

            # Promoted to manager, not admin: an admin may not edit or delete a
            # peer of equal rank, so promoting to admin here would (correctly)
            # lock the rest of this flow out. See test_auth_privilege_escalation.
            updated = await client.patch(
                f"/api/auth/users/{created_body['id']}",
                json={"role": "manager", "status": "disabled", "password": "newpass123"},
            )
            assert updated.status_code == 200
            assert updated.json()["role"] == "manager"
            assert updated.json()["status"] == "disabled"

            deleted = await client.delete(f"/api/auth/users/{created_body['id']}")
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True

            listed_after_delete = await client.get("/api/auth/users")
            assert listed_after_delete.status_code == 200
            assert {row["username"] for row in listed_after_delete.json()} == {"admin"}
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_users(session: AsyncSession) -> None:
    user = User(
        username="worker",
        password_hash=hash_password("workerpass"),
        role="user",
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    async def override_get_session():
        async for item in _session_override(session):
            yield item

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/auth/users")
            assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)
