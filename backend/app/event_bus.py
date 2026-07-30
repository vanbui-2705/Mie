"""SSE event bus — per-channel publish/subscribe, fanned out across processes.

Delivery inside one process is a plain in-memory queue. That is not enough on
its own: the worker that runs a clip job and the API process that holds the
browser's SSE connection are different processes, so an event published by the
worker would never reach the page. Every publish is therefore also mirrored on
Redis pub/sub, and each process runs a relay that injects what the *other*
processes published into its own subscribers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any, AsyncGenerator

from app.config import settings
from app.db.redis import get_redis
from app.schemas import LogEventData, ProxyEventData, ProfileEventData, StatsEventData

logger = logging.getLogger("flowmeta.event_bus")

# --- types ---
Channel = str
EventType = str
EventId = str

ReplayEvent = tuple[float, EventId, EventType, Any]


class EventBus:
    """Thread-safe (asyncio-safe) fan-out pub/sub for SSE channels."""

    def __init__(self) -> None:
        self._subscribers: dict[Channel, list[asyncio.Queue]] = defaultdict(list)
        self._history: dict[Channel, deque[ReplayEvent]] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._counter: int = 0
        self._lock = asyncio.Lock()
        # Identifies this process so the relay can skip its own echo, and keeps
        # event ids from two processes out of each other's way.
        self._origin = uuid.uuid4().hex[:8]

    @property
    def origin(self) -> str:
        return self._origin

    def _next_id(self) -> EventId:
        self._counter += 1
        return f"evt-{self._origin}-{self._counter:06d}"

    def _deliver(self, channel: Channel, event_id: EventId, event_type: EventType, data: Any) -> None:
        """Hand an event to this process's subscribers and to the replay log."""
        self._history[channel].append((time.monotonic(), event_id, event_type, data))
        dead: list[asyncio.Queue] = []
        for q in list(self._subscribers[channel]):
            try:
                q.put_nowait((event_id, event_type, data))
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers[channel].remove(q)

    async def publish(self, channel: Channel, event_type: EventType, data: Any) -> EventId:
        event_id = self._next_id()
        self._deliver(channel, event_id, event_type, data)
        await self._fanout(channel, event_id, event_type, data)
        return event_id

    async def _fanout(self, channel: Channel, event_id: EventId, event_type: EventType, data: Any) -> None:
        """Mirror the event to the other processes. Never fatal: a page that
        misses a progress event still has the poll fallback, but a job that
        cannot publish must not fail because of it."""
        if not settings.SSE_REDIS_FANOUT:
            return
        try:
            redis = await get_redis()
            await redis.publish(
                f"{settings.SSE_REDIS_PREFIX}{channel}",
                json.dumps(
                    {"origin": self._origin, "id": event_id, "type": event_type, "data": data},
                    ensure_ascii=False,
                    default=str,
                ),
            )
        except Exception:
            logger.debug("SSE fan-out to Redis failed for channel %s", channel, exc_info=True)

    async def run_relay(self, channels: list[str]) -> None:
        """Inject events published by other processes. Runs until cancelled."""
        if not settings.SSE_REDIS_FANOUT or not channels:
            return
        names = [f"{settings.SSE_REDIS_PREFIX}{c}" for c in channels]
        while True:
            pubsub = None
            try:
                redis = await get_redis()
                pubsub = redis.pubsub(ignore_subscribe_messages=True)
                await pubsub.subscribe(*names)
                logger.info("SSE relay listening on %s", ", ".join(names))
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                    except (TypeError, ValueError):
                        continue
                    # Our own publish already reached local subscribers.
                    if payload.get("origin") == self._origin:
                        continue
                    channel = str(message["channel"]).removeprefix(settings.SSE_REDIS_PREFIX)
                    self._deliver(
                        channel,
                        str(payload.get("id") or ""),
                        str(payload.get("type") or "message"),
                        payload.get("data"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("SSE relay dropped, retrying in 5s", exc_info=True)
                await asyncio.sleep(5)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass

    async def subscribe(
        self, channel: Channel, last_id: str | None = None, user_id: object | None = None,
    ) -> AsyncGenerator[tuple[EventId, EventType, Any], None]:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers[channel].append(q)
        replay_started = False
        ping_task: "asyncio.Task[None] | None" = None
        try:
            if last_id is not None:
                found = False
                for _ts, eid, etype, data in self._history[channel]:
                    if eid == last_id:
                        found = True
                        continue
                    if found and self._belongs_to_user(data, user_id):
                        yield (eid, etype, data)
                if found:
                    replay_started = True
                else:
                    yield ("", "reset", {"reason": "stale_event_id"})

            ping_task = asyncio.create_task(self._ping_loop(q))
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=30.0)
                    if self._belongs_to_user(item[2], user_id):
                        yield item
                except asyncio.TimeoutError:
                    yield ("", "ping", None)
                except asyncio.CancelledError:
                    return
        finally:
            if q in self._subscribers[channel]:
                self._subscribers[channel].remove(q)
            if ping_task is not None:
                ping_task.cancel()

    @staticmethod
    def _belongs_to_user(data: Any, user_id: object | None) -> bool:
        if user_id is None:
            return True
        return isinstance(data, dict) and str(data.get("user_id") or "") == str(user_id)

    @staticmethod
    async def _ping_loop(q: asyncio.Queue) -> None:
        while True:
            await asyncio.sleep(25)
            try:
                q.put_nowait(("", "ping", None))
            except asyncio.Full:
                pass


event_bus = EventBus()
