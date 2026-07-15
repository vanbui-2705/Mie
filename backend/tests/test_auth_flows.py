from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session
from app.main import app
from app.routers.auth_oauth import _state


@pytest.mark.asyncio
async def test_register_login_and_password_reset(session: AsyncSession, monkeypatch) -> None:
    async def override_session():
        yield session

    monkeypatch.setattr("app.routers.auth.settings.EXPOSE_PASSWORD_RESET_TOKEN", True)
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registered = await client.post("/api/auth/register", json={"email": "new@example.com", "username": "newuser", "full_name": "New User", "password": "secret123"})
            assert registered.status_code == 201
            login = await client.post("/api/auth/login", json={"username": "NEW@EXAMPLE.COM", "password": "secret123"})
            assert login.status_code == 200
            duplicate = await client.post("/api/auth/register", json={"email": "new@example.com", "username": "another", "password": "secret123"})
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"] == "Email hoặc tên đăng nhập đã tồn tại"
            forgot = await client.post("/api/auth/forgot-password", json={"email": "new@example.com"})
            token = forgot.json()["reset_url"].split("token=", 1)[1]
            reset = await client.post("/api/auth/reset-password", json={"token": token, "password": "changed123"})
            assert reset.status_code == 200
            login_again = await client.post("/api/auth/login", json={"username": "newuser", "password": "changed123"})
            assert login_again.status_code == 200
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_oauth_status_and_callback_errors_return_to_login(session: AsyncSession, monkeypatch) -> None:
    async def override_session():
        yield session

    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_GOOGLE_CLIENT_ID", "google-id")
    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_FACEBOOK_APP_ID", "")
    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_FACEBOOK_APP_SECRET", "")
    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_FRONTEND_CALLBACK_URL", "http://localhost:3001/auth/callback")
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            status = await client.get("/api/auth/oauth/status/providers")
            assert status.status_code == 200
            assert status.json() == {"google": True, "facebook": False}

            canceled = await client.get("/api/auth/oauth/google/callback", params={"error": "access_denied"})
            assert canceled.status_code == 307
            assert "oauth_error=" in canceled.headers["location"]

            invalid_state = await client.get("/api/auth/oauth/google/callback", params={"code": "code", "state": "invalid"})
            assert invalid_state.status_code == 307
            assert invalid_state.headers["location"].startswith("http://localhost:3001/login?")
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_oauth_success_creates_session_redirect(session: AsyncSession, monkeypatch) -> None:
    async def override_session():
        yield session

    async def fake_identity(provider: str, code: str) -> dict:
        assert provider == "google"
        assert code == "valid-code"
        return {"id": "google-user-1", "email": "oauth@example.com", "name": "OAuth User", "picture": None}

    monkeypatch.setattr("app.routers.auth_oauth._fetch_identity", fake_identity)
    monkeypatch.setattr("app.routers.auth_oauth.settings.AUTH_FRONTEND_CALLBACK_URL", "http://localhost:3001/auth/callback")
    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/auth/oauth/google/callback", params={"code": "valid-code", "state": _state("google")})
            assert response.status_code == 307
            assert response.headers["location"].startswith("http://localhost:3001/auth/callback#token=")
            assert "&user=" in response.headers["location"]
    finally:
        app.dependency_overrides.pop(get_session, None)
