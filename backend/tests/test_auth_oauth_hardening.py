"""OAuth sign-in must not hand an account to whoever claimed the email first.

Registration never verified an email address, and the callback linked a
provider identity to any account carrying the same one. So an attacker could
register victim@example.com, wait for the real owner to sign in with Google,
and keep a working password on the account they now share.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import User
from app.routers import auth_oauth


@pytest.fixture
def _callback_url(monkeypatch):
    monkeypatch.setattr(
        "app.routers.auth_oauth.settings.AUTH_FRONTEND_CALLBACK_URL",
        "http://localhost:3001/auth/callback",
    )


async def _start_and_callback(client: AsyncClient, identity: dict, monkeypatch) -> object:
    async def fake_identity(provider: str, code: str) -> dict:
        return identity

    monkeypatch.setattr("app.routers.auth_oauth._fetch_identity", fake_identity)
    started = await client.get("/api/auth/oauth/google/start", follow_redirects=False)
    state = started.headers["location"].split("state=", 1)[1].split("&", 1)[0]
    return await client.get(
        "/api/auth/oauth/google/callback", params={"code": "valid-code", "state": state}
    )


@pytest.mark.asyncio
async def test_signing_in_with_a_verified_email_evicts_the_squatter(
    session: AsyncSession, monkeypatch, _callback_url
) -> None:
    """Google proves who owns the mailbox. The stale password loses."""

    async def override_get_session():
        yield session

    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_GOOGLE_CLIENT_ID", "google-id")
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            squatted = await client.post(
                "/api/auth/register",
                json={"email": "victim@example.com", "username": "victim", "password": "squatter-pass"},
            )
            assert squatted.status_code == 201

            response = await _start_and_callback(
                client,
                {
                    "id": "google-victim",
                    "email": "victim@example.com",
                    "email_verified": True,
                    "name": "Victim",
                    "picture": None,
                },
                monkeypatch,
            )
            assert response.status_code == 307
            assert "#token=" in response.headers["location"]

            # The password the squatter set no longer opens the account, and
            # the token they were holding is dead.
            stale = await client.post(
                "/api/auth/login", json={"username": "victim", "password": "squatter-pass"}
            )
            assert stale.status_code in (401, 409)
            user = (
                await session.execute(select(User).where(User.email == "victim@example.com"))
            ).scalar_one()
            assert user.password_hash is None
            assert user.token_version > 0
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_an_unverified_provider_email_links_to_nothing(
    session: AsyncSession, monkeypatch, _callback_url
) -> None:
    """Without a verified email the provider is only asserting a string."""

    async def override_get_session():
        yield session

    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_GOOGLE_CLIENT_ID", "google-id")
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/auth/register",
                json={"email": "owner@example.com", "username": "owner", "password": "owner-pass"},
            )
            response = await _start_and_callback(
                client,
                {
                    "id": "google-imposter",
                    "email": "owner@example.com",
                    "email_verified": False,
                    "name": "Imposter",
                    "picture": None,
                },
                monkeypatch,
            )
            assert response.status_code == 307
            assert "oauth_error=" in response.headers["location"]

            user = (
                await session.execute(select(User).where(User.email == "owner@example.com"))
            ).scalar_one()
            assert user.password_hash is not None
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_a_state_from_someone_elses_browser_is_refused(
    session: AsyncSession, monkeypatch, _callback_url
) -> None:
    """A signed state alone proves nothing about who is finishing the flow."""

    async def override_get_session():
        yield session

    async def fake_identity(provider: str, code: str) -> dict:
        return {"id": "google-1", "email": "drive@example.com", "email_verified": True, "name": "D"}

    monkeypatch.setattr("app.routers.auth_oauth._fetch_identity", fake_identity)
    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_GOOGLE_CLIENT_ID", "google-id")
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as attacker:
            started = await attacker.get("/api/auth/oauth/google/start", follow_redirects=False)
            stolen_state = started.headers["location"].split("state=", 1)[1].split("&", 1)[0]

        # A different browser: valid signature, but it never began this flow.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as victim:
            response = await victim.get(
                "/api/auth/oauth/google/callback",
                params={"code": "valid-code", "state": stolen_state},
            )
            assert response.status_code == 307
            assert "oauth_error=" in response.headers["location"]
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_the_state_cookie_is_single_use(
    session: AsyncSession, monkeypatch, _callback_url
) -> None:
    async def override_get_session():
        yield session

    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_GOOGLE_CLIENT_ID", "google-id")
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            identity = {
                "id": "google-replay",
                "email": "replay@example.com",
                "email_verified": True,
                "name": "Replay",
            }

            async def fake_identity(provider: str, code: str) -> dict:
                return identity

            monkeypatch.setattr("app.routers.auth_oauth._fetch_identity", fake_identity)
            started = await client.get("/api/auth/oauth/google/start", follow_redirects=False)
            state = started.headers["location"].split("state=", 1)[1].split("&", 1)[0]

            first = await client.get(
                "/api/auth/oauth/google/callback", params={"code": "valid-code", "state": state}
            )
            assert "#token=" in first.headers["location"]

            replayed = await client.get(
                "/api/auth/oauth/google/callback", params={"code": "valid-code", "state": state}
            )
            assert "oauth_error=" in replayed.headers["location"]
    finally:
        app.dependency_overrides.pop(get_session, None)
