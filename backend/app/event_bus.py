"""In-memory SSE event bus — publish/subscribe per channel."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any, AsyncGenerator

from app.schemas import LogEventData, ProxyEventData, ProfileEventData, StatsEventData

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

    def _next_id(self) -> EventId:
        self._counter += 1
        return f"evt-{self._counter:06d}"

    async def publish(self, channel: Channel, event_type: EventType, data: Any) -> EventId:
        event_id = self._next_id()
        ts = time.monotonic()
        self._history[channel].append((ts, event_id, event_type, data))
        dead: list[asyncio.Queue] = []
        for q in list(self._subscribers[channel]):
            try:
                q.put_nowait((event_id, event_type, data))
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers[channel].remove(q)
        return event_id

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
