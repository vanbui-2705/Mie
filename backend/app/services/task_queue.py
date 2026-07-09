"""Redis-backed task queue used by the production worker."""
from __future__ import annotations

import json
from typing import Any

from app.db.redis import get_redis

QUEUE_KEY = "flowmeta:task_queue"
BROWSER_QUEUE_KEY = "flowmeta:browser_queue"
BROWSER_ACCOUNT_LOCK_PREFIX = "flowmeta:browser_account_lock:"


async def enqueue_task(payload: dict[str, Any]) -> int:
    """Push a JSON job to Redis and return the queue length."""
    redis = await get_redis()
    return int(await redis.rpush(QUEUE_KEY, json.dumps(payload, ensure_ascii=False)))


async def dequeue_task(timeout_seconds: int = 5) -> dict[str, Any] | None:
    """Pop one job from Redis. Returns None on timeout."""
    redis = await get_redis()
    item = await redis.blpop(QUEUE_KEY, timeout=timeout_seconds)
    if item is None:
        return None
    _, raw_payload = item
    return json.loads(raw_payload)


async def enqueue_browser_job(payload: dict[str, Any]) -> int:
    redis = await get_redis()
    return int(await redis.rpush(BROWSER_QUEUE_KEY, json.dumps(payload, ensure_ascii=False)))


async def dequeue_browser_job(timeout_seconds: int = 5) -> dict[str, Any] | None:
    redis = await get_redis()
    item = await redis.blpop(BROWSER_QUEUE_KEY, timeout=timeout_seconds)
    if item is None:
        return None
    _, raw_payload = item
    return json.loads(raw_payload)


async def acquire_browser_account_lock(account_id: str, owner: str, ttl_seconds: int = 900) -> bool:
    redis = await get_redis()
    return bool(await redis.set(f"{BROWSER_ACCOUNT_LOCK_PREFIX}{account_id}", owner, nx=True, ex=ttl_seconds))


async def release_browser_account_lock(account_id: str, owner: str) -> bool:
    redis = await get_redis()
    key = f"{BROWSER_ACCOUNT_LOCK_PREFIX}{account_id}"
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """
    return bool(await redis.eval(script, 1, key, owner))


def build_comment_job(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a stable queue payload for a comment/edit/delete task."""
    return {
        "type": "comment_task",
        "run_id": run_id,
        "payload": payload,
    }
