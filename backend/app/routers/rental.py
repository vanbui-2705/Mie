"""Rental (Đăng trọ tự động) config/room management endpoints."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt
from app.db.postgres import get_session, session_context
from app.models.sqlmodels import (
    FacebookGroup,
    GoogleSheetConnection,
    PublicationJob,
    RentalConfig,
    RentalRoom,
    User,
)
from app.rbac import require_permission
from app.schemas.rental import AssignRentalGroups, RentalConfigCreate, RentalConfigUpdate
from app.services.nhatrovn_adapter import NhatrovnAdapter, NhatrovnError
from app.services.rental_post import RentalPostService
from app.services.rental_sync import RentalSyncBusy, RentalSyncError, RentalSyncService

router = APIRouter(prefix="/api/rental", tags=["rental"])


# ─── Configs ─────────────────────────────────────────────────────────────────

@router.get("/configs", response_model=list[dict])
async def list_configs(
    user: User = Depends(require_permission("rental:read")),
    session: AsyncSession = Depends(get_session),
):
    rows = list((await session.execute(
        select(RentalConfig)
        .where(RentalConfig.user_id == user.id)
        .order_by(RentalConfig.created_at.desc())
    )).scalars())
    return [_config_dict(row) for row in rows]


@router.post("/configs", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_config(
    body: RentalConfigCreate,
    user: User = Depends(require_permission("rental:create")),
    session: AsyncSession = Depends(get_session),
):
    credentials = body.credentials.model_dump()
    await _owned_writable_sheet_or_400(
        session, body.google_sheet_connection_id, user.id,
    )

    row = RentalConfig(
        user_id=user.id,
        name=body.name,
        source_type="nhatrovn",
        source_credentials_enc=encrypt(json.dumps(credentials)),
        province_code=body.province_code,
        province_name=body.province_name,
        district_code=body.district_code,
        district_name=body.district_name,
        ward_code=body.ward_code,
        ward_name=body.ward_name,
        caption_template=body.caption_template,
        contact_phone=body.contact_phone,
        post_spacing_seconds=body.post_spacing_seconds,
        post_delay_seconds=body.post_delay_seconds,
        poll_interval_seconds=body.poll_interval_seconds,
        auto_post=body.auto_post,
        google_sheet_connection_id=body.google_sheet_connection_id,
        timezone=body.timezone,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _config_dict(row)


@router.put("/configs/{config_id}", response_model=dict)
async def update_config(
    config_id: uuid.UUID,
    body: RentalConfigUpdate,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_config(session, config_id, user.id)
    fields = body.model_fields_set
    if body.credentials is not None:
        row.source_credentials_enc = encrypt(json.dumps(body.credentials.model_dump()))
    if "google_sheet_connection_id" in fields:
        await _owned_writable_sheet_or_400(
            session, body.google_sheet_connection_id, user.id,
        )
        row.google_sheet_connection_id = body.google_sheet_connection_id
    for field in (
        "name",
        "province_code",
        "province_name",
        "district_code",
        "district_name",
        "ward_code",
        "ward_name",
        "caption_template",
        "contact_phone",
        "post_spacing_seconds",
        "post_delay_seconds",
        "poll_interval_seconds",
        "auto_post",
        "timezone",
    ):
        if field in fields:
            value = getattr(body, field)
            if value is not None or field in {"ward_code", "ward_name"}:
                setattr(row, field, value)

    await session.flush()
    await session.refresh(row)
    return _config_dict(row)


@router.delete("/configs/{config_id}", response_model=dict)
async def delete_config(
    config_id: uuid.UUID,
    user: User = Depends(require_permission("rental:delete")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_config(session, config_id, user.id)
    await session.delete(row)
    await session.flush()
    return {"deleted": True, "id": str(config_id)}


@router.post("/configs/{config_id}/test-login", response_model=dict)
async def test_login(
    config_id: uuid.UUID,
    user: User = Depends(require_permission("rental:create")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_config(session, config_id, user.id)
    credentials = _decrypt_credentials(row)
    adapter = _adapter()
    client = None
    try:
        client = await adapter.login(credentials.get("username", ""), credentials.get("password", ""))
        return {"ok": True}
    except NhatrovnError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        aclose = getattr(client, "aclose", None)
        if aclose:
            await aclose()


@router.post("/configs/{config_id}/sync-now", response_model=dict)
async def sync_now(
    config_id: uuid.UUID,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_config(session, config_id, user.id)
    try:
        return await RentalSyncService(session_context).sync_config(config_id)
    except RentalSyncBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RentalSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/configs/{config_id}/post-now", response_model=dict)
async def post_now(
    config_id: uuid.UUID,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_config(session, config_id, user.id)
    fired = await RentalPostService(session_context).post_due(
        config_id=config_id,
        user_id=user.id,
        force=True,
    )
    return {"fired": fired}


@router.get("/configs/{config_id}/rooms", response_model=list[dict])
async def list_rooms(
    config_id: uuid.UUID,
    user: User = Depends(require_permission("rental:read")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_config(session, config_id, user.id)
    rows = list((await session.execute(
        select(RentalRoom)
        .where(RentalRoom.config_id == config_id)
        .order_by(RentalRoom.created_at.desc())
    )).scalars())
    return [_room_dict(row) for row in rows]


# ─── Rooms ───────────────────────────────────────────────────────────────────

@router.get("/rooms/{room_id}/jobs", response_model=list[dict])
async def list_room_jobs(
    room_id: uuid.UUID,
    user: User = Depends(require_permission("rental:read")),
    session: AsyncSession = Depends(get_session),
):
    room = await _owned_room(session, room_id, user.id)
    rows = list((await session.execute(
        select(PublicationJob)
        .where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.user_id == user.id,
        )
        .order_by(PublicationJob.created_at.desc())
    )).scalars())
    return [_publication_job_dict(row) for row in rows]


@router.post("/rooms/{room_id}/assign-groups", response_model=dict)
async def assign_groups(
    room_id: uuid.UUID,
    body: AssignRentalGroups,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    room = await _owned_room(session, room_id, user.id)
    groups = list((await session.execute(
        select(FacebookGroup).where(
            FacebookGroup.user_id == user.id,
            FacebookGroup.group_id.in_(body.group_ids),
        )
    )).scalars())
    resolved = {str(group.group_id): group for group in groups if group.group_id}
    missing = [group_id for group_id in body.group_ids if group_id not in resolved]
    unavailable = [
        group_id
        for group_id, group in resolved.items()
        if group.status != "available"
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown Facebook groups: {missing}")
    if unavailable:
        raise HTTPException(status_code=400, detail=f"Unavailable Facebook groups: {unavailable}")
    active_job = (await session.execute(
        select(PublicationJob.id).where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.status.in_(["dispatching", "queued", "running"]),
        ).limit(1)
    )).scalar_one_or_none()
    if active_job is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot reassign groups while a publication job is running",
        )
    await session.execute(
        PublicationJob.__table__.delete().where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.status.in_(["pending", "failed", "canceled"]),
        )
    )
    group_ids = body.group_ids
    room.matched_group_ids_json = json.dumps(group_ids)
    room.status = "new"
    room.error = None
    await session.flush()
    await session.refresh(room)
    return _room_dict(room)


@router.post("/rooms/{room_id}/skip", response_model=dict)
async def skip_room(
    room_id: uuid.UUID,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    room = await _owned_room(session, room_id, user.id)
    now = datetime.now(timezone.utc)
    jobs = list((await session.execute(
        select(PublicationJob).where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.status.in_(["pending", "dispatching", "queued", "running"]),
        )
    )).scalars())
    for job in jobs:
        was_running = job.status == "running"
        job.status = "pending_review" if was_running else "canceled"
        job.error = (
            "Room was skipped while the publication was running; verify Facebook"
            if was_running else "Room skipped by user"
        )
        job.finished_at = now
        job.next_retry_at = None
    room.status = "skipped"
    await session.flush()
    await session.refresh(room)
    return _room_dict(room)


@router.post("/rooms/{room_id}/retry", response_model=dict)
async def retry_room(
    room_id: uuid.UUID,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    room = await _owned_room(session, room_id, user.id)
    active_job = (await session.execute(
        select(PublicationJob.id).where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.status.in_(["dispatching", "queued", "running"]),
        ).limit(1)
    )).scalar_one_or_none()
    if active_job is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot retry while a publication job is running",
        )
    now = datetime.now(timezone.utc)
    retryable = list((await session.execute(
        select(PublicationJob).where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.status.in_(["failed", "canceled", "pending_review"]),
        )
    )).scalars())
    for job in retryable:
        job.status = "pending"
        job.attempt_count = 0
        job.scheduled_at = now
        job.next_retry_at = None
        job.task_run_id = None
        job.task_item_id = None
        job.facebook_post_id = None
        job.facebook_url = None
        job.result_message = None
        job.error = None
        job.claimed_at = None
        job.started_at = None
        job.finished_at = None
    room.status = "new"
    room.error = None
    room.retry_count = 0
    await session.flush()
    await session.refresh(room)
    return _room_dict(room)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _adapter() -> NhatrovnAdapter:
    """Seam so tests can monkeypatch `rental.NhatrovnAdapter`."""
    return NhatrovnAdapter()


async def _owned_config(session: AsyncSession, config_id: uuid.UUID, user_id: uuid.UUID) -> RentalConfig:
    row = await session.get(RentalConfig, config_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Rental config not found")
    return row


async def _owned_room(session: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> RentalRoom:
    row = await session.get(RentalRoom, room_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Rental room not found")
    return row


def _decrypt_credentials(row: RentalConfig) -> dict[str, str]:
    from app.crypto import decrypt
    plaintext = decrypt(row.source_credentials_enc)
    if not plaintext:
        raise HTTPException(status_code=500, detail="Stored rental credentials cannot be decrypted")
    try:
        return json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored rental credentials are invalid") from exc


async def _owned_writable_sheet_or_400(
    session: AsyncSession,
    connection_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> GoogleSheetConnection | None:
    if connection_id is None:
        return None
    connection = await session.get(GoogleSheetConnection, connection_id)
    if connection is None or connection.user_id != user_id:
        raise HTTPException(status_code=400, detail="Google Sheets connection not found")
    if connection.status != "connected":
        raise HTTPException(
            status_code=400,
            detail="Google Sheets connection must have write access",
        )
    return connection


def _config_dict(row: RentalConfig) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "source_type": row.source_type,
        "province_code": row.province_code,
        "province_name": row.province_name,
        "district_code": row.district_code,
        "district_name": row.district_name,
        "ward_code": row.ward_code,
        "ward_name": row.ward_name,
        "auto_post": row.auto_post,
        "post_spacing_seconds": row.post_spacing_seconds,
        "post_delay_seconds": row.post_delay_seconds,
        "caption_template": row.caption_template,
        "contact_phone": row.contact_phone,
        "group_match_level": row.group_match_level,
        "poll_interval_seconds": row.poll_interval_seconds,
        "timezone": row.timezone,
        "google_sheet_connection_id": str(row.google_sheet_connection_id) if row.google_sheet_connection_id else None,
        "status": row.status,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "last_sync_attempt_at": row.last_sync_attempt_at.isoformat() if row.last_sync_attempt_at else None,
        "last_post_at": row.last_post_at.isoformat() if row.last_post_at else None,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _room_dict(row: RentalRoom) -> dict:
    return {
        "id": str(row.id),
        "config_id": str(row.config_id),
        "external_room_id": row.external_room_id,
        "title": row.title,
        "price": row.price,
        "area_text": row.area_text,
        "address": row.address,
        "district": row.district,
        "ward": row.ward,
        "description": row.description,
        "images": json.loads(row.images_json or "[]"),
        "caption": row.caption,
        "matched_group_ids": json.loads(row.matched_group_ids_json) if row.matched_group_ids_json else [],
        "status": row.status,
        "post_urls": json.loads(row.post_urls_json) if row.post_urls_json else {},
        "posted_at": row.posted_at.isoformat() if row.posted_at else None,
        "retry_count": row.retry_count,
        "error": row.error,
        "source_status": row.source_status,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "media_paths": json.loads(row.media_paths_json or "[]"),
        "mirror_status": row.mirror_status,
        "mirror_error": row.mirror_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _publication_job_dict(row: PublicationJob) -> dict:
    return {
        "id": str(row.id),
        "rental_room_id": str(row.rental_room_id) if row.rental_room_id else None,
        "target_type": row.target_type,
        "target_id": str(row.target_id),
        "target_external_id": row.target_external_id,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
        "facebook_url": row.facebook_url,
        "error": row.error,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }
