"""Flow Studio standalone FastAPI app (runs independently of Face).

    uvicorn app.flow_app:app --host 0.0.0.0 --port 8001
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.postgres import close_db
from app.db.redis import close_redis
from app.event_bus import event_bus
from app.modules.flow_video import api as flow_video_api
from app.modules.platform import api as platform_api
from app.sse import register_sse_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Flow needs no proxy/profile/scheduler machinery — just shared DB + Redis.
    # The relay is what makes progress live: the clip pipeline runs in
    # app.flow_worker, a different process, and publishes there.
    relay = asyncio.create_task(event_bus.run_relay(["clip"]))
    try:
        yield
    finally:
        relay.cancel()
        with suppress(asyncio.CancelledError):
            await relay
        await close_redis()
        await close_db()


app = FastAPI(title="Flow Studio API", version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(platform_api.health.router)
app.include_router(flow_video_api.clip_jobs.router)
register_sse_endpoint(app, channels_default="clip")
