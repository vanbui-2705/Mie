"""Health check router."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.sqlmodels import PublicationJob, SheetCampaign, RentalConfig, User
from app.rbac import require_permission
from app.schemas import HealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health_check(session: AsyncSession = Depends(get_session)):
    pg_status = "ok"
    redis_status = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        pg_status = "error"
    try:
        r = await get_redis()
        await r.ping()
    except Exception:
        redis_status = "error"

    status = "ok" if pg_status == "ok" and redis_status == "ok" else "degraded"
    return HealthResponse(status=status, postgres=pg_status, redis=redis_status)


@router.get("/publication", response_model=dict)
async def publication_health(
    user: User = Depends(require_permission("task:read")),
    session: AsyncSession = Depends(get_session),
):
    counts = {
        str(status): int(count)
        for status, count in (await session.execute(
            select(PublicationJob.status, func.count(PublicationJob.id))
            .where(PublicationJob.user_id == user.id)
            .group_by(PublicationJob.status)
        )).all()
    }
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=30)
    stale = int((await session.execute(
        select(func.count(PublicationJob.id)).where(
            PublicationJob.user_id == user.id,
            PublicationJob.status.in_(["dispatching", "queued", "running"]),
            PublicationJob.started_at <= stale_before,
        )
    )).scalar_one())
    sheet_errors = int((await session.execute(
        select(func.count(SheetCampaign.id)).where(
            SheetCampaign.user_id == user.id,
            SheetCampaign.status == "error",
        )
    )).scalar_one())
    rental_errors = int((await session.execute(
        select(func.count(RentalConfig.id)).where(
            RentalConfig.user_id == user.id,
            RentalConfig.status == "error",
        )
    )).scalar_one())
    return {
        "publication_jobs": counts,
        "stale_jobs": stale,
        "sheet_campaign_errors": sheet_errors,
        "rental_config_errors": rental_errors,
    }
