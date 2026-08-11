"""Fixed-window counters for the endpoints an attacker can call without a token.

Redis holds the counter so every API process shares one window — a per-process
limiter is worth 1/N of its stated limit once the app scales out. When Redis is
unreachable the limiter falls back to an in-process dict rather than letting the
request through: a broken cache must not silently disable the throttle.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from app.config import settings
from app.db.redis import get_redis

logger = logging.getLogger("flowmeta.rate_limit")

_PREFIX = "ratelimit:"

# key -> (window_started_at, count). Only used when Redis is unavailable.
_local: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

# A refused connection still costs seconds in retries, and this code sits in
# front of the login form. After one failure, stop asking for a while and serve
# from the in-process counters instead of making every sign-in pay the timeout.
_REDIS_RETRY_AFTER_SEC = 30.0
_redis_down_until = 0.0


class RateLimited(HTTPException):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=429,
            detail="Quá nhiều yêu cầu. Vui lòng thử lại sau ít phút.",
            headers={"Retry-After": str(max(1, retry_after))},
        )


def reset_local_state() -> None:
    """Drop the in-process counters and re-arm the Redis probe. For tests."""
    global _redis_down_until
    _local.clear()
    _redis_down_until = 0.0


def client_key(request: Request, *, scope: str, identity: str = "") -> str:
    """Bucket by client address, narrowed by whatever the caller is naming.

    `X-Forwarded-For` is trusted only when the deployment sets a proxy in front
    of the API — an attacker who can forge the header can otherwise mint a
    fresh bucket per request and the limit means nothing.
    """
    host = ""
    if settings.TRUST_PROXY_HEADERS:
        host = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not host:
        host = request.client.host if request.client else "unknown"
    suffix = identity.strip().lower()
    return f"{scope}:{host}:{suffix}" if suffix else f"{scope}:{host}"


async def check_rate_limit(key: str, *, limit: int, window_sec: int) -> None:
    """Count one hit against `key`; raise `RateLimited` once it passes `limit`.

    A limit of 0 or less turns the check off, which is how the settings disable
    throttling for a local dev box.
    """
    global _redis_down_until
    if limit <= 0:
        return
    if time.monotonic() >= _redis_down_until:
        try:
            redis = await get_redis()
            full_key = f"{_PREFIX}{key}"
            count = await redis.incr(full_key)
            if count == 1:
                await redis.expire(full_key, window_sec)
            if count > limit:
                raise RateLimited(await redis.ttl(full_key) or window_sec)
            return
        except RateLimited:
            raise
        except Exception as exc:  # Redis down, misconfigured, or not running.
            _redis_down_until = time.monotonic() + _REDIS_RETRY_AFTER_SEC
            logger.warning("rate limiter falling back to in-process counters (%s)", exc)

    now = time.monotonic()
    started, count = _local[key]
    if now - started >= window_sec:
        started, count = now, 0
    count += 1
    _local[key] = (started, count)
    if count > limit:
        raise RateLimited(int(window_sec - (now - started)))


async def clear_rate_limit(key: str) -> None:
    """Forget the counter for `key` — call it when the attempt succeeded.

    Without this a user who mistypes a password twice and then gets it right
    stays two attempts away from a lockout for the rest of the window.
    """
    _local.pop(key, None)
    if time.monotonic() < _redis_down_until:
        return
    try:
        redis = await get_redis()
        await redis.delete(f"{_PREFIX}{key}")
    except Exception:
        return
