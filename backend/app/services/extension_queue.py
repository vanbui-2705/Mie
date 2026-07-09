"""Redis-backed queue for Chrome Extension connector jobs."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.redis import get_redis

ONLINE_PREFIX = "flowmeta:extension_online:"
QUEUE_PREFIX = "flowmeta:extension_jobs:"


async def mark_extension_online(account_id: str, client_id: str, ttl_seconds: int = 45) -> None:
    redis = await get_redis()
    await redis.set(f"{ONLINE_PREFIX}{account_id}", client_id, ex=ttl_seconds)


async def is_extension_online(account_id: str) -> bool:
    redis = await get_redis()
    return bool(await redis.exists(f"{ONLINE_PREFIX}{account_id}"))


async def enqueue_extension_job(account_id: str, payload: dict[str, Any]) -> str:
    redis = await get_redis()
    job_id = str(payload.get("job_id") or uuid.uuid4())
    payload = {**payload, "job_id": job_id}
    await redis.rpush(f"{QUEUE_PREFIX}{account_id}", json.dumps(payload, ensure_ascii=False))
    return job_id


async def dequeue_extension_job(account_id: str, timeout_seconds: int = 20) -> dict[str, Any] | None:
    redis = await get_redis()
    item = await redis.blpop(f"{QUEUE_PREFIX}{account_id}", timeout=timeout_seconds)
    if item is None:
        return None
    _, raw_payload = item
    return json.loads(raw_payload)
