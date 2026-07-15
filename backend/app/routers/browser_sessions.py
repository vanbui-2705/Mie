"""Browser session management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.rbac import require_permission
from app.db.postgres import get_session
from app.models.sqlmodels import BrowserSession, BrowserSessionStatus, User
from app.services.browser_sessions import (
    expire_old_sessions,
    provider_remote_url_for_session,
    session_response,
    stop_browser_session,
)

router = APIRouter(tags=["browser-sessions"])


@router.get("/api/browser-sessions", response_model=list[dict])
async def list_browser_sessions(
    user: User = Depends(require_permission("browser_session:read")),
    session: AsyncSession = Depends(get_session),
):
    await expire_old_sessions(session)
    result = await session.execute(
        select(BrowserSession)
        .where(BrowserSession.user_id == user.id)
        .order_by(BrowserSession.started_at.desc())
    )
    await session.commit()
    return [session_response(item) for item in result.scalars().all()]


@router.get("/api/browser-sessions/{session_id}", response_model=dict)
async def get_browser_session(
    session_id: str,
    user: User = Depends(require_permission("browser_session:read")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_user_session(session, user.id, session_id)
    return session_response(item)


@router.post("/api/browser-sessions/{session_id}/stop", response_model=dict)
async def stop_session(
    session_id: str,
    user: User = Depends(require_permission("browser_session:manage")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_user_session(session, user.id, session_id)
    return session_response(await stop_browser_session(session, item))


@router.get("/remote/{session_id}")
async def open_remote_browser(
    session_id: str,
    user: User = Depends(require_permission("browser_session:read")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_user_session(session, user.id, session_id)
    now = datetime.now(timezone.utc)
    if item.status == BrowserSessionStatus.ERROR:
        raise HTTPException(status_code=503, detail=item.error or "Browser session provider failed")
    if item.status not in (BrowserSessionStatus.STARTING, BrowserSessionStatus.READY) or item.expires_at <= now:
        item.status = BrowserSessionStatus.EXPIRED
        item.stopped_at = now
        await session.commit()
        raise HTTPException(status_code=410, detail="Browser session expired")
    item.last_seen_at = now
    await session.commit()
    provider_url = provider_remote_url_for_session(item)
    if not provider_url:
        raise HTTPException(status_code=503, detail="Remote browser provider is not configured")
    return RedirectResponse(provider_url)


async def _get_user_session(session: AsyncSession, user_id: uuid.UUID, session_id: str) -> BrowserSession:
    item = await _get_session(session, session_id)
    if item.user_id != user_id:
        raise HTTPException(status_code=404, detail="Browser session not found")
    return item


async def _get_session(session: AsyncSession, session_id: str) -> BrowserSession:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid browser session id") from None
    item = await session.get(BrowserSession, session_uuid)
    if item is None:
        raise HTTPException(status_code=404, detail="Browser session not found")
    return item
