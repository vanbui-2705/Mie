"""Registry of the external processes the pipeline currently has open.

A cancelled job must not keep an ffmpeg render (or a yt-dlp download) burning
CPU for another minute, and the pipeline spawns processes from five different
modules. Registering them here lets the runner's cancel watcher kill whatever is
live without any of those modules learning what a job is.

The worker runs one job at a time, so a module-level set is the whole story.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("flowmeta.pipeline.procs")

_LIVE: set[asyncio.subprocess.Process] = set()


async def spawn(cmd: list[str], **kwargs) -> asyncio.subprocess.Process:
    process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
    _LIVE.add(process)
    return process


async def communicate(process: asyncio.subprocess.Process, **kwargs) -> tuple[bytes, bytes]:
    try:
        return await process.communicate(**kwargs)
    finally:
        _LIVE.discard(process)


def kill_live() -> int:
    """Kill every tracked process. Returns how many were still running."""
    killed = 0
    for process in list(_LIVE):
        if process.returncode is not None:
            _LIVE.discard(process)
            continue
        try:
            process.kill()
            killed += 1
        except (ProcessLookupError, OSError) as exc:
            logger.warning("could not kill pid %s: %s", process.pid, exc)
        _LIVE.discard(process)
    return killed
