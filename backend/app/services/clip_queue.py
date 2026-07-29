"""Redis-backed queue for Flow Studio clip jobs.

Deliberately a SEPARATE key from the comment worker's queue so the Face
worker and the Flow worker never steal each other's jobs.
"""
from __future__ import annotations

import json
from typing import Any

from app.db.redis import get_redis

CLIP_QUEUE_KEY = "flowmeta:clip_queue"


def build_clip_job(job_id: str) -> dict[str, Any]:
    return {"type": "clip_job", "job_id": job_id}


async def enqueue_clip_job(payload: dict[str, Any]) -> int:
    redis = await get_redis()
    return int(await redis.rpush(CLIP_QUEUE_KEY, json.dumps(payload, ensure_ascii=False)))


async def dequeue_clip_job(timeout_seconds: int = 5) -> dict[str, Any] | None:
    redis = await get_redis()
    item = await redis.blpop(CLIP_QUEUE_KEY, timeout=timeout_seconds)
    if item is None:
        return None
    _, raw_payload = item
    return json.loads(raw_payload)
