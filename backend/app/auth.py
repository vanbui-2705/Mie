"""Authentication helpers — token issuance, validation, and user resolution."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.postgres import get_session
from app.models.sqlmodels import User, UserStatus

logger = logging.getLogger(__name__)

DEFAULT_USERNAME = settings.FLOWMETA_DEFAULT_USER
TOKEN_SECRET = settings.FLOWMETA_TOKEN_SECRET or settings.FERNET_KEY or "dev-secret"

if TOKEN_SECRET == "dev-secret":  # pragma: no cover - startup guard
    logger.warning(
        "FLOWMETA_TOKEN_SECRET is not set; signing tokens with the built-in dev secret. "
        "Set it before running anything but a local dev box."
    )


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


def create_token(user_id: uuid.UUID, token_version: int = 0) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    payload = f"{user_id}.{exp}.{int(token_version)}"
    sig = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def parse_token(token: str) -> tuple[uuid.UUID, int] | None:
    """Return `(user_id, token_version)`, or None if the token is not usable.

    Tokens minted before `token_version` existed carry three parts instead of
    four and are rejected outright: accepting them as version 0 would hand
    every pre-upgrade session a permanent exemption from revocation. The cost
    is one forced re-login at deploy.
    """
    try:
        user_id, exp_raw, version_raw, sig = token.split(".", 3)
        payload = f"{user_id}.{exp_raw}.{version_raw}"
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp_raw) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return uuid.UUID(user_id), int(version_raw)
    except Exception:
        return None


def revoke_sessions(user: User) -> None:
    """Invalidate every token already issued for this account.

    Call it wherever the credentials change. The caller commits.
    """
    user.token_version = (user.token_version or 0) + 1


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


async def _load_user_by_id(
    session: AsyncSession, user_id: uuid.UUID, token_version: int
) -> User | None:
    result = await session.execute(
        select(User).where(User.id == user_id, User.status == UserStatus.ACTIVE)
    )
    user = result.scalar_one_or_none()
    if user is None or (user.token_version or 0) != token_version:
        return None
    return user


async def current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = auth_header[7:]
    claims = parse_token(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await _load_user_by_id(session, *claims)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    return user


async def current_user_media(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Same check as `current_user`, but a `?token=` query parameter is accepted.

    A `<video src>` tag cannot set an Authorization header, so media endpoints
    need the token in the URL — the same concession `/api/events/stream` already
    makes. Kept separate from `current_user` so no other endpoint starts
    accepting tokens from the query string, where they end up in access logs.
    """
    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token is required")
    claims = parse_token(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await _load_user_by_id(session, *claims)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    return user


async def optional_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    claims = parse_token(auth_header[7:])
    if claims is None:
        return None
    return await _load_user_by_id(session, *claims)
