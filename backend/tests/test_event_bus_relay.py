"""The clip pipeline publishes from the worker process; the browser's SSE
stream lives in the API process. These tests pin the bridge between them."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.event_bus import EventBus


class FakePubSub:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = messages
        self.subscribed: tuple[str, ...] = ()
        self.closed = False

    async def subscribe(self, *names: str) -> None:
        self.subscribed = names

    async def listen(self):
        for message in self._messages:
            yield message
        # Nothing more will arrive; block so the relay behaves like a live
        # connection instead of falling into its reconnect loop.
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.published: list[tuple[str, str]] = []
        self._messages = messages or []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    def pubsub(self, **_kwargs) -> FakePubSub:
        return FakePubSub(self._messages)


@pytest.mark.asyncio
async def test_publish_mirrors_the_event_to_redis(monkeypatch) -> None:
    bus = EventBus()
    redis = FakeRedis()
    monkeypatch.setattr("app.event_bus.get_redis", lambda: _ready(redis))

    event_id = await bus.publish("clip", "phase", {"user_id": "u1", "phase": "rendering"})

    assert len(redis.published) == 1
    channel, raw = redis.published[0]
    assert channel == "sse:clip"
    payload = json.loads(raw)
    assert payload["type"] == "phase"
    assert payload["id"] == event_id
    assert payload["origin"] == bus.origin
    assert payload["data"]["phase"] == "rendering"


@pytest.mark.asyncio
async def test_publish_survives_redis_being_down(monkeypatch) -> None:
    bus = EventBus()

    async def _boom():
        raise ConnectionError("redis is gone")

    monkeypatch.setattr("app.event_bus.get_redis", _boom)
    received: list[tuple[str, str, object]] = []

    async def reader():
        async for item in bus.subscribe("clip", user_id="u1"):
            received.append(item)
            return

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    # A job must not fail because the event bus cannot reach Redis.
    await bus.publish("clip", "done", {"user_id": "u1", "job_id": "j1"})
    await asyncio.wait_for(task, timeout=2)

    assert received[0][1] == "done"


@pytest.mark.asyncio
async def test_relay_delivers_events_from_another_process(monkeypatch) -> None:
    bus = EventBus()
    remote = {
        "type": "message",
        "channel": "sse:clip",
        "data": json.dumps(
            {"origin": "other-process", "id": "evt-abc-000001", "type": "clip_ready",
             "data": {"user_id": "u1", "clip_id": "c1"}}
        ),
    }
    echo = {
        "type": "message",
        "channel": "sse:clip",
        "data": json.dumps(
            {"origin": bus.origin, "id": "evt-self-000001", "type": "phase",
             "data": {"user_id": "u1", "phase": "scoring"}}
        ),
    }
    monkeypatch.setattr("app.event_bus.get_redis", lambda: _ready(FakeRedis([remote, echo])))

    received: list[tuple[str, str, object]] = []

    async def reader():
        async for item in bus.subscribe("clip", user_id="u1"):
            received.append(item)
            return

    reader_task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    relay_task = asyncio.create_task(bus.run_relay(["clip"]))
    await asyncio.wait_for(reader_task, timeout=2)
    relay_task.cancel()

    # The remote event arrives once; this process's own echo is dropped, since
    # publish() already delivered it locally.
    assert [(etype, data) for _id, etype, data in received] == [
        ("clip_ready", {"user_id": "u1", "clip_id": "c1"})
    ]


async def _ready(value):
    return value
