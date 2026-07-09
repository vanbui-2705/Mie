"""Multi-user Facebook account and Fanpage routes."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import settings
from app.crypto import decrypt, encrypt, mask
from app.db.postgres import get_session
from app.models.sqlmodels import BrowserSession, FacebookAccount, FacebookPage, TokenStatus, User
from app.services.browser_profiles import profile_exists, profile_path
from app.services.browser_sessions import create_browser_session, session_response, stop_browser_session
from app.services.extension_queue import is_extension_online
from app.services.facebook_graph import exchange_long_lived_user_token, get_my_pages, get_user_info
from app.services.personal_browser import check_facebook_login

router = APIRouter(tags=["facebook"])


def _account_response(account: FacebookAccount) -> dict:
    return {
        "id": str(account.id),
        "uid": account.uid,
        "name": account.name or "",
        "masked_token": mask(decrypt(account.user_token_enc)),
        "token_status": account.token_status.value,
        "last_error": account.last_error or "",
        "last_checked_at": account.last_checked_at,
        "browser_status": account.browser_status,
        "browser_last_checked_at": account.browser_last_checked_at,
        "browser_last_error": account.browser_last_error or "",
        "created_at": account.created_at,
    }


def _page_response(page: FacebookPage) -> dict:
    return {
        "id": str(page.id),
        "facebook_account_id": str(page.facebook_account_id),
        "page_id": page.page_id,
        "page_name": page.page_name,
        "category": page.category or "",
        "permissions": page.permissions or [],
        "status": page.status,
        "created_at": page.created_at,
    }


@router.get("/api/facebook-accounts", response_model=list[dict])
async def list_accounts(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(FacebookAccount)
        .where(FacebookAccount.user_id == user.id)
        .order_by(FacebookAccount.created_at.desc())
    )
    rows = []
    for account in result.scalars().all():
        item = _account_response(account)
        if await is_extension_online(str(account.id)):
            item["browser_status"] = "extension_online"
            item["browser_last_error"] = ""
        elif account.browser_status == "extension_online":
            item["browser_status"] = "extension_offline"
            item["browser_last_error"] = "Extension is not connected."
        rows.append(item)
    return rows


@router.post("/api/facebook-accounts/import", response_model=dict)
async def import_accounts(
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    raw_text = str(body.get("raw_text") or body.get("text") or "")
    errors: list[str] = []
    added = 0
    duplicate = 0
    exchanged = 0
    exchange_failed = 0
    for raw_line in raw_text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            errors.append(f"Sai định dạng: {line}")
            continue
        uid = parts[0].strip()
        token = parts[1].strip()
        import_error = ""
        if settings.AUTO_EXCHANGE_LONG_LIVED_TOKEN and settings.META_APP_ID and settings.META_APP_SECRET:
            exchange = await exchange_long_lived_user_token(token)
            if exchange.get("success") and exchange.get("access_token"):
                token = str(exchange["access_token"])
                exchanged += 1
            elif not exchange.get("skipped"):
                exchange_failed += 1
                import_error = str(exchange.get("message") or "Long-lived token exchange failed")
        result = await session.execute(
            select(FacebookAccount).where(
                FacebookAccount.user_id == user.id,
                func.lower(FacebookAccount.uid) == uid.lower(),
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.user_token_enc = encrypt(token)
            existing.token_status = TokenStatus.DA_REFRESH
            existing.last_error = import_error
            duplicate += 1
        else:
            session.add(FacebookAccount(
                user_id=user.id,
                uid=uid,
                user_token_enc=encrypt(token),
                token_status=TokenStatus.DA_NAP,
                last_error=import_error,
            ))
            added += 1
    await session.commit()
    return {
        "total": added + duplicate,
        "added": added,
        "duplicate": duplicate,
        "exchanged_long_lived": exchanged,
        "exchange_failed": exchange_failed,
        "errors": errors,
    }


@router.post("/api/facebook-accounts/{account_id}/check", response_model=dict)
async def check_account(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    result = await get_user_info(decrypt(account.user_token_enc))
    account.last_checked_at = datetime.now(timezone.utc)
    if result.get("success"):
        account.name = result.get("name") or account.name
        account.token_status = TokenStatus.LIVE
        account.last_error = ""
    else:
        account.token_status = TokenStatus.DIE
        account.last_error = result.get("message") or result.get("error") or "Token check failed"
    await session.commit()
    return _account_response(account)


@router.post("/api/facebook-accounts/{account_id}/sync-pages", response_model=dict)
async def sync_pages(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    result = await get_my_pages(decrypt(account.user_token_enc))
    if not result.get("success"):
        account.last_error = result.get("message") or result.get("error") or "Sync pages failed"
        account.last_checked_at = datetime.now(timezone.utc)
        if result.get("token_issue"):
            account.token_status = TokenStatus.DIE
        await session.commit()
        raise HTTPException(status_code=400, detail=account.last_error)

    added = 0
    updated = 0
    for item in result.get("pages", []):
        page_id = item.get("page_id") or ""
        page_token = item.get("page_access_token") or ""
        if not page_id or not page_token:
            continue
        page_result = await session.execute(
            select(FacebookPage).where(
                FacebookPage.user_id == user.id,
                FacebookPage.page_id == page_id,
            )
        )
        page = page_result.scalar_one_or_none()
        if page:
            page.facebook_account_id = account.id
            page.page_name = item.get("page_name") or page.page_name
            page.page_access_token_enc = encrypt(page_token)
            page.category = item.get("category") or ""
            page.permissions = item.get("permissions") or []
            updated += 1
        else:
            session.add(FacebookPage(
                user_id=user.id,
                facebook_account_id=account.id,
                page_id=page_id,
                page_name=item.get("page_name") or page_id,
                page_access_token_enc=encrypt(page_token),
                category=item.get("category") or "",
                permissions=item.get("permissions") or [],
            ))
            added += 1
    account.token_status = TokenStatus.LIVE
    account.last_error = ""
    await session.commit()
    return {"added": added, "updated": updated}


@router.post("/api/facebook-accounts/{account_id}/browser-login/start", response_model=dict)
async def start_browser_login(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    return await _start_connect_browser(session, user.id, account)


@router.post("/api/facebook-accounts/{account_id}/connect-browser/start", response_model=dict)
async def start_connect_browser(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    return await _start_connect_browser(session, user.id, account)


@router.get("/api/facebook-accounts/{account_id}/browser-login/status", response_model=dict)
async def browser_login_status(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    return await _check_connect_browser(session, user.id, account)


@router.get("/api/facebook-accounts/{account_id}/connect-browser/status", response_model=dict)
async def connect_browser_status(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    return await _check_connect_browser(session, user.id, account)


@router.post("/api/facebook-accounts/{account_id}/browser-login/stop", response_model=dict)
async def stop_browser_login(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    return await _stop_connect_browser(session, user.id, account)


@router.post("/api/facebook-accounts/{account_id}/connect-browser/stop", response_model=dict)
async def stop_connect_browser(
    account_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_account(session, user.id, account_id)
    return await _stop_connect_browser(session, user.id, account)


@router.get("/api/facebook-pages", response_model=list[dict])
async def list_pages(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(FacebookPage)
        .where(FacebookPage.user_id == user.id)
        .order_by(FacebookPage.page_name)
    )
    return [_page_response(row) for row in result.scalars().all()]


async def _get_account(session: AsyncSession, user_id: uuid.UUID, account_id: str) -> FacebookAccount:
    try:
        account_uuid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account id") from None
    account = await session.get(FacebookAccount, account_uuid)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=404, detail="Facebook account not found")
    return account


async def _start_connect_browser(session: AsyncSession, user_id: uuid.UUID, account: FacebookAccount) -> dict:
    browser_session = await create_browser_session(session, user_id, account)
    selected_profile_path = profile_path(user_id, account.id)
    return {
        "account_id": str(account.id),
        "status": account.browser_status,
        "browser_session_id": str(browser_session.id),
        "session_url": browser_session.remote_url,
        "remote_username": "kasm_user" if browser_session.provider == "kasm" else "",
        "remote_password": settings.KASM_VNC_PASSWORD if browser_session.provider == "kasm" else "",
        "profile_path": str(selected_profile_path),
        "message": "Mo browser ket noi lan dau, login Facebook, roi bam Check browser. Task sau do se chay an bang Playwright/Browserless.",
    }


async def _check_connect_browser(session: AsyncSession, user_id: uuid.UUID, account: FacebookAccount) -> dict:
    profile_dir = profile_path(user_id, account.id)
    check = check_facebook_login(str(profile_dir)) if profile_exists(user_id, account.id) else {"success": False, "status": "login_required", "message": "Browser profile khong ton tai hoac rong."}
    if check.get("success"):
        account.browser_status = "logged_in"
        account.browser_last_error = ""
    elif str(check.get("status") or "").lower() == "checkpoint":
        account.browser_status = "checkpoint"
        account.browser_last_error = check.get("message") or "Facebook yeu cau checkpoint/xac thuc."
    elif check.get("unknown") and profile_exists(user_id, account.id):
        account.browser_status = "login_required"
        account.browser_last_error = check.get("message") or "Chua the check login trong API container."
    elif account.browser_status == "logged_in":
        account.browser_status = "expired"
        account.browser_last_error = check.get("message") or "Browser profile khong con login."
    else:
        account.browser_status = "login_required"
        account.browser_last_error = check.get("message") or account.browser_last_error
    account.browser_last_checked_at = datetime.now(timezone.utc)
    await session.commit()
    return {
        "account_id": str(account.id),
        "status": account.browser_status,
        "available": account.browser_status == "logged_in",
        "session_url": "",
        "last_error": account.browser_last_error or "",
        "last_checked_at": account.browser_last_checked_at,
    }


async def _stop_connect_browser(session: AsyncSession, user_id: uuid.UUID, account: FacebookAccount) -> dict:
    result = await session.execute(
        select(BrowserSession).where(
            BrowserSession.user_id == user_id,
            BrowserSession.facebook_account_id == account.id,
        ).order_by(BrowserSession.started_at.desc())
    )
    latest = result.scalar_one_or_none()
    if latest is not None:
        await stop_browser_session(session, latest)
    if account.browser_status == "login_required":
        account.browser_status = "not_configured"
    account.browser_last_checked_at = datetime.now(timezone.utc)
    await session.commit()
    return {"account_id": str(account.id), "status": account.browser_status}
