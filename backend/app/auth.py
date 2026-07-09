"""Minimal auth helpers for multi-user APIs.

For the current migration stage, requests without an Authorization header are
assigned to a default admin user. This keeps the existing single-user UI usable
while new data is stored with user_id from day one.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session
from app.models.sqlmodels import User, UserStatus


DEFAULT_USERNAME = os.environ.get("FLOWMETA_DEFAULT_USER", "admin")
TOKEN_SECRET = os.environ.get("FLOWMETA_TOKEN_SECRET") or os.environ.get("FERNET_KEY") or "dev-secret"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, salt, digest = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
        return hmac.compare_digest(check, digest)
    except Exception:
        return False


def create_token(user_id: uuid.UUID) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    payload = f"{user_id}.{exp}"
    sig = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def parse_token(token: str) -> uuid.UUID | None:
    try:
        user_id, exp_raw, sig = token.split(".", 2)
        payload = f"{user_id}.{exp_raw}"
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp_raw) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return uuid.UUID(user_id)
    except Exception:
        return None


async def get_or_create_default_user(session: AsyncSession) -> User:
    result = await session.execute(select(User).where(User.username == DEFAULT_USERNAME))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(username=DEFAULT_USERNAME, role="admin", status=UserStatus.ACTIVE)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if authorization and authorization.lower().startswith("bearer "):
        token_user_id = parse_token(authorization[7:].strip())
        if token_user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await session.get(User, token_user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise HTTPException(status_code=401, detail="User disabled or not found")
        return user
    return await get_or_create_default_user(session)
