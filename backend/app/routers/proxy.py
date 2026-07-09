"""Proxy management router — CRUD for KiotProxy API keys + monitor control."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt, mask
from app.db.postgres import get_session
from app.models.sqlmodels import ProxyKey
from app.schemas import ProxyKeyCreate, ProxyKeyResponse
from app.services.proxy_manager import ProxyManager

router = APIRouter(prefix="/api/proxy", tags=["proxy"])

# injected by main.py
_proxy_manager: ProxyManager | None = None


def _get_pm() -> ProxyManager:
    if _proxy_manager is None:
        raise RuntimeError("ProxyManager not initialized")
    return _proxy_manager


@router.get("/keys", response_model=List[ProxyKeyResponse])
async def list_keys(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(ProxyKey).order_by(ProxyKey.id))
    rows = result.scalars().all()
    return [_proxy_key_to_response(p) for p in rows]


@router.post("/keys", response_model=ProxyKeyResponse)
async def add_key(
    body: ProxyKeyCreate,
    session: AsyncSession = Depends(get_session),
):
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")

    masked = mask(api_key)
    enc = encrypt(api_key)
    pk = ProxyKey(
        api_key_enc=enc,
        masked_key=masked,
    )
    session.add(pk)
    try:
        await session.commit()
        await session.refresh(pk)
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="API key already exists")
    return _proxy_key_to_response(pk)


@router.post("/keys/import", response_model=dict)
async def import_keys(
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    raw_text = str(body.get("raw_text") or body.get("text") or "")
    lines = [line.strip() for line in raw_text.replace("\r\n", "\n").split("\n") if line.strip()]
    added = 0
    duplicate = 0
    errors: list[str] = []
    for api_key in lines:
        masked = mask(api_key)
        exists = await session.execute(select(ProxyKey.id).where(ProxyKey.masked_key == masked))
        if exists.scalar_one_or_none() is not None:
            duplicate += 1
            continue
        session.add(ProxyKey(api_key_enc=encrypt(api_key), masked_key=masked))
        added += 1
    try:
        await session.commit()
    except Exception as ex:
        await session.rollback()
        errors.append(str(ex))
    return {"total": len(lines), "added": added, "duplicate": duplicate, "errors": errors}


@router.delete("/keys/{key_id}", response_model=dict)
async def remove_key(key_id: int, session: AsyncSession = Depends(get_session)):
    stmt = delete(ProxyKey).where(ProxyKey.id == key_id)
    result = await session.execute(stmt)
    await session.commit()
    count = result.row_count if result.row_count is not None else 0
    if count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"removed": True}


@router.delete("/keys", response_model=dict)
async def remove_all_keys(session: AsyncSession = Depends(get_session)):
    result = await session.execute(delete(ProxyKey))
    await session.commit()
    return {"removed": result.rowcount or 0}


@router.post("/monitor/start", response_model=dict)
async def start_monitor(
    body: dict | None = Body(default=None),
    auth_token: str = "",
    get_new_url: str = "",
    get_current_url: str = "",
    uses_per_proxy: int = 4,
    check_interval: int = 5,
    session: AsyncSession = Depends(get_session),
):
    if body:
        auth_token = str(body.get("auth_token") or auth_token or "")
        get_new_url = str(body.get("get_new_url") or get_new_url or "")
        get_current_url = str(body.get("get_current_url") or get_current_url or "")
        uses_per_proxy = int(body.get("uses_per_proxy") or uses_per_proxy)
        check_interval = int(body.get("check_interval") or check_interval)
    pm = _get_pm()
    # Load keys from DB
    result = await session.execute(select(ProxyKey.api_key_enc).order_by(ProxyKey.id))
    enc_keys = [r[0] for r in result.all()]
    raw_keys = "\n".join(decrypt(enc) for enc in enc_keys)
    pm.configure(raw_keys)
    # load settings
    settings_row = await _get_app_settings(session)
    url_new = get_new_url or settings_row.get("get_new_url_template", "")
    url_cur = get_current_url or settings_row.get("get_current_url_template", "")
    pm.start(
        auth_token=auth_token or settings_row.get("kiot_auth_token", ""),
        get_new_url=url_new,
        get_current_url=url_cur,
        uses_per_proxy=uses_per_proxy or settings_row.get("uses_per_proxy", 4),
        check_interval=check_interval or settings_row.get("proxy_check_interval", 5),
    )
    return {"started": True}


@router.post("/monitor/stop", response_model=dict)
async def stop_monitor():
    pm = _get_pm()
    await pm.stop_async()
    return {"stopped": True}


@router.get("/status", response_model=List[ProxyKeyResponse])
async def proxy_status():
    pm = _get_pm()
    snap = pm.snapshot()
    return [_snapshot_to_response(s) for s in snap]


# -- helpers ---------------------------------------------------------------

async def _get_app_settings(session: AsyncSession) -> dict:
    result = await session.execute(
        text("SELECT * FROM app_settings WHERE id = 1")
    )
    row = result.mappings().fetchone()
    if not row:
        return {}
    from app.crypto import decrypt
    return {
        "kiot_auth_token": decrypt(row.get("kiot_auth_token_enc") or ""),
        "get_new_url_template": row.get("get_new_url_template", ""),
        "get_current_url_template": row.get("get_current_url_template", ""),
        "uses_per_proxy": row.get("uses_per_proxy", 4),
        "proxy_check_interval": row.get("proxy_check_interval", 5),
    }


def _proxy_key_to_response(pk: ProxyKey) -> ProxyKeyResponse:
    from app.crypto import decrypt as dc
    endpoint = None
    if pk.endpoint_host:
        endpoint = {
            "host": pk.endpoint_host,
            "port": pk.endpoint_port or 0,
            "username": None,
            "password": None,
            "display": pk.endpoint_display or "",
            "expires_at": pk.endpoint_expires_at.isoformat() if pk.endpoint_expires_at else None,
        }
    return ProxyKeyResponse(
        id=pk.id,
        masked_api_key=pk.masked_key,
        current_proxy=pk.current_proxy,
        remaining_uses=pk.remaining_uses,
        reserved_uses=pk.reserved_uses,
        status=pk.status,
        ip_expires_at=pk.endpoint_expires_at,
        last_error=pk.last_error,
        endpoint=endpoint,
    )


def _snapshot_to_response(s: dict) -> ProxyKeyResponse:
    endpoint = None
    if s.get("endpoint_host"):
        endpoint = {
            "host": s["endpoint_host"],
            "port": s["endpoint_port"] or 0,
            "username": None,
            "password": None,
            "display": s.get("endpoint_display", ""),
            "expires_at": s.get("endpoint_expires_at"),
        }
    return ProxyKeyResponse(
        id=s.get("id", 0),
        masked_api_key=s.get("masked_api_key", ""),
        current_proxy=s.get("current_proxy", ""),
        remaining_uses=s.get("remaining_uses", 0),
        reserved_uses=s.get("reserved_uses", 0),
        status=s.get("status", ""),
        ip_expires_at=s.get("ip_expires_at"),
        last_error=s.get("last_error"),
        endpoint=endpoint,
    )


def _decrypt(token: str) -> str:
    from app.crypto import decrypt as dc
    return dc(token)
