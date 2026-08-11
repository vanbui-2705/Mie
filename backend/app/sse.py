"""Shared SSE endpoint factory — mounts /api/events/stream on any app."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import parse_token, _load_user_by_id
from app.db.postgres import session_context
from app.event_bus import event_bus
from app.models.sqlmodels import UserStatus


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def register_sse_endpoint(app: FastAPI, *, channels_default: str = "clip") -> None:
    @app.get("/api/events/stream")
    async def stream_events(
        request: Request,
        channels: str = channels_default,
        last_id: str | None = None,
        token: str | None = None,
    ):
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
                except Exception:
                    pass

            for ch in wanted:
                consumers.append(asyncio.ensure_future(_forward(ch)))
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event_id, event_type, data = await asyncio.wait_for(merge_q.get(), timeout=30)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if event_type == "ping":
                        yield ": ping\n\n"
                    elif event_type == "reset":
                        yield f"event: reset\ndata: {_json({'reason': 'stale_event_id'})}\n\n"
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
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
