"""Changing a password must end the sessions that password opened.

Tokens are stateless HMAC blobs valid for a week, so before `token_version`
existed a stolen token outlived the one thing a victim can actually do about
it. "Change your password" was advice that changed nothing.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, hash_password
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import User, UserStatus


async def _login(client: AsyncClient, username: str, password: str) -> str:
    response = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_a_password_reset_kills_the_tokens_issued_before_it(
    session: AsyncSession, monkeypatch
) -> None:
    async def override_get_session():
        yield session

    monkeypatch.setattr("app.routers.auth.settings.EXPOSE_PASSWORD_RESET_TOKEN", True)
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/auth/register",
                json={"email": "victim@example.com", "username": "victim", "password": "original-pass"},
            )
            stolen = await _login(client, "victim", "original-pass")
            alive = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {stolen}"})
            assert alive.status_code == 200

            forgot = await client.post("/api/auth/forgot-password", json={"email": "victim@example.com"})
            reset_token = forgot.json()["reset_url"].split("token=", 1)[1]
            reset = await client.post(
                "/api/auth/reset-password", json={"token": reset_token, "password": "brand-new-pass"}
            )
            assert reset.status_code == 200

            dead = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {stolen}"})
            assert dead.status_code == 401

            # The new password still works, and its token is accepted.
            fresh = await _login(client, "victim", "brand-new-pass")
            assert (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {fresh}"})).status_code == 200
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_an_admin_password_change_kicks_the_account_out(session: AsyncSession) -> None:
    """Resetting a compromised user's password is a containment action."""
    admin = User(username="admin", password_hash=hash_password("admin-pass"), role="admin", status=UserStatus.ACTIVE)
    session.add(admin)
    await session.commit()
    await session.refresh(admin)

    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/auth/register",
                json={"email": "worker@example.com", "username": "worker", "password": "worker-pass"},
            )
            token = await _login(client, "worker", "worker-pass")
            worker = (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).json()

            app.dependency_overrides[current_user] = lambda: admin
            changed = await client.patch(
                f"/api/auth/users/{worker['id']}", json={"password": "reset-by-admin"}
            )
            assert changed.status_code == 200
            app.dependency_overrides.pop(current_user, None)

            dead = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert dead.status_code == 401
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)
