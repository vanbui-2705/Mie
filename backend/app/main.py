"""
FlowMeta Backend — FastAPI app bootstrap.

Startup:  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Endpoints (see app/routers/* for full list):
  GET  /api/health              — health check (pg + redis)
  GET  /api/events/stream      — unified SSE (channels: log,stats,proxy,profile)
  POST /api/tasks/start         — start task run
  POST /api/tasks/stop/{run_id} — stop a task
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.auth import get_or_create_default_user, parse_token, _load_user_by_id
from app.config import settings
from app.db.postgres import close_db, get_session, session_context
from app.db.redis import close_redis
from app.event_bus import event_bus
from app.models.sqlmodels import FacebookAccount, Profile, UserStatus
from app.routers import auth, auth_oauth, browser_sessions, comment_tasks, extension_connector, facebook_accounts, facebook_oauth, graph, health, page_tasks, profiles, proxy, roles, scheduled_posts, settings as settings_router, tasks
from app.services.profile_manager import ProfileManager
from app.services.proxy_manager import ProxyManager
from app.services.scheduled_post_service import enqueue_due_posts
from app.services.task_runner import TaskRunner
from sqlalchemy import func, select


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    pm = ProxyManager()
    profile_mgr = ProfileManager()

    async with session_context() as session:
        await _migrate_legacy_profiles(session)
        await profile_mgr.reload_cache(session)

    runner = TaskRunner(
        get_session=get_session,
        proxy_manager=pm,
        publish=event_bus.publish,
    )

    app.state.proxy_manager = pm
    app.state.profile_manager = profile_mgr
    app.state.task_runner = runner

    # wire singletons into router modules
    tasks._task_runner = runner
    proxy._proxy_manager = pm
    scheduler_task = asyncio.create_task(_scheduler_tick())
    app.state.scheduler_task = scheduler_task

    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

    # Shutdown — ordered
    await pm.stop_async()
    await close_redis()
    await close_db()


async def _migrate_legacy_profiles(session) -> None:
    user = await get_or_create_default_user(session)
    result = await session.execute(select(Profile).order_by(Profile.uid))
    profiles = result.scalars().all()
    changed = False
    for profile in profiles:
        exists = await session.execute(
            select(FacebookAccount.id).where(
                FacebookAccount.user_id == user.id,
                func.lower(FacebookAccount.uid) == profile.uid.lower(),
            )
        )
        if exists.scalar_one_or_none() is not None:
            continue
        session.add(FacebookAccount(
            user_id=user.id,
            uid=profile.uid,
            user_token_enc=profile.token_enc,
            token_status=profile.token_status,
            last_error=profile.last_error,
        ))
        changed = True
    if changed:
        await session.commit()


async def _scheduler_tick() -> None:
    log = logging.getLogger("flowmeta.scheduler")
    while True:
        try:
            fired = await enqueue_due_posts()
            if fired:
                log.info("scheduled posts fired: %s", fired)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick error")
        await asyncio.sleep(60)


# ─── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Route registration ────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(auth_oauth.router)
app.include_router(roles.router)
app.include_router(browser_sessions.router)
app.include_router(profiles.router)
app.include_router(facebook_accounts.router)
app.include_router(facebook_oauth.router)
app.include_router(comment_tasks.router)
app.include_router(tasks.router)
app.include_router(page_tasks.router)
app.include_router(scheduled_posts.router)
app.include_router(extension_connector.router)
app.include_router(proxy.router)
app.include_router(graph.router)
app.include_router(settings_router.router)


# ─── Unified SSE endpoint ──────────────────────────────────────────────────────

@app.get("/api/events/stream")
async def stream_events(
    request: Request,
    channels: str = "log",
    last_id: str | None = None,
    token: str | None = None,
):
    """
    Multiplexed SSE endpoint.
    GET /api/events/stream?channels=log,stats,proxy,profile&token=<jwt>&last_id=evt-000042
    """
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token is required")
    try:
        user_id = parse_token(token)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        async with session_context() as session:
            user = await _load_user_by_id(session, user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise HTTPException(status_code=401, detail="User not found or disabled")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed")

    wanted = [c.strip() for c in channels.split(",") if c.strip()]

    async def event_stream():
        # Create one subscription per channel, merge via asyncio.Queue
        merge_q: asyncio.Queue = asyncio.Queue(maxsize=500)
        consumers: list[asyncio.Task] = []

        async def _forward(channel: str) -> None:
            gen = event_bus.subscribe(channel, last_id, user_id=user_id)
            try:
                async for event_id, event_type, data in gen:
                    if event_type == "ping":
                        await merge_q.put(("", "ping", None))
                    elif event_type == "reset":
                        await merge_q.put(("", "reset", {"reason": "stale"}))
                    else:
                        await merge_q.put((event_id, event_type, data))
            except StopAsyncIteration:
                pass
            except Exception:
                pass

        for ch in wanted:
            consumers.append(asyncio.ensure_future(_forward(ch)))

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_id, event_type, data = await asyncio.wait_for(
                        merge_q.get(), timeout=30
                    )
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                if event_type == "ping":
                    yield ": ping\n\n"
                elif event_type == "reset":
                    payload = _json({"reason": "stale_event_id"})
                    yield f"event: reset\ndata: {payload}\n\n"
                else:
                    payload = _json(data) if data is not None else ""
                    yield f"event: {event_type}\nid: {event_id}\ndata: {payload}\n\n"
        finally:
            for task in consumers:
                task.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


# ─── Root ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
