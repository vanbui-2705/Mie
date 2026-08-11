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
from app.modules.automation import api as automation_api
from app.modules.automation.runtime import TaskRunner, enqueue_due_posts
from app.modules.browser import api as browser_api
from app.modules.facebook import api as facebook_api
from app.modules.identity_access import api as identity_api
from app.modules.platform import api as platform_api
from app.modules.proxy_profiles import api as proxy_profiles_api
from app.modules.proxy_profiles.runtime import ProfileManager, ProxyManager
from app.modules.rental import api as rental_api
from app.modules.sheets import api as sheets_api
from sqlalchemy import func, select


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    # uvicorn configures its own loggers and leaves the root one bare, so
    # without this every logger under "flowmeta." writes into the void — which
    # is why the scheduler could run for hours without printing a line.
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
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
    automation_api.tasks._task_runner = runner
    proxy_profiles_api.proxy._proxy_manager = pm
    scheduler_task = asyncio.create_task(_scheduler_tick()) if settings.SCHEDULER_ENABLED else None
    app.state.scheduler_task = scheduler_task
    # app.worker publishes from its own process; without this relay none of its
    # events reach a browser connected to this one.
    relay_task = asyncio.create_task(
        event_bus.run_relay(["log", "stats", "proxy", "profile"])
    )
    app.state.sse_relay_task = relay_task

    try:
        yield
    finally:
        for task in (scheduler_task, relay_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
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
    ticks = 0
    while True:
        try:
            from app.services.sheet_sync import run_sheet_sync
            from app.services.sheet_post import SheetPostService
            from app.services.sheet_writeback import (
                recover_stale_writebacks,
                run_sheet_writebacks,
            )
            from app.services.rental_sync import run_rental_sync
            from app.services.rental_post import RentalPostService
            from app.services.rental_sheet_mirror import run_rental_sheet_mirror
            from app.services.publication_jobs import (
                reconcile_publication_jobs,
                recover_stale_publication_jobs,
            )

            await asyncio.gather(
                _run_scheduler_service("scheduled_posts", enqueue_due_posts(), log),
                _run_scheduler_service("sheet_sync", run_sheet_sync(session_context), log),
                _run_scheduler_service("rental_sync", run_rental_sync(), log),
            )
            await _run_scheduler_service(
                "publication_recovery",
                recover_stale_publication_jobs(session_context),
                log,
            )
            await _run_scheduler_service(
                "writeback_recovery",
                recover_stale_writebacks(session_context),
                log,
            )
            await _run_scheduler_service(
                "publication_reconcile",
                reconcile_publication_jobs(session_context),
                log,
            )
            await asyncio.gather(
                _run_scheduler_service(
                    "sheet_post", SheetPostService(session_context).post_due(), log,
                ),
                _run_scheduler_service(
                    "rental_post", RentalPostService(session_context).post_due(), log,
                ),
                _run_scheduler_service(
                    "sheet_writeback", run_sheet_writebacks(session_context), log,
                ),
                _run_scheduler_service(
                    "rental_sheet_mirror",
                    run_rental_sheet_mirror(session_context),
                    log,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick error")
        # An idle tick logs nothing at all, so silence used to mean either "no
        # work" or "the loop died" with no way to tell them apart.
        ticks += 1
        if ticks % 10 == 1:
            log.info("scheduler alive, tick %s", ticks)
        await asyncio.sleep(max(5, settings.SCHEDULER_INTERVAL_SECONDS))


async def _run_scheduler_service(
    name: str,
    operation,
    log: logging.Logger,
    timeout_seconds: int = 55,
):
    try:
        result = await asyncio.wait_for(operation, timeout=timeout_seconds)
        if result:
            log.info("scheduler service %s: %s", name, result)
        return result
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        log.error("scheduler service %s timed out after %ss", name, timeout_seconds)
    except Exception:
        log.exception("scheduler service %s failed", name)
    return None


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

app.include_router(platform_api.health.router)
app.include_router(identity_api.auth.router)
app.include_router(identity_api.auth_oauth.router)
app.include_router(identity_api.roles.router)
app.include_router(browser_api.browser_sessions.router)
app.include_router(proxy_profiles_api.profiles.router)
app.include_router(facebook_api.facebook_accounts.router)
app.include_router(facebook_api.facebook_oauth.router)
app.include_router(automation_api.comment_tasks.router)
app.include_router(automation_api.tasks.router)
app.include_router(automation_api.page_tasks.router)
app.include_router(automation_api.scheduled_posts.router)
app.include_router(sheets_api.google_sheets.router)
app.include_router(sheets_api.sheet_campaigns.router)
app.include_router(rental_api.rental.router)
app.include_router(browser_api.extension_connector.router)
app.include_router(proxy_profiles_api.proxy.router)
app.include_router(facebook_api.graph.router)
app.include_router(platform_api.settings_router.router)


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
        claims = parse_token(token)
        if claims is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        async with session_context() as session:
            user = await _load_user_by_id(session, *claims)
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
