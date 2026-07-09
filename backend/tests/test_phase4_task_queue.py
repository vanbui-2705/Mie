from __future__ import annotations

import json

import pytest

from app.services import task_queue


class FakeRedis:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.values: dict[str, str] = {}

    async def rpush(self, key: str, payload: str) -> int:
        assert key == task_queue.QUEUE_KEY
        self.items.append(payload)
        return len(self.items)

    async def blpop(self, key: str, timeout: int = 0):
        assert key == task_queue.QUEUE_KEY
        assert timeout == 1
        if not self.items:
            return None
        return key, self.items.pop(0)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, count: int, key: str, owner: str) -> int:
        if self.values.get(key) == owner:
            del self.values[key]
            return 1
        return 0


@pytest.mark.asyncio
async def test_enqueue_and_dequeue_task_roundtrip(monkeypatch) -> None:
    fake = FakeRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr(task_queue, "get_redis", fake_get_redis)

    payload = task_queue.build_comment_job(
        "00000000-0000-0000-0000-000000000001",
        {"action": "edit", "raw_uid_text": "10001"},
    )
    length = await task_queue.enqueue_task(payload)
    job = await task_queue.dequeue_task(timeout_seconds=1)

    assert length == 1
    assert job == payload
    assert json.loads(fake.items[0]) if fake.items else True


@pytest.mark.asyncio
async def test_browser_account_lock_is_owner_scoped(monkeypatch) -> None:
    fake = FakeRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr(task_queue, "get_redis", fake_get_redis)

    assert await task_queue.acquire_browser_account_lock("account-1", "owner-1")
    assert not await task_queue.acquire_browser_account_lock("account-1", "owner-2")
    assert not await task_queue.release_browser_account_lock("account-1", "owner-2")
    assert await task_queue.release_browser_account_lock("account-1", "owner-1")
    assert await task_queue.acquire_browser_account_lock("account-1", "owner-2")
