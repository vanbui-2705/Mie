"""Google and Facebook sign-in using the OAuth 2 authorization-code flow."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TOKEN_SECRET, create_token, revoke_sessions
from app.config import settings
from app.db.postgres import get_session
from app.models.sqlmodels import OAuthAccount, User, UserStatus

logger = logging.getLogger("flowmeta.auth.oauth")

router = APIRouter(prefix="/api/auth/oauth", tags=["auth"])

# The browser's half of the state check. A signed state proves the server
# issued it; only a cookie the same browser sends back proves the browser that
# started the flow is the one finishing it.
STATE_COOKIE = "flowmeta_oauth_state"
STATE_TTL_SEC = 600


def _provider_name(provider: str) -> str:
    return "Google" if provider == "google" else "Facebook" if provider == "facebook" else "OAuth"


def _login_redirect(message: str) -> RedirectResponse:
    separator = "&" if "?" in settings.AUTH_FRONTEND_CALLBACK_URL else "?"
    return RedirectResponse(f"{settings.AUTH_FRONTEND_CALLBACK_URL.rsplit('/auth/callback', 1)[0]}/login{separator}{urlencode({'oauth_error': message})}")


def _state(provider: str, nonce: str = "") -> str:
    payload = f"{provider}:{int(time.time())}:{nonce or secrets.token_urlsafe(18)}"
    signature = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode().rstrip("=")


def _verify_state(value: str, provider: str, cookie_nonce: str | None = None) -> None:
    """Check the signature, the age, and that this browser started the flow.

    The signature alone only proves *we* minted the state. Anyone could fetch
    one from `/start` and hand the finished callback URL to somebody else,
    landing them in an account they never meant to open. The nonce is echoed
    in a cookie the same browser must return, which also makes the state
    single-use: the callback clears the cookie before it answers.
    """
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        saved_provider, timestamp, nonce, signature = raw.split(":", 3)
        payload = f"{saved_provider}:{timestamp}:{nonce}"
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if (
            saved_provider != provider
            or not hmac.compare_digest(signature, expected)
            or time.time() - int(timestamp) > STATE_TTL_SEC
        ):
            raise ValueError
        if not cookie_nonce or not hmac.compare_digest(cookie_nonce, nonce):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="Phiên đăng nhập OAuth không hợp lệ hoặc đã hết hạn.") from None


def _remember_state(response: RedirectResponse, nonce: str) -> RedirectResponse:
    response.set_cookie(
        STATE_COOKIE,
        nonce,
        max_age=STATE_TTL_SEC,
        httponly=True,
        # Lax, not Strict: the browser arrives at the callback from the
        # provider's domain, and Strict would withhold the cookie on that hop.
        samesite="lax",
        secure=settings.AUTH_GOOGLE_REDIRECT_URI.startswith("https://"),
        path="/api/auth/oauth",
    )
    return response


@router.get("/{provider}/start")
async def oauth_start(provider: str):
    nonce = secrets.token_urlsafe(18)
    state = _state(provider, nonce)
    if provider == "google":
        if not settings.AUTH_GOOGLE_CLIENT_ID:
            raise HTTPException(status_code=503, detail="Google OAuth is not configured")
        query = urlencode({"client_id": settings.AUTH_GOOGLE_CLIENT_ID, "redirect_uri": settings.AUTH_GOOGLE_REDIRECT_URI, "response_type": "code", "scope": "openid email profile", "state": state, "prompt": "select_account"})
        return _remember_state(
            RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}"), nonce
        )
    if provider == "facebook":
        if not settings.AUTH_FACEBOOK_APP_ID:
            raise HTTPException(status_code=503, detail="Facebook OAuth is not configured")
        query = urlencode({"client_id": settings.AUTH_FACEBOOK_APP_ID, "redirect_uri": settings.AUTH_FACEBOOK_REDIRECT_URI, "response_type": "code", "scope": "email,public_profile", "state": state})
        return _remember_state(
            RedirectResponse(
                f"https://www.facebook.com/{settings.GRAPH_API_VERSION}/dialog/oauth?{query}"
            ),
            nonce,
        )
    raise HTTPException(status_code=404, detail="Unsupported OAuth provider")


@router.get("/status/providers", response_model=dict)
async def oauth_provider_status():
    return {
        "google": bool(settings.AUTH_GOOGLE_CLIENT_ID and settings.AUTH_GOOGLE_CLIENT_SECRET),
        "facebook": bool(settings.AUTH_FACEBOOK_APP_ID and settings.AUTH_FACEBOOK_APP_SECRET),
    }


def _clear_state(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(STATE_COOKIE, path="/api/auth/oauth")
    return response


@router.get("/{provider}/callback")
async def oauth_callback(
    request: Request,
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    provider_name = _provider_name(provider)
    if provider not in {"google", "facebook"}:
        return _login_redirect("Nhà cung cấp đăng nhập không được hỗ trợ.")
    if error:
        message = f"Bạn đã hủy đăng nhập {provider_name}." if error == "access_denied" else f"{provider_name} từ chối yêu cầu đăng nhập."
        return _clear_state(_login_redirect(message))
    if not code or not state:
        return _clear_state(_login_redirect(f"Phản hồi đăng nhập từ {provider_name} không đầy đủ."))
    try:
        _verify_state(state, provider, request.cookies.get(STATE_COOKIE))
        identity = await _fetch_identity(provider, code)
    except HTTPException as exc:
        message = str(exc.detail) if isinstance(exc.detail, str) else f"Không thể đăng nhập bằng {provider_name}."
        return _clear_state(_login_redirect(message))
    provider_id = str(identity["id"])
    email = str(identity.get("email") or "").strip().lower()
    if not email:
        return _clear_state(_login_redirect(f"{provider_name} không trả về địa chỉ email."))
    # An address the provider has not verified is a string it passed along, not
    # proof of anything — and this whole flow decides who owns an account by
    # matching on it. Facebook only returns confirmed addresses; Google says so
    # explicitly and sometimes says no.
    if not bool(identity.get("email_verified", True)):
        return _clear_state(
            _login_redirect(
                f"{provider_name} chưa xác minh địa chỉ email này. Hãy đăng nhập bằng mật khẩu."
            )
        )

    linked = (await session.execute(select(OAuthAccount).where(OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_id))).scalar_one_or_none()
    user = await session.get(User, linked.user_id) if linked else None
    if user is None:
        existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None and existing.password_hash:
            # Someone registered this address with a password before its owner
            # ever signed in here, and registration never verified the mailbox.
            # The provider has now proved who controls it, so the account goes
            # to them: the old password and every session it opened are cleared,
            # and the rightful owner can set a new one through forgot-password.
            logger.warning(
                "clearing the password on %s: %s proved ownership of %s",
                existing.username, provider, email,
            )
            existing.password_hash = None
            revoke_sessions(existing)
        user = existing
    if user is None:
        base_username = email.split("@", 1)[0][:40] or f"{provider}_user"
        username = base_username
        suffix = 1
        while (await session.execute(select(User.id).where(User.username == username))).scalar_one_or_none():
            suffix += 1
            username = f"{base_username}{suffix}"
        user = User(username=username, email=email, full_name=identity.get("name"), avatar_url=identity.get("picture"), role="user", status=UserStatus.ACTIVE)
        session.add(user)
        await session.flush()
    elif user.status != UserStatus.ACTIVE:
        return _clear_state(_login_redirect("Tài khoản đã bị vô hiệu hóa."))
    if linked is None:
        session.add(OAuthAccount(user_id=user.id, provider=provider, provider_user_id=provider_id, email=email))
    user.full_name = user.full_name or identity.get("name")
    user.avatar_url = identity.get("picture") or user.avatar_url
    await session.commit()

    user_data = {"id": str(user.id), "username": user.username, "email": user.email, "role": user.role}
    encoded_user = base64.urlsafe_b64encode(json.dumps(user_data).encode()).decode().rstrip("=")
    fragment = urlencode({"token": create_token(user.id, user.token_version), "user": encoded_user})
    # Clearing the cookie here is what makes the state single-use.
    return _clear_state(RedirectResponse(f"{settings.AUTH_FRONTEND_CALLBACK_URL}#{fragment}"))


async def _fetch_identity(provider: str, code: str) -> dict:
    provider_name = _provider_name(provider)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if provider == "google":
                token_response = await client.post("https://oauth2.googleapis.com/token", data={"client_id": settings.AUTH_GOOGLE_CLIENT_ID, "client_secret": settings.AUTH_GOOGLE_CLIENT_SECRET, "code": code, "grant_type": "authorization_code", "redirect_uri": settings.AUTH_GOOGLE_REDIRECT_URI})
                token_response.raise_for_status()
                access_token = token_response.json()["access_token"]
                response = await client.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access_token}"})
            elif provider == "facebook":
                token_response = await client.get(f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/oauth/access_token", params={"client_id": settings.AUTH_FACEBOOK_APP_ID, "client_secret": settings.AUTH_FACEBOOK_APP_SECRET, "code": code, "redirect_uri": settings.AUTH_FACEBOOK_REDIRECT_URI})
                token_response.raise_for_status()
                access_token = token_response.json()["access_token"]
                response = await client.get(f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/me", params={"fields": "id,name,email,picture.type(large)", "access_token": access_token})
            else:
                raise HTTPException(status_code=404, detail="Nhà cung cấp đăng nhập không được hỗ trợ.")
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"Không thể xác minh đăng nhập với {provider_name}. Vui lòng thử lại.") from exc
    picture = data.get("picture")
    if isinstance(picture, dict):
        data["picture"] = picture.get("data", {}).get("url")
    return data
