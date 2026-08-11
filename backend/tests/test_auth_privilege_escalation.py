"""An administrator must not be able to seize an account that outranks them.

`user:update` used to be enough to set *anyone's* password, super_admin
included: an admin could overwrite the owner's password, log in as them and
inherit `tenant:manage:any`. Deleting or demoting the owner was open the same
way. These tests pin the rank guard that closes all three doors.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, hash_password
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import User, UserStatus


async def _make(session: AsyncSession, username: str, role: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password("original-pass"),
        role=role,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_admin_cannot_take_over_a_super_admin(session: AsyncSession) -> None:
    admin = await _make(session, "admin", "admin")
    owner = await _make(session, "owner", "super_admin")

    async def override_get_session():
        yield session

    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            reset = await client.patch(f"/api/auth/users/{owner.id}", json={"password": "stolen-pass"})
            assert reset.status_code == 403

            demote = await client.patch(f"/api/auth/users/{owner.id}", json={"role": "user"})
            assert demote.status_code == 403

            disable = await client.patch(f"/api/auth/users/{owner.id}", json={"status": "disabled"})
            assert disable.status_code == 403

            removed = await client.delete(f"/api/auth/users/{owner.id}")
            assert removed.status_code == 403

            # The owner's credentials are untouched by all of that.
            await session.refresh(owner)
            assert owner.role == "super_admin"
            assert owner.status is UserStatus.ACTIVE
            login = await client.post(
                "/api/auth/login", json={"username": "owner", "password": "original-pass"}
            )
            assert login.status_code == 200
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_an_admin_cannot_take_over_another_admin(session: AsyncSession) -> None:
    """Equal rank is a takeover too: same permissions, different person."""
    admin = await _make(session, "admin", "admin")
    peer = await _make(session, "peer", "admin")

    async def override_get_session():
        yield session

    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(f"/api/auth/users/{peer.id}", json={"password": "stolen-pass"})
            assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_an_admin_cannot_mint_an_account_above_their_own_rank(session: AsyncSession) -> None:
    admin = await _make(session, "admin", "admin")

    async def override_get_session():
        yield session

    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/auth/users",
                json={"username": "shadow", "password": "secret123", "role": "super_admin"},
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_an_admin_still_manages_everyone_below_them(session: AsyncSession) -> None:
    """The guard must not turn into a lockout: ranks below stay manageable."""
    admin = await _make(session, "admin", "admin")
    staff = await _make(session, "staff", "manager")

    async def override_get_session():
        yield session

    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            updated = await client.patch(
                f"/api/auth/users/{staff.id}", json={"role": "admin", "password": "new-pass-123"}
            )
            assert updated.status_code == 200
            assert updated.json()["role"] == "admin"
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)
