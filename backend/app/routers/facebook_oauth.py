"""Facebook OAuth connect flow for production page-token onboarding."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TOKEN_SECRET, current_user
from app.rbac import require_permission
from app.config import settings
from app.crypto import encrypt
from app.db.postgres import get_session
from app.models.sqlmodels import FacebookAccount, FacebookPage, TokenStatus, User
from app.services.facebook_graph import (
    exchange_long_lived_user_token,
    exchange_oauth_code_for_user_token,
    get_my_pages,
    get_user_info,
)

router = APIRouter(prefix="/api/facebook/oauth", tags=["facebook-oauth"])


@router.get("/start", response_model=dict)
async def start_facebook_oauth(user: User = Depends(require_permission("facebook_account:create"))):
    if not settings.META_APP_ID or not settings.META_APP_SECRET:
        raise HTTPException(status_code=400, detail="META_APP_ID/META_APP_SECRET is not configured")
    state = _sign_state({"user_id": str(user.id), "nonce": secrets.token_urlsafe(16), "exp": int(time.time()) + 900})
    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": settings.FACEBOOK_OAUTH_REDIRECT_URI,
        "state": state,
        "scope": settings.FACEBOOK_OAUTH_SCOPES,
        "response_type": "code",
        "auth_type": "rerequest",
    }
    return {"auth_url": f"https://www.facebook.com/dialog/oauth?{urlencode(params)}"}


@router.get("/callback")
async def facebook_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    if error:
        return _redirect(False, error_description or error)
    if not code or not state:
        return _redirect(False, "Facebook callback missing code/state")

    payload = _verify_state(state)
    if payload is None:
        return _redirect(False, "OAuth state is invalid or expired")
    user_id = uuid.UUID(str(payload["user_id"]))
    user = await session.get(User, user_id)
    if user is None:
        return _redirect(False, "FlowMeta user not found")

    token_result = await exchange_oauth_code_for_user_token(code, settings.FACEBOOK_OAUTH_REDIRECT_URI)
    if not token_result.get("success"):
        return _redirect(False, str(token_result.get("message") or "Cannot exchange OAuth code"))

    token = str(token_result["access_token"])
    token_expires_at = _expires_at_from_result(token_result)
    token_is_long_lived = False
    long_result = await exchange_long_lived_user_token(token)
    if long_result.get("success") and long_result.get("access_token"):
        token = str(long_result["access_token"])
        token_expires_at = _expires_at_from_result(long_result)
        token_is_long_lived = True

    info = await get_user_info(token)
    if not info.get("success") or not info.get("id"):
        return _redirect(False, str(info.get("message") or info.get("error") or "Cannot read Facebook user info"))

    account = await _upsert_account(session, user.id, str(info["id"]), str(info.get("name") or ""), token, token_expires_at, token_is_long_lived)
    sync_result = await _sync_pages_for_account(session, user.id, account, token)
    await session.commit()
    return _redirect(
        True,
        f"Connected {account.uid}. Pages added {sync_result['added']}, updated {sync_result['updated']}.",
    )


async def _upsert_account(
    session: AsyncSession,
    user_id: uuid.UUID,
    uid: str,
    name: str,
    token: str,
    token_expires_at,
    token_is_long_lived: bool,
) -> FacebookAccount:
    result = await session.execute(
        select(FacebookAccount).where(
            FacebookAccount.user_id == user_id,
            func.lower(FacebookAccount.uid) == uid.lower(),
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = FacebookAccount(
            user_id=user_id,
            uid=uid,
            name=name or None,
            user_token_enc=encrypt(token),
            token_status=TokenStatus.LIVE,
            last_error="",
            token_expires_at=token_expires_at,
            token_last_refreshed_at=datetime.now(timezone.utc),
            token_is_long_lived=token_is_long_lived,
        )
        session.add(account)
        await session.flush()
        return account
    account.name = name or account.name
    account.user_token_enc = encrypt(token)
    account.token_status = TokenStatus.LIVE
    account.last_error = ""
    account.token_expires_at = token_expires_at
    account.token_last_refreshed_at = datetime.now(timezone.utc)
    account.token_is_long_lived = token_is_long_lived
    await session.flush()
    return account


async def _sync_pages_for_account(session: AsyncSession, user_id: uuid.UUID, account: FacebookAccount, token: str) -> dict:
    result = await get_my_pages(token)
    if not result.get("success"):
        account.last_error = str(result.get("message") or result.get("error") or "Sync pages failed")
        return {"added": 0, "updated": 0}
    added = 0
    updated = 0
    for item in result.get("pages", []):
        page_id = str(item.get("page_id") or "")
        page_token = str(item.get("page_access_token") or "")
        if not page_id or not page_token:
            continue
        page_result = await session.execute(
            select(FacebookPage).where(FacebookPage.user_id == user_id, FacebookPage.page_id == page_id)
        )
        page = page_result.scalar_one_or_none()
        if page is None:
            session.add(FacebookPage(
                user_id=user_id,
                facebook_account_id=account.id,
                page_id=page_id,
                page_name=str(item.get("page_name") or page_id),
                page_access_token_enc=encrypt(page_token),
                category=str(item.get("category") or ""),
                permissions=item.get("permissions") or [],
                status="active",
            ))
            added += 1
        else:
            page.facebook_account_id = account.id
            page.page_name = str(item.get("page_name") or page.page_name)
            page.page_access_token_enc = encrypt(page_token)
            page.category = str(item.get("category") or "")
            page.permissions = item.get("permissions") or []
            page.status = "active"
            updated += 1
    account.last_error = ""
    return {"added": added, "updated": updated}


def _redirect(success: bool, message: str) -> RedirectResponse:
    params = urlencode({"oauth": "success" if success else "error", "message": message})
    separator = "&" if "?" in settings.FACEBOOK_OAUTH_SUCCESS_URL else "?"
    return RedirectResponse(f"{settings.FACEBOOK_OAUTH_SUCCESS_URL}{separator}{params}")


def _expires_at_from_result(result: dict) -> datetime | None:
    try:
        expires_in = int(result.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if expires_in <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _sign_state(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify_state(value: str) -> dict | None:
    try:
        body, sig = value.split(".", 1)
        expected = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
