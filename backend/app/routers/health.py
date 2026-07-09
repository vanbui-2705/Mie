"""Health check router."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session
from app.db.redis import get_redis
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
