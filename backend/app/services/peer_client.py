"""Health-gated cross-module HTTP client.

Face and Flow run as separate processes. Either may be down. Every
cross-call first pings the peer's /api/health; if the peer is unreachable
the call degrades to None instead of raising — "call each other only if
both on."
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("flowmeta.peer")


async def peer_available(base_url: str) -> bool:
    timeout = settings.PEER_HEALTH_TIMEOUT_SECONDS
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/health")
            return 200 <= resp.status_code < 300
    except Exception:
        return False


async def call_peer(
    base_url: str,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    if not await peer_available(base_url):
        logger.info("peer %s unavailable; skipping %s %s", base_url, method, path)
        return None
    headers = {"Authorization": f"Bearer {token}"} if token else None
    url = f"{base_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=settings.PEER_HEALTH_TIMEOUT_SECONDS) as client:
            resp = await client.request(method, url, json=json, headers=headers)
            if 200 <= resp.status_code < 300:
                return resp.json()
            logger.warning("peer %s %s returned %s", method, url, resp.status_code)
            return None
    except Exception:
        logger.exception("peer call %s %s failed", method, url)
        return None
