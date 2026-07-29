"""FastAPI authorization dependencies."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, current_user_media
from app.db.postgres import get_session
from app.models.sqlmodels import User
from app.services.permission_service import permission_codes_for_user


def require_permission(code: str) -> Callable:
    async def dependency(
        user: User = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        permissions = await permission_codes_for_user(session, user)
        if code not in permissions:
            raise HTTPException(status_code=403, detail=f"Missing permission: {code}")
        return user

    return dependency


def require_permission_media(code: str) -> Callable:
    """`require_permission` for endpoints a media tag loads directly.

    Only differs in where the token may come from — see `current_user_media`.
    """
    async def dependency(
        user: User = Depends(current_user_media),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        permissions = await permission_codes_for_user(session, user)
        if code not in permissions:
            raise HTTPException(status_code=403, detail=f"Missing permission: {code}")
        return user

    return dependency


def require_any_permission(*codes: str) -> Callable:
    async def dependency(
        user: User = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        permissions = await permission_codes_for_user(session, user)
        if not permissions.intersection(codes):
            raise HTTPException(status_code=403, detail=f"Missing one of permissions: {', '.join(codes)}")
        return user

    return dependency


async def has_permission(session: AsyncSession, user: User, code: str) -> bool:
    return code in await permission_codes_for_user(session, user)
