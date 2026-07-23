"""Google Sheets connection management endpoints."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.db.postgres import get_session
from app.models.sqlmodels import GoogleSheetConnection, User
from app.rbac import require_permission
from app.services.google_sheets import (
    GoogleSheetsClient,
    GoogleSheetsError,
    normalize_service_account_credentials,
    parse_spreadsheet_id,
    serialize_service_account_credentials,
)

router = APIRouter(prefix="/api/google-sheets", tags=["google-sheets"])


@router.get("/connections", response_model=list[dict])
async def list_connections(
    user: User = Depends(require_permission("google_sheet:read")),
    session: AsyncSession = Depends(get_session),
):
    rows = list((await session.execute(
        select(GoogleSheetConnection)
        .where(GoogleSheetConnection.user_id == user.id)
        .order_by(GoogleSheetConnection.created_at.desc())
    )).scalars())
    return [_connection_dict(row) for row in rows]


@router.post("/connections/test", response_model=dict)
async def test_new_connection(
    body: dict,
    user: User = Depends(require_permission("google_sheet:create")),
):
    credentials, spreadsheet_id, sheet_name = _connection_inputs(body, require_credentials=True)
    return await _inspect_or_400(credentials, spreadsheet_id, sheet_name)


@router.post("/connections", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: dict,
    user: User = Depends(require_permission("google_sheet:create")),
    session: AsyncSession = Depends(get_session),
):
    credentials, spreadsheet_id, sheet_name = _connection_inputs(body, require_credentials=True)
    inspected = await _inspect_or_400(credentials, spreadsheet_id, sheet_name)
    existing = (await session.execute(select(GoogleSheetConnection.id).where(
        GoogleSheetConnection.user_id == user.id,
        GoogleSheetConnection.spreadsheet_id == spreadsheet_id,
        GoogleSheetConnection.sheet_name == sheet_name,
    ))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="This Google Sheet is already connected")

    row = GoogleSheetConnection(
        user_id=user.id,
        name=_name(body, inspected.get("spreadsheet_title")),
        spreadsheet_id=spreadsheet_id,
        sheet_name=sheet_name,
        credentials_enc=encrypt(serialize_service_account_credentials(credentials)),
        service_account_email=credentials["client_email"],
        poll_interval_seconds=_poll_interval(body.get("poll_interval_seconds")),
        timezone=_timezone(body.get("timezone")),
        status="connected" if inspected.get("can_edit") else "read_only",
        last_error=None if inspected.get("can_edit") else "Service account has read-only access",
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return {**_connection_dict(row), "inspection": inspected}


@router.put("/connections/{connection_id}", response_model=dict)
async def update_connection(
    connection_id: uuid.UUID,
    body: dict,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_connection(session, connection_id, user.id)
    raw_credentials = body.get("credentials")
    if raw_credentials is None:
        credentials = _decrypt_credentials(row)
    else:
        credentials = _normalize_or_400(raw_credentials)
    spreadsheet_id = _spreadsheet_id_or_400(body.get("spreadsheet_url") or body.get("spreadsheet_id") or row.spreadsheet_id)
    sheet_name = str(body.get("sheet_name") or row.sheet_name).strip() or "Posts"
    inspected = await _inspect_or_400(credentials, spreadsheet_id, sheet_name)

    duplicate = (await session.execute(select(GoogleSheetConnection.id).where(
        GoogleSheetConnection.user_id == user.id,
        GoogleSheetConnection.spreadsheet_id == spreadsheet_id,
        GoogleSheetConnection.sheet_name == sheet_name,
        GoogleSheetConnection.id != row.id,
    ))).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="This Google Sheet is already connected")

    row.name = _name(body, inspected.get("spreadsheet_title"), fallback=row.name)
    row.spreadsheet_id = spreadsheet_id
    row.sheet_name = sheet_name
    row.credentials_enc = encrypt(serialize_service_account_credentials(credentials))
    row.service_account_email = credentials["client_email"]
    row.poll_interval_seconds = _poll_interval(body.get("poll_interval_seconds", row.poll_interval_seconds))
    row.timezone = _timezone(body.get("timezone", row.timezone))
    row.status = "connected" if inspected.get("can_edit") else "read_only"
    row.last_error = None if inspected.get("can_edit") else "Service account has read-only access"
    await session.flush()
    await session.refresh(row)
    return {**_connection_dict(row), "inspection": inspected}


@router.post("/connections/{connection_id}/test", response_model=dict)
async def test_saved_connection(
    connection_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:update")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_connection(session, connection_id, user.id)
    try:
        inspected = await GoogleSheetsClient().inspect_connection(
            credentials=_decrypt_credentials(row),
            spreadsheet_id=row.spreadsheet_id,
            sheet_name=row.sheet_name,
        )
    except GoogleSheetsError as exc:
        row.status = "error"
        row.last_error = str(exc)
        await session.flush()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row.status = "connected" if inspected.get("can_edit") else "read_only"
    row.last_error = None if inspected.get("can_edit") else "Service account has read-only access"
    await session.flush()
    return inspected


@router.delete("/connections/{connection_id}", response_model=dict)
async def delete_connection(
    connection_id: uuid.UUID,
    user: User = Depends(require_permission("google_sheet:delete")),
    session: AsyncSession = Depends(get_session),
):
    row = await _owned_connection(session, connection_id, user.id)
    await session.delete(row)
    await session.flush()
    return {"deleted": True, "id": str(connection_id)}


async def _owned_connection(
    session: AsyncSession, connection_id: uuid.UUID, user_id: uuid.UUID,
) -> GoogleSheetConnection:
    row = await session.get(GoogleSheetConnection, connection_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Google Sheets connection not found")
    return row


def _connection_inputs(body: dict, *, require_credentials: bool) -> tuple[dict[str, str], str, str]:
    raw_credentials = body.get("credentials")
    if require_credentials and raw_credentials is None:
        raise HTTPException(status_code=400, detail="Service-account credentials are required")
    credentials = _normalize_or_400(raw_credentials)
    spreadsheet_id = _spreadsheet_id_or_400(body.get("spreadsheet_url") or body.get("spreadsheet_id"))
    sheet_name = str(body.get("sheet_name") or "Posts").strip() or "Posts"
    if len(sheet_name) > 255:
        raise HTTPException(status_code=400, detail="Sheet name is too long")
    return credentials, spreadsheet_id, sheet_name


def _normalize_or_400(value) -> dict[str, str]:
    try:
        return normalize_service_account_credentials(value)
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _spreadsheet_id_or_400(value) -> str:
    try:
        return parse_spreadsheet_id(str(value or ""))
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _inspect_or_400(credentials: dict[str, str], spreadsheet_id: str, sheet_name: str) -> dict:
    try:
        return await GoogleSheetsClient().inspect_connection(
            credentials=credentials,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
        )
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _decrypt_credentials(row: GoogleSheetConnection) -> dict[str, str]:
    plaintext = decrypt(row.credentials_enc)
    if not plaintext:
        raise HTTPException(status_code=500, detail="Stored Google credentials cannot be decrypted")
    try:
        parsed = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored Google credentials are invalid") from exc
    return _normalize_or_400(parsed)


def _connection_dict(row: GoogleSheetConnection) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "spreadsheet_id": row.spreadsheet_id,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{row.spreadsheet_id}/edit",
        "sheet_name": row.sheet_name,
        "service_account_email": row.service_account_email,
        "poll_interval_seconds": row.poll_interval_seconds,
        "timezone": row.timezone,
        "status": row.status,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _poll_interval(value) -> int:
    try:
        parsed = int(value or 60)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid polling interval") from exc
    if parsed < 30 or parsed > 3600:
        raise HTTPException(status_code=400, detail="Polling interval must be between 30 and 3600 seconds")
    return parsed


def _timezone(value) -> str:
    parsed = str(value or "Asia/Ho_Chi_Minh").strip()
    if parsed not in {"Asia/Ho_Chi_Minh", "UTC"}:
        raise HTTPException(status_code=400, detail="Unsupported timezone")
    return parsed


def _name(body: dict, spreadsheet_title, *, fallback: str = "") -> str:
    parsed = str(body.get("name") or fallback or spreadsheet_title or "Google Sheets").strip()
    if not parsed:
        parsed = "Google Sheets"
    if len(parsed) > 255:
        raise HTTPException(status_code=400, detail="Connection name is too long")
    return parsed
