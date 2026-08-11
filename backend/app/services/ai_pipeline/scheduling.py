"""Concurrency slots, one per kind of resource.

Three kinds of work with three different limits:
- CPU: whisper, x264, OpenCV. More of these than cores makes everything slower.
- Network: yt-dlp, stock photo fetches. Bound by latency, not by cores.
- TTS: also network, but against an unofficial endpoint that must not be
  hammered, so it gets a smaller allowance of its own.

Semaphores are created lazily and torn down by `reset_slots()` because an
`asyncio.Semaphore` binds to the running loop, and the tests (and the worker's
restart path) do not share one loop.
"""
from __future__ import annotations

import asyncio
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import settings

_CPU: asyncio.Semaphore | None = None
_NET: asyncio.Semaphore | None = None
_TTS: asyncio.Semaphore | None = None


def cpu_slots() -> int:
    configured = int(settings.FLOW_CPU_SLOTS)
    if configured > 0:
        return configured
    # Leave one core for the event loop, the DB driver and the OS.
    return max(1, (os.cpu_count() or 2) - 1)


def net_slots() -> int:
    return max(1, int(settings.FLOW_NET_SLOTS))


def tts_slots() -> int:
    return max(1, int(settings.FLOW_TTS_SLOTS))


def ffmpeg_threads(parallel: int | None = None) -> int:
    """Threads for one ffmpeg process.

    Without this, N concurrent encodes each grab every core and spend their
    time fighting each other — concurrency that is slower than running them
    one at a time.

    `parallel` is how many encodes will actually run at once. Dividing by the
    slot limit instead would pin a two-clip job on a twelve-core box to one
    thread per clip and leave ten cores idle: the limit is a ceiling on
    concurrency, not a promise that the work exists to fill it.
    """
    live = cpu_slots() if parallel is None else max(1, min(parallel, cpu_slots()))
    return max(1, math.floor((os.cpu_count() or 2) / live))


def reset_slots() -> None:
    """Drop the cached semaphores (tests, worker restart)."""
    global _CPU, _NET, _TTS
    _CPU = _NET = _TTS = None


@asynccontextmanager
async def cpu_slot() -> AsyncIterator[None]:
    global _CPU
    if _CPU is None:
        _CPU = asyncio.Semaphore(cpu_slots())
    async with _CPU:
        yield


@asynccontextmanager
async def net_slot() -> AsyncIterator[None]:
    global _NET
    if _NET is None:
        _NET = asyncio.Semaphore(net_slots())
    async with _NET:
        yield


@asynccontextmanager
async def tts_slot() -> AsyncIterator[None]:
    global _TTS
    if _TTS is None:
        _TTS = asyncio.Semaphore(tts_slots())
    async with _TTS:
        yield
