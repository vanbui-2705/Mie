"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_token, current_user, get_or_create_default_user, hash_password, verify_password
from app.db.postgres import get_session
from app.models.sqlmodels import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me", response_model=dict)
async def me(user: User = Depends(current_user)):
    return {
        "id": str(user.id),
        "username": user.username,
        "role": user.role,
        "status": user.status.value,
    }


@router.post("/bootstrap", response_model=dict)
async def bootstrap_admin(body: dict, session: AsyncSession = Depends(get_session)):
    user = await get_or_create_default_user(session)
    password = str(body.get("password") or "")
    if not password:
        raise HTTPException(status_code=400, detail="password is required")
    if user.password_hash:
        raise HTTPException(status_code=409, detail="Admin password already configured")
    user.password_hash = hash_password(password)
    await session.commit()
    return {"configured": True}


@router.post("/login", response_model=dict)
async def login(body: dict, session: AsyncSession = Depends(get_session)):
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {
        "access_token": create_token(user.id),
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
        },
    }
