"""Authentication endpoints."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_token, current_user, get_or_create_default_user, hash_password, verify_password
from app.db.postgres import get_session
from app.config import settings
from app.models.sqlmodels import PasswordResetToken, Role, User, UserRole, UserStatus
from app.rbac import has_permission, require_permission
from app.services.permission_service import permission_codes_for_user, role_codes_for_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me", response_model=dict)
async def me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "roles": sorted(await role_codes_for_user(session, user)),
        "permissions": sorted(await permission_codes_for_user(session, user)),
        "status": user.status.value,
    }


def _user_response(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "status": user.status.value if hasattr(user.status, "value") else str(user.status),
        "created_at": user.created_at,
        "has_password": bool(user.password_hash),
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


@router.get("/bootstrap/status", response_model=dict)
async def bootstrap_status(session: AsyncSession = Depends(get_session)):
    user = await get_or_create_default_user(session)
    return {"configured": bool(user.password_hash), "username": user.username}


@router.post("/login", response_model=dict)
async def login(body: dict, session: AsyncSession = Depends(get_session)):
    username = str(body.get("username") or body.get("email") or "").strip()
    if "@" in username:
        username = username.lower()
    password = str(body.get("password") or "")
    result = await session.execute(select(User).where((User.username == username) | (User.email == username)))
    user = result.scalar_one_or_none()
    if user is not None and not user.password_hash:
        raise HTTPException(status_code=409, detail="Admin password is not configured")
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="User account is disabled")
    return {
        "access_token": create_token(user.id),
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
        },
    }


@router.post("/register", response_model=dict, status_code=201)
async def register(body: dict, session: AsyncSession = Depends(get_session)):
    email = str(body.get("email") or "").strip().lower()
    username = str(body.get("username") or email.split("@", 1)[0]).strip()
    full_name = str(body.get("full_name") or "").strip() or None
    password = str(body.get("password") or "")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Email không hợp lệ")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Tên đăng nhập phải có ít nhất 3 ký tự")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có ít nhất 8 ký tự")
    existing = (await session.execute(
        select(User).where((User.username == username) | (User.email == email))
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email hoặc tên đăng nhập đã tồn tại")
    user = User(username=username, email=email, full_name=full_name, password_hash=hash_password(password), role="user", status=UserStatus.ACTIVE)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email hoặc tên đăng nhập đã tồn tại") from None
    await session.refresh(user)
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": _user_response(user)}


@router.post("/forgot-password", response_model=dict)
async def forgot_password(body: dict, session: AsyncSession = Depends(get_session)):
    email = str(body.get("email") or "").strip().lower()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    response = {"message": "If the email exists, a reset link has been created."}
    if user is None:
        return response
    raw_token = secrets.token_urlsafe(32)
    item = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    session.add(item)
    await session.commit()
    # Development-only escape hatch until an email transport is configured.
    if settings.EXPOSE_PASSWORD_RESET_TOKEN:
        response["reset_url"] = f"{settings.PASSWORD_RESET_URL}?token={raw_token}"
    return response


@router.post("/reset-password", response_model=dict)
async def reset_password(body: dict, session: AsyncSession = Depends(get_session)):
    token = str(body.get("token") or "")
    password = str(body.get("password") or "")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    item = (await session.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    expires_at = item.expires_at.replace(tzinfo=timezone.utc) if item is not None and item.expires_at.tzinfo is None else (item.expires_at if item is not None else now)
    if item is None or item.used_at is not None or expires_at < now:
        raise HTTPException(status_code=400, detail="Reset token is invalid or expired")
    user = await session.get(User, item.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Reset token is invalid")
    user.password_hash = hash_password(password)
    item.used_at = now
    await session.commit()
    return {"reset": True}


@router.get("/users", response_model=list[dict])
async def list_users(
    user: User = Depends(require_permission("user:read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    return [_user_response(row) for row in result.scalars().all()]


@router.post("/users", response_model=dict, status_code=201)
async def create_user(
    body: dict,
    user: User = Depends(require_permission("user:create")),
    session: AsyncSession = Depends(get_session),
):
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    role = str(body.get("role") or "user").strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="password must be at least 6 characters")
    if role not in {"super_admin", "admin", "manager", "staff", "user"}:
        raise HTTPException(status_code=400, detail="Unknown role")
    if role != "user" and not await has_permission(session, user, "permission:assign"):
        raise HTTPException(status_code=403, detail="Missing permission: permission:assign")
    if role == "super_admin" and not await has_permission(session, user, "tenant:manage:any"):
        raise HTTPException(status_code=403, detail="Only a super administrator can assign super_admin")
    existing = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="username already exists")
    item = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        status=UserStatus.ACTIVE,
    )
    session.add(item)
    await session.flush()
    role_row = (await session.execute(select(Role).where(Role.name == role))).scalar_one_or_none()
    if role_row is not None:
        session.add(UserRole(user_id=item.id, role_id=role_row.id, assigned_by_user_id=user.id))
    await session.commit()
    await session.refresh(item)
    return _user_response(item)


@router.patch("/users/{user_id}", response_model=dict)
async def update_user(
    user_id: str,
    body: dict,
    user: User = Depends(require_permission("user:update")),
    session: AsyncSession = Depends(get_session),
):
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id") from None
    item = await session.get(User, user_uuid)
    if item is None:
        raise HTTPException(status_code=404, detail="User not found")
    role = body.get("role")
    status = body.get("status")
    password = body.get("password")
    if role is not None:
        role_value = str(role).strip().lower()
        if role_value not in {"super_admin", "admin", "manager", "staff", "user"}:
            raise HTTPException(status_code=400, detail="Unknown role")
        if not await has_permission(session, user, "permission:assign"):
            raise HTTPException(status_code=403, detail="Missing permission: permission:assign")
        if role_value == "super_admin" and not await has_permission(session, user, "tenant:manage:any"):
            raise HTTPException(status_code=403, detail="Only a super administrator can assign super_admin")
        item.role = role_value
    if status is not None:
        status_value = str(status).strip().lower()
        if status_value not in {UserStatus.ACTIVE.value, UserStatus.DISABLED.value}:
            raise HTTPException(status_code=400, detail="status must be active or disabled")
        if str(item.id) == str(user.id) and status_value == UserStatus.DISABLED.value:
            raise HTTPException(status_code=400, detail="cannot disable current user")
        item.status = UserStatus(status_value)
    if password is not None and str(password):
        if len(str(password)) < 6:
            raise HTTPException(status_code=400, detail="password must be at least 6 characters")
        item.password_hash = hash_password(str(password))
    await session.commit()
    await session.refresh(item)
    return _user_response(item)


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: str,
    user: User = Depends(require_permission("user:delete")),
    session: AsyncSession = Depends(get_session),
):
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id") from None
    if str(user_uuid) == str(user.id):
        raise HTTPException(status_code=400, detail="cannot delete current user")
    item = await session.get(User, user_uuid)
    if item is None:
        raise HTTPException(status_code=404, detail="User not found")
    await session.delete(item)
    await session.commit()
    return {"deleted": True, "id": str(user_uuid)}
