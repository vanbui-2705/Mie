"""Authentication endpoints."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_token,
    current_user,
    get_or_create_default_user,
    hash_password,
    revoke_sessions,
    verify_password,
)
from app.db.postgres import get_session
from app.config import settings
from app.models.sqlmodels import PasswordResetToken, Role, User, UserRole, UserStatus
from app.rbac import has_permission, require_permission
from app.rbac_catalog import role_rank
from app.services.permission_service import permission_codes_for_user, role_codes_for_user
from app.services.rate_limit import check_rate_limit, clear_rate_limit, client_key

router = APIRouter(prefix="/api/auth", tags=["auth"])

ASSIGNABLE_ROLES = {"super_admin", "admin", "manager", "staff", "user"}

# One rule for every path that sets a password. The admin endpoints used to
# accept 6 characters while self-service registration demanded 8, so the
# weakest password on the system was always the one an admin typed.
MIN_PASSWORD_LENGTH = 8


def _guard_target_rank(actor: User, target: User) -> None:
    """Refuse to touch an account that ranks at or above the caller's own.

    `user:update` is permission to administer users, not permission to become
    one of them. Equal rank counts as a takeover as well: two admins hold the
    same powers, so letting either overwrite the other's password just moves
    the account between people.
    """
    if str(actor.id) == str(target.id):
        return
    if role_rank(target.role) >= role_rank(actor.role):
        raise HTTPException(
            status_code=403,
            detail="Không thể thao tác trên tài khoản ngang hoặc cao quyền hơn bạn",
        )


def _guard_assigned_rank(actor: User, role: str) -> None:
    """No one hands out a role stronger than the one they hold."""
    if role_rank(role) > role_rank(actor.role):
        raise HTTPException(
            status_code=403,
            detail="Không thể gán vai trò cao hơn vai trò của bạn",
        )


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
async def bootstrap_admin(
    request: Request, body: dict, session: AsyncSession = Depends(get_session)
):
    """Set the administrator password once, on a brand new deployment.

    This used to need nothing at all. On a fresh install with the port open,
    the first caller to reach it owned the system — and reaching it takes a
    port scan, not an invitation. It now demands the shared secret from the
    environment, and refuses to run if that secret was never set.
    """
    expected = settings.FLOWMETA_BOOTSTRAP_TOKEN
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Bootstrap is disabled. Set FLOWMETA_BOOTSTRAP_TOKEN to enable it.",
        )
    await check_rate_limit(
        client_key(request, scope="bootstrap"),
        limit=settings.AUTH_SIGNUP_MAX_ATTEMPTS,
        window_sec=settings.AUTH_SIGNUP_WINDOW_SEC,
    )
    supplied = request.headers.get("x-bootstrap-token", "")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid bootstrap token")
    user = await get_or_create_default_user(session)
    password = str(body.get("password") or "")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
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
async def login(request: Request, body: dict, session: AsyncSession = Depends(get_session)):
    username = str(body.get("username") or body.get("email") or "").strip()
    if "@" in username:
        username = username.lower()
    password = str(body.get("password") or "")
    # Bucketed per client *and* per account name, so one attacker cannot lock
    # every user out by hammering the shared address bucket, and one account
    # cannot be sprayed from a single host.
    throttle_key = client_key(request, scope="login", identity=username)
    await check_rate_limit(
        throttle_key,
        limit=settings.AUTH_LOGIN_MAX_ATTEMPTS,
        window_sec=settings.AUTH_LOGIN_WINDOW_SEC,
    )
    result = await session.execute(select(User).where((User.username == username) | (User.email == username)))
    user = result.scalar_one_or_none()
    if user is not None and not user.password_hash:
        raise HTTPException(status_code=409, detail="Admin password is not configured")
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="User account is disabled")
    await clear_rate_limit(throttle_key)
    return {
        "access_token": create_token(user.id, user.token_version),
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
        },
    }


@router.post("/register", response_model=dict, status_code=201)
async def register(request: Request, body: dict, session: AsyncSession = Depends(get_session)):
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(
            status_code=403, detail="Đăng ký tự do đang tắt. Liên hệ quản trị viên để được cấp tài khoản."
        )
    await check_rate_limit(
        client_key(request, scope="signup"),
        limit=settings.AUTH_SIGNUP_MAX_ATTEMPTS,
        window_sec=settings.AUTH_SIGNUP_WINDOW_SEC,
    )
    email = str(body.get("email") or "").strip().lower()
    username = str(body.get("username") or email.split("@", 1)[0]).strip()
    full_name = str(body.get("full_name") or "").strip() or None
    password = str(body.get("password") or "")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Email không hợp lệ")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Tên đăng nhập phải có ít nhất 3 ký tự")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự"
        )
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
    return {
        "access_token": create_token(user.id, user.token_version),
        "token_type": "bearer",
        "user": _user_response(user),
    }


@router.post("/forgot-password", response_model=dict)
async def forgot_password(request: Request, body: dict, session: AsyncSession = Depends(get_session)):
    # Every call here mints a token and, once mail is wired up, sends a message
    # to somebody who did not ask for it. Same budget as signup.
    await check_rate_limit(
        client_key(request, scope="forgot"),
        limit=settings.AUTH_SIGNUP_MAX_ATTEMPTS,
        window_sec=settings.AUTH_SIGNUP_WINDOW_SEC,
    )
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
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
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
    # Whoever was holding a token for this account loses it here. That is the
    # whole point of resetting a password you think somebody else knows.
    revoke_sessions(user)
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
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Unknown role")
    if role != "user" and not await has_permission(session, user, "permission:assign"):
        raise HTTPException(status_code=403, detail="Missing permission: permission:assign")
    if role == "super_admin" and not await has_permission(session, user, "tenant:manage:any"):
        raise HTTPException(status_code=403, detail="Only a super administrator can assign super_admin")
    _guard_assigned_rank(user, role)
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
    _guard_target_rank(user, item)
    role = body.get("role")
    status = body.get("status")
    password = body.get("password")
    if role is not None:
        role_value = str(role).strip().lower()
        if role_value not in ASSIGNABLE_ROLES:
            raise HTTPException(status_code=400, detail="Unknown role")
        if not await has_permission(session, user, "permission:assign"):
            raise HTTPException(status_code=403, detail="Missing permission: permission:assign")
        if role_value == "super_admin" and not await has_permission(session, user, "tenant:manage:any"):
            raise HTTPException(status_code=403, detail="Only a super administrator can assign super_admin")
        _guard_assigned_rank(user, role_value)
        item.role = role_value
    if status is not None:
        status_value = str(status).strip().lower()
        if status_value not in {UserStatus.ACTIVE.value, UserStatus.DISABLED.value}:
            raise HTTPException(status_code=400, detail="status must be active or disabled")
        if str(item.id) == str(user.id) and status_value == UserStatus.DISABLED.value:
            raise HTTPException(status_code=400, detail="cannot disable current user")
        item.status = UserStatus(status_value)
    if password is not None and str(password):
        if len(str(password)) < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"password must be at least {MIN_PASSWORD_LENGTH} characters",
            )
        item.password_hash = hash_password(str(password))
        # An admin resetting somebody's password is usually containing an
        # incident. Leaving that account's live tokens working would defeat it.
        revoke_sessions(item)
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
    _guard_target_rank(user, item)
    await session.delete(item)
    await session.commit()
    return {"deleted": True, "id": str(user_uuid)}
