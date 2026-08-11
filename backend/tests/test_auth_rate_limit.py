"""Guessing a password must get slower, not stay free.

Nothing throttled `/api/auth/login` before this, so an 8-character password
was worth exactly as much as the attacker's bandwidth. The same hole let
anyone mint accounts or spray password-reset mail in a loop.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session
from app.main import app
from app.services import rate_limit


@pytest.fixture(autouse=True)
def _clean_limiter():
    rate_limit.reset_local_state()
    yield
    rate_limit.reset_local_state()


@pytest.mark.asyncio
async def test_repeated_bad_passwords_start_getting_429(session: AsyncSession, monkeypatch) -> None:
    async def override_get_session():
        yield session

    monkeypatch.setattr(rate_limit.settings, "AUTH_LOGIN_MAX_ATTEMPTS", 3)
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/auth/register",
                json={"email": "target@example.com", "username": "target", "password": "correct-pass"},
            )
            for _ in range(3):
                wrong = await client.post(
                    "/api/auth/login", json={"username": "target", "password": "wrong-pass"}
                )
                assert wrong.status_code == 401

            blocked = await client.post(
                "/api/auth/login", json={"username": "target", "password": "wrong-pass"}
            )
            assert blocked.status_code == 429
            assert blocked.headers.get("retry-after")

            # The real password is refused too — otherwise the throttle is a
            # hint that tells the attacker when they have guessed right.
            correct = await client.post(
                "/api/auth/login", json={"username": "target", "password": "correct-pass"}
            )
            assert correct.status_code == 429
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_a_successful_login_clears_the_counter(session: AsyncSession, monkeypatch) -> None:
    async def override_get_session():
        yield session

    monkeypatch.setattr(rate_limit.settings, "AUTH_LOGIN_MAX_ATTEMPTS", 3)
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/auth/register",
                json={"email": "typo@example.com", "username": "typo", "password": "correct-pass"},
            )
            for _ in range(2):
                await client.post("/api/auth/login", json={"username": "typo", "password": "wrong-pass"})
            good = await client.post(
                "/api/auth/login", json={"username": "typo", "password": "correct-pass"}
            )
            assert good.status_code == 200

            # Two fumbled attempts before remembering the password must not
            # leave the account one mistake away from being locked out.
            for _ in range(3):
                again = await client.post(
                    "/api/auth/login", json={"username": "typo", "password": "wrong-pass"}
                )
                assert again.status_code == 401
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_registration_is_throttled_per_client(session: AsyncSession, monkeypatch) -> None:
    async def override_get_session():
        yield session

    monkeypatch.setattr(rate_limit.settings, "AUTH_SIGNUP_MAX_ATTEMPTS", 2)
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for index in range(2):
                created = await client.post(
                    "/api/auth/register",
                    json={
                        "email": f"bulk{index}@example.com",
                        "username": f"bulk{index}",
                        "password": "bulk-pass-123",
                    },
                )
                assert created.status_code == 201
            blocked = await client.post(
                "/api/auth/register",
                json={"email": "bulk9@example.com", "username": "bulk9", "password": "bulk-pass-123"},
            )
            assert blocked.status_code == 429
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_the_limiter_survives_redis_being_down(monkeypatch) -> None:
    """A broken cache must fail closed onto the in-process counter, not open."""

    async def explode():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(rate_limit, "get_redis", explode)
    for _ in range(2):
        await rate_limit.check_rate_limit("probe", limit=2, window_sec=60)
    with pytest.raises(rate_limit.RateLimited):
        await rate_limit.check_rate_limit("probe", limit=2, window_sec=60)
