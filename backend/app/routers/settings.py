"""Settings router — get/update app settings (single-row table)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.db.postgres import get_session
from app.models.sqlmodels import AppSetting
from app.schemas import AppSettingsResponse, AppSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=AppSettingsResponse)
async def get_settings(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(AppSetting).where(AppSetting.id == 1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        # bootstrap singleton
        row = AppSetting(id=1)
        session.add(row)
        await session.commit()
        await session.refresh(row)

    kiot_token = decrypt(row.kiot_auth_token_enc or "")
    masked = _mask(kiot_token) if kiot_token else ""
    return AppSettingsResponse(
        interaction_threads=row.interaction_threads,
        posts_per_uid=row.posts_per_uid,
        delay_min_seconds=row.delay_min_seconds,
        delay_max_seconds=row.delay_max_seconds,
        delay_every_rounds=row.delay_every_rounds,
        uses_per_proxy=row.uses_per_proxy,
        proxy_check_interval=row.proxy_check_interval,
        get_new_url_template=row.get_new_url_template,
        get_current_url_template=row.get_current_url_template,
        kiot_auth_token_masked=masked,
    )


@router.put("", response_model=dict)
async def update_settings(body: AppSettingsUpdate, session: AsyncSession = Depends(get_session)):
    values: dict = {}
    if body.interaction_threads:
        values["interaction_threads"] = body.interaction_threads
    if body.posts_per_uid:
        values["posts_per_uid"] = body.posts_per_uid
    if body.delay_min_seconds is not None:
        values["delay_min_seconds"] = body.delay_min_seconds
    if body.delay_max_seconds is not None:
        values["delay_max_seconds"] = body.delay_max_seconds
    if body.delay_every_rounds:
        values["delay_every_rounds"] = body.delay_every_rounds
    if body.uses_per_proxy:
        values["uses_per_proxy"] = body.uses_per_proxy
    if body.proxy_check_interval:
        values["proxy_check_interval"] = body.proxy_check_interval
    if body.get_new_url_template:
        values["get_new_url_template"] = body.get_new_url_template
    if body.get_current_url_template:
        values["get_current_url_template"] = body.get_current_url_template
    if body.kiot_auth_token is not None:
        values["kiot_auth_token_enc"] = encrypt(body.kiot_auth_token)

    if values:
        await session.execute(
            update(AppSetting).where(AppSetting.id == 1).values(**values)
        )
        await session.commit()
    return {"updated": True}


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}***{value[-4:]}"
