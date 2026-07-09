"""Browser login session orchestration.

Production can point this at an external Kasm/KasmVNC gateway. Local/dev falls
back to the existing noVNC service, but callers only see a safe /remote session
URL.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.sqlmodels import BrowserSession, BrowserSessionStatus, FacebookAccount
from app.services.browser_profiles import activate_remote_profile
from app.services.kasm_provider import KasmProviderError, start_kasm_session, stop_kasm_session


ACTIVE_STATUSES = (BrowserSessionStatus.STARTING, BrowserSessionStatus.READY)


async def create_browser_session(session: AsyncSession, user_id: uuid.UUID, account: FacebookAccount) -> BrowserSession:
    await expire_old_sessions(session)
    await enforce_session_limits(session, user_id)

    activate_remote_profile(user_id, account.id)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.BROWSER_SESSION_TTL_SECONDS)
    browser_session = BrowserSession(
        user_id=user_id,
        facebook_account_id=account.id,
        status=BrowserSessionStatus.STARTING,
        provider=settings.BROWSER_PROVIDER,
        container_name=None,
        session_key=str(account.id),
        remote_url="",
        expires_at=expires_at,
        last_seen_at=datetime.now(timezone.utc),
    )
    session.add(browser_session)
    await session.flush()
    browser_session.remote_url = _public_session_url(browser_session.id)
    if settings.BROWSER_PROVIDER.lower() == "kasm":
        try:
            provider = start_kasm_session(browser_session.id, user_id, account.id)
            browser_session.container_name = provider.get("container_name") or None
            browser_session.session_key = provider.get("provider_url") or ""
            browser_session.status = BrowserSessionStatus.READY
        except KasmProviderError as exc:
            browser_session.status = BrowserSessionStatus.ERROR
            browser_session.error = str(exc)
            browser_session.session_key = _provider_remote_url(account.id)
    else:
        browser_session.session_key = _provider_remote_url(account.id)
        browser_session.status = BrowserSessionStatus.READY
    account.browser_status = "login_required"
    account.browser_last_error = browser_session.error or ""
    account.browser_last_checked_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(browser_session)
    return browser_session


async def expire_old_sessions(session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(BrowserSession).where(
            BrowserSession.status.in_(ACTIVE_STATUSES),
            BrowserSession.expires_at <= now,
        )
    )
    for item in result.scalars().all():
        stop_kasm_session(item.container_name)
        item.status = BrowserSessionStatus.EXPIRED
        item.stopped_at = now
        item.error = item.error or "Browser session expired."
    await session.flush()


async def enforce_session_limits(session: AsyncSession, user_id: uuid.UUID) -> None:
    now = datetime.now(timezone.utc)
    per_user_result = await session.execute(
        select(BrowserSession)
        .where(BrowserSession.user_id == user_id, BrowserSession.status.in_(ACTIVE_STATUSES))
        .order_by(BrowserSession.started_at.asc())
    )
    per_user = per_user_result.scalars().all()
    for item in per_user[: max(0, len(per_user) - settings.MAX_BROWSER_SESSIONS_PER_USER + 1)]:
        stop_kasm_session(item.container_name)
        item.status = BrowserSessionStatus.STOPPED
        item.stopped_at = now
        item.error = "Stopped because per-user browser session limit was reached."

    global_count = await session.scalar(
        select(func.count()).select_from(BrowserSession).where(BrowserSession.status.in_(ACTIVE_STATUSES))
    )
    if int(global_count or 0) >= settings.MAX_BROWSER_SESSIONS_GLOBAL:
        oldest_result = await session.execute(
            select(BrowserSession)
            .where(BrowserSession.status.in_(ACTIVE_STATUSES))
            .order_by(BrowserSession.started_at.asc())
            .limit(1)
        )
        oldest = oldest_result.scalar_one_or_none()
        if oldest is not None:
            stop_kasm_session(oldest.container_name)
            oldest.status = BrowserSessionStatus.STOPPED
            oldest.stopped_at = now
            oldest.error = "Stopped because global browser session limit was reached."
    await session.flush()


async def stop_browser_session(session: AsyncSession, browser_session: BrowserSession) -> BrowserSession:
    stop_kasm_session(browser_session.container_name)
    browser_session.status = BrowserSessionStatus.STOPPED
    browser_session.stopped_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(browser_session)
    return browser_session


def session_response(browser_session: BrowserSession) -> dict:
    return {
        "id": str(browser_session.id),
        "user_id": str(browser_session.user_id),
        "facebook_account_id": str(browser_session.facebook_account_id),
        "status": browser_session.status.value if hasattr(browser_session.status, "value") else browser_session.status,
        "provider": browser_session.provider,
        "session_url": browser_session.remote_url,
        "remote_url": browser_session.remote_url,
        "expires_at": browser_session.expires_at,
        "last_seen_at": browser_session.last_seen_at,
        "error": browser_session.error or "",
    }


def _provider_remote_url(account_id: uuid.UUID | str) -> str:
    template = settings.REMOTE_BROWSER_URL_TEMPLATE.strip()
    if template:
        return template.replace("{account_id}", str(account_id))
    base_url = settings.REMOTE_BROWSER_BASE_URL.strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/vnc.html?autoconnect=true&resize=scale"


def provider_remote_url_for_session(browser_session: BrowserSession) -> str:
    if browser_session.session_key and browser_session.session_key.startswith(("http://", "https://")):
        return browser_session.session_key
    return _provider_remote_url(browser_session.facebook_account_id)


def _public_session_url(session_id: uuid.UUID | str) -> str:
    base = settings.REMOTE_BROWSER_PUBLIC_BASE_URL.strip().rstrip("/")
    path = f"/remote/{session_id}"
    return f"{base}{path}" if base else path
