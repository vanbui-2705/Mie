"""Google Sheet campaign, source queue and publication-job APIs."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session, session_context
from app.models.sqlmodels import (
    FacebookAccount,
    FacebookGroup,
    FacebookPage,
    GoogleSheetConnection,
    PublicationJob,
    SheetCampaign,
    SheetSourceItem,
    User,
)
from app.rbac import require_permission
from app.schemas.google_sheet_campaigns import SheetCampaignCreate, SheetCampaignUpdate
from app.services.sheet_post import SheetPostService
from app.services.sheet_sync import SheetSyncBusy, SheetSyncError, sync_sheet_campaign


router = APIRouter(prefix="/api/sheet-campaigns", tags=["sheet-campaigns"])


@router.get("", response_model=list[dict])
async def list_campaigns(
    user: User = Depends(require_permission("google_sheet:read")),
    session: AsyncSession = Depends(get_session),
):
    rows = list((await session.execute(
        select(SheetCampaign)
        .where(SheetCampaign.user_id == user.id)
        .order_by(SheetCampaign.created_at.desc())
    )).scalars())
    return [_campaign_dict(row) for row in rows]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: SheetCampaignCreate,
    user: User = Depends(require_permission("google_sheet:create")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_writable_connection(session, body.connection_id, user.id)
    await _validate_owned_targets(session, body.default_targets, user.id)
    existing = (await session.execute(
        select(SheetCampaign.id).where(
            SheetCampaign.connection_id == body.connection_id
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="This Sheet already has a campaign")
    row = SheetCampaign(
        user_id=user.id,
        connection_id=body.connection_id,
        name=body.name,
        default_targets_json=json.dumps(body.default_targets),
        default_schedule_mode=body.default_schedule_mode,
        schedule_slots_json=json.dumps(body.schedule_slots),
        active_weekdays_json=json.dumps(body.active_weekdays),
        timezone=body.timezone,
        max_posts_per_day=body.max_posts_per_day,
        min_post_gap_seconds=body.min_post_gap_seconds,
        late_policy=body.late_policy,
        max_retries=body.max_retries,
        enabled=body.enabled,
        status="active" if body.enabled else "paused",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _campaign_dict(row)


@router.put("/{campaign_id}", response_model=dict)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: SheetCampaignUpdate,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_campaign(session, campaign_id, user.id)
    fields = body.model_fields_set
    if body.default_targets is not None:
        await _validate_owned_targets(session, body.default_targets, user.id)
    mapping = {
        "default_targets": "default_targets_json",
        "schedule_slots": "schedule_slots_json",
        "active_weekdays": "active_weekdays_json",
    }
    for field in fields:
        value = getattr(body, field)
        if value is None:
            continue
        target = mapping.get(field, field)
        setattr(row, target, json.dumps(value) if field in mapping else value)
    if "enabled" in fields:
        row.status = "active" if body.enabled else "paused"
    await session.commit()
    await session.refresh(row)
    return _campaign_dict(row)


@router.post("/{campaign_id}/sync", response_model=dict)
async def sync_campaign_now(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_campaign(session, campaign_id, user.id)
    try:
        return await sync_sheet_campaign(session_context, campaign_id)
    except SheetSyncBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SheetSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{campaign_id}/pause", response_model=dict)
async def pause_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_campaign(session, campaign_id, user.id)
    row.enabled = False
    row.status = "paused"
    await session.commit()
    return _campaign_dict(row)


@router.post("/{campaign_id}/resume", response_model=dict)
async def resume_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_campaign(session, campaign_id, user.id)
    row.enabled = True
    row.status = "active"
    row.last_error = None
    await session.commit()
    return _campaign_dict(row)


@router.delete("/{campaign_id}", response_model=dict)
async def delete_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:delete")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_campaign(session, campaign_id, user.id)
    await session.delete(row)
    await session.commit()
    return {"deleted": True, "id": str(campaign_id)}


@router.get("/{campaign_id}/items", response_model=list[dict])
async def list_source_items(
    campaign_id: uuid.UUID,
    item_status: str | None = Query(default=None, alias="status"),
    user: User = Depends(require_permission("google_sheet:read")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_campaign(session, campaign_id, user.id)
    query = select(SheetSourceItem).where(
        SheetSourceItem.campaign_id == campaign_id,
        SheetSourceItem.user_id == user.id,
    )
    if item_status:
        query = query.where(SheetSourceItem.status == item_status.lower())
    rows = list((await session.execute(
        query.order_by(SheetSourceItem.sheet_row_number)
    )).scalars())
    return [_source_dict(row) for row in rows]


@router.get("/{campaign_id}/jobs", response_model=list[dict])
async def list_publication_jobs(
    campaign_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:read")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_campaign(session, campaign_id, user.id)
    rows = list((await session.execute(
        select(PublicationJob)
        .join(SheetSourceItem, SheetSourceItem.id == PublicationJob.sheet_source_item_id)
        .where(
            SheetSourceItem.campaign_id == campaign_id,
            PublicationJob.user_id == user.id,
        )
        .order_by(PublicationJob.created_at.desc())
    )).scalars())
    return [_job_dict(row) for row in rows]


@router.post("/items/{source_item_id}/publish-now", response_model=dict)
async def publish_source_now(
    source_item_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    source = await _owned_source(session, source_item_id, user.id)
    fired = await SheetPostService(session_context).post_due(
        source_item_id=source.id,
        user_id=user.id,
        force=True,
    )
    return {"queued": fired}


@router.post("/items/{source_item_id}/cancel", response_model=dict)
async def cancel_source(
    source_item_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    source = await _owned_source(session, source_item_id, user.id)
    jobs = list((await session.execute(
        select(PublicationJob).where(
            PublicationJob.sheet_source_item_id == source.id,
            PublicationJob.status.in_(["pending", "dispatching", "queued", "running"]),
        )
    )).scalars())
    for job in jobs:
        job.status = "canceled"
        job.error = "Canceled by user"
    source.status = "canceled"
    await session.commit()
    return _source_dict(source)


async def _owned_writable_connection(session, connection_id, user_id):
    row = await session.get(GoogleSheetConnection, connection_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Google Sheets connection not found")
    if row.status != "connected":
        raise HTTPException(status_code=400, detail="Google Sheet must have write access")
    return row


async def _validate_owned_targets(session, targets, user_id) -> None:
    for value in targets:
        target_type, raw_id = value.split(":", 1)
        model = {
            "page": FacebookPage,
            "group": FacebookGroup,
            "personal": FacebookAccount,
        }[target_type]
        target = await session.get(model, uuid.UUID(raw_id))
        if target is None or target.user_id != user_id:
            raise HTTPException(status_code=400, detail=f"Target not found: {value}")
        if target_type == "group" and target.status != "available":
            raise HTTPException(
                status_code=400, detail=f"Facebook group is unavailable: {value}",
            )


async def _owned_campaign(session, campaign_id, user_id):
    row = await session.get(SheetCampaign, campaign_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Sheet campaign not found")
    return row


async def _owned_source(session, source_id, user_id):
    row = await session.get(SheetSourceItem, source_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Sheet source item not found")
    return row


def _campaign_dict(row):
    return {
        "id": str(row.id),
        "connection_id": str(row.connection_id),
        "name": row.name,
        "default_targets": json.loads(row.default_targets_json or "[]"),
        "default_schedule_mode": row.default_schedule_mode,
        "schedule_slots": json.loads(row.schedule_slots_json or "[]"),
        "active_weekdays": json.loads(row.active_weekdays_json or "[]"),
        "timezone": row.timezone,
        "max_posts_per_day": row.max_posts_per_day,
        "min_post_gap_seconds": row.min_post_gap_seconds,
        "late_policy": row.late_policy,
        "max_retries": row.max_retries,
        "enabled": row.enabled,
        "status": row.status,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "last_error": row.last_error,
    }


def _source_dict(row):
    return {
        "id": str(row.id),
        "campaign_id": str(row.campaign_id),
        "external_id": row.external_id,
        "sheet_row_number": row.sheet_row_number,
        "content": row.content,
        "media_urls": json.loads(row.media_urls_json or "[]"),
        "targets": json.loads(row.targets_json or "[]"),
        "schedule_mode": row.schedule_mode,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "source_version": row.source_version,
        "status": row.status,
        "validation_error": row.validation_error,
        "queued_at": row.queued_at.isoformat() if row.queued_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _job_dict(row):
    return {
        "id": str(row.id),
        "source_item_id": str(row.sheet_source_item_id),
        "source_version": row.source_version,
        "target_type": row.target_type,
        "target_id": str(row.target_id),
        "status": row.status,
        "attempt_count": row.attempt_count,
        "scheduled_at": row.scheduled_at.isoformat(),
        "facebook_url": row.facebook_url,
        "error": row.error,
    }
