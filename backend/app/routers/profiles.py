"""Profile CRUD router — REST endpoints for profile management."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Body, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import CITEXT

from app.auth import current_user
from app.rbac import require_permission
from app.crypto import decrypt
from app.db.postgres import get_session
from app.event_bus import event_bus
from app.models.sqlmodels import Profile, TokenStatus, User
from app.schemas import (
    ProfileImportResult,
    ProfileResponse,
    SavedProfileStateResponse,
)
from app.services.profile_manager import ProfileManager

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _profile_to_response(profile: Profile) -> ProfileResponse:
    from app.crypto import mask
    return ProfileResponse(
        uid=profile.uid,
        masked_token=mask(decrypt(profile.token_enc)),
        token_status=profile.token_status.value,
        task_count=profile.task_count,
        last_error=profile.last_error or "",
        created_at=profile.created_at,
    )


@router.get("", response_model=List[ProfileResponse])
async def list_profiles(
    user: User = Depends(require_permission("facebook_account:read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Profile).order_by(Profile.uid))
    return [_profile_to_response(p) for p in result.scalars().all()]


@router.post("/import", response_model=ProfileImportResult)
async def import_profiles(
    user: User = Depends(require_permission("facebook_account:create")),
    body: dict | None = Body(default=None),
    raw_text: str = "",
    session: AsyncSession = Depends(get_session),
):
    if body:
        raw_text = str(body.get("raw_text") or body.get("text") or raw_text or "")
    if not raw_text:
        return ProfileImportResult(total=0, added=0, duplicate=0, errors=[])
    manager = ProfileManager()
    await manager.reload_cache(session)
    result = await manager.import_text(session, raw_text)
    return ProfileImportResult(
        total=result.total,
        added=result.added_count,
        duplicate=result.duplicate_count,
        errors=result.errors,
    )


@router.delete("", response_model=dict)
async def remove_profiles(
    user: User = Depends(require_permission("facebook_account:delete")),
    body: dict | None = Body(default=None),
    uids: list[str] = [],
    session: AsyncSession = Depends(get_session),
):
    if body:
        uids = body.get("uids") or uids
    if not uids:
        return {"removed": 0}
    norm = [u.strip() for u in uids if u.strip()]
    stmt = delete(Profile).where(func.lower(Profile.uid).in_([u.lower() for u in norm]))
    result = await session.execute(stmt)
    await session.commit()
    count = result.row_count if result.row_count is not None else 0
    return {"removed": count}


@router.get("/export", response_model=dict)
async def export_profiles(
    user: User = Depends(require_permission("facebook_account:read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Profile).order_by(Profile.uid))
    rows = result.scalars().all()
    tokens = [f"{p.uid}|{decrypt(p.token_enc)}" for p in rows]
    return {"text": "\n".join(tokens)}


@router.get("/states", response_model=dict)
async def export_states(
    user: User = Depends(require_permission("facebook_account:read")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Profile).order_by(Profile.uid))
    rows = result.scalars().all()
    states = {
        p.uid: {
            "token_status": p.token_status.value,
            "task_count": p.task_count,
            "last_error": p.last_error or "",
        }
        for p in rows
    }
    return {"states": states}


@router.put("/states", response_model=dict)
async def apply_states(
    user: User = Depends(require_permission("facebook_account:update")),
    states: dict[str, dict] = {},
    session: AsyncSession = Depends(get_session),
):
    if not states:
        return {"applied": 0}
    manager = ProfileManager()
    await manager.reload_cache(session)
    count = await manager.apply_states(session, states)
    return {"applied": count}


@router.post("/check-tokens", response_model=dict)
async def check_tokens(
    user: User = Depends(require_permission("facebook_account:check")),
    body: dict | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
):
    """
    Check all profile tokens by calling Graph API /me.
    Publishes per-profile results on the 'profile' SSE channel.
    """
    selected_uids = [str(uid).strip().lower() for uid in (body or {}).get("uids", []) if str(uid).strip()]
    stmt = select(Profile).order_by(Profile.uid)
    if selected_uids:
        stmt = stmt.where(func.lower(Profile.uid).in_(selected_uids))
    result = await session.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return {"started": False, "message": "No profiles."}

    from app.services.facebook_graph import check_token as graph_check

    for profile in rows:
        token = decrypt(profile.token_enc)
        try:
            check_result = await graph_check(token)
            if check_result.get("live"):
                profile.token_status = TokenStatus.LIVE
            else:
                profile.token_status = TokenStatus.DIE
            profile.last_error = check_result.get("error", check_result.get("message", ""))
        except Exception as ex:
            profile.token_status = TokenStatus.DIE
            profile.last_error = str(ex)

    await session.commit()
    await event_bus.publish("profile", "profile", {
        "user_id": str(user.id),
        "uid": profile.uid,
        "token_status": profile.token_status.value,
        "last_error": profile.last_error or "",
        "task_count": profile.task_count,
    })

    return {"started": True, "count": len(rows)}
