"""Rental (Đăng trọ tự động) config/room management endpoints."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt
from app.db.postgres import get_session, session_context
from app.models.sqlmodels import RentalConfig, RentalRoom, User
from app.rbac import require_permission
from app.services.nhatrovn_adapter import NhatrovnAdapter, NhatrovnError
from app.services.rental_post import RentalPostService
from app.services.rental_sync import RentalSyncService

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
    body: dict,
    user: User = Depends(require_permission("rental:create")),
    session: AsyncSession = Depends(get_session),
):
    credentials = _credentials_or_400(body.get("credentials"), require=True)
    _required_fields_or_400(body)

    row = RentalConfig(
        user_id=user.id,
        name=str(body.get("name") or "").strip(),
        source_type="nhatrovn",
        source_credentials_enc=encrypt(json.dumps(credentials)),
        province_code=str(body["province_code"]),
        province_name=str(body["province_name"]),
        district_code=str(body["district_code"]),
        district_name=str(body["district_name"]),
        ward_code=body.get("ward_code"),
        ward_name=body.get("ward_name"),
        caption_template=str(body.get("caption_template") or ""),
        contact_phone=str(body.get("contact_phone") or ""),
        post_spacing_seconds=int(body.get("post_spacing_seconds", 480)),
        poll_interval_seconds=int(body.get("poll_interval_seconds", 300)),
        auto_post=bool(body.get("auto_post", True)),
        google_sheet_connection_id=_uuid_or_none(body.get("google_sheet_connection_id")),
        timezone=str(body.get("timezone") or "Asia/Ho_Chi_Minh"),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _config_dict(row)


@router.put("/configs/{config_id}", response_model=dict)
async def update_config(
    config_id: uuid.UUID,
    body: dict,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_config(session, config_id, user.id)
    raw_credentials = body.get("credentials")
    if raw_credentials is not None:
        credentials = _credentials_or_400(raw_credentials, require=True)
        row.source_credentials_enc = encrypt(json.dumps(credentials))

    if "name" in body:
        row.name = str(body.get("name") or row.name).strip()
    if "province_code" in body:
        row.province_code = str(body["province_code"])
    if "province_name" in body:
        row.province_name = str(body["province_name"])
    if "district_code" in body:
        row.district_code = str(body["district_code"])
    if "district_name" in body:
        row.district_name = str(body["district_name"])
    if "ward_code" in body:
        row.ward_code = body.get("ward_code")
    if "ward_name" in body:
        row.ward_name = body.get("ward_name")
    if "caption_template" in body:
        row.caption_template = str(body.get("caption_template") or "")
    if "contact_phone" in body:
        row.contact_phone = str(body.get("contact_phone") or "")
    if "post_spacing_seconds" in body:
        row.post_spacing_seconds = int(body["post_spacing_seconds"])
    if "poll_interval_seconds" in body:
        row.poll_interval_seconds = int(body["poll_interval_seconds"])
    if "auto_post" in body:
        row.auto_post = bool(body["auto_post"])
    if "google_sheet_connection_id" in body:
        row.google_sheet_connection_id = _uuid_or_none(body.get("google_sheet_connection_id"))
    if "timezone" in body:
        row.timezone = str(body.get("timezone") or row.timezone)

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
    result = await RentalSyncService(session_context).sync_config(config_id)
    return result


@router.post("/configs/{config_id}/post-now", response_model=dict)
async def post_now(
    config_id: uuid.UUID,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    await _owned_config(session, config_id, user.id)
    fired = await RentalPostService(session_context).post_due()
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

@router.post("/rooms/{room_id}/assign-groups", response_model=dict)
async def assign_groups(
    room_id: uuid.UUID,
    body: dict,
    user: User = Depends(require_permission("rental:update")),
    session: AsyncSession = Depends(get_session),
):
    room = await _owned_room(session, room_id, user.id)
    group_ids = body.get("group_ids")
    if not isinstance(group_ids, list):
        raise HTTPException(status_code=400, detail="group_ids must be a list")
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


def _required_fields_or_400(body: dict) -> None:
    required = ("name", "credentials", "province_code", "province_name", "district_code", "district_name")
    missing = [field for field in required if not body.get(field)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")


def _credentials_or_400(value, *, require: bool) -> dict[str, str]:
    if value is None:
        if require:
            raise HTTPException(status_code=400, detail="Source credentials are required")
        return {}
    if not isinstance(value, dict) or not value.get("username") or not value.get("password"):
        raise HTTPException(status_code=400, detail="Credentials must include username and password")
    return {"username": str(value["username"]), "password": str(value["password"])}


def _decrypt_credentials(row: RentalConfig) -> dict[str, str]:
    from app.crypto import decrypt
    plaintext = decrypt(row.source_credentials_enc)
    if not plaintext:
        raise HTTPException(status_code=500, detail="Stored rental credentials cannot be decrypted")
    try:
        return json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored rental credentials are invalid") from exc


def _uuid_or_none(value) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid google_sheet_connection_id") from exc


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
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
