"""Flow Studio worker — drains the clip queue only.

    python -m app.flow_worker

Separate from app.worker so Flow runs without the Face worker, and the two
never contend for each other's jobs (distinct Redis keys).
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.db.postgres import close_db, session_context
from app.db.redis import close_redis
from app.event_bus import event_bus
from app.services.clip_queue import dequeue_clip_job
from app.services.clip_retention import sweep_once
from app.services.clip_runner import ClipRunner
from app.services.gen_runner import GenRunner

logger = logging.getLogger("flowmeta.flow_worker")


async def process_clip_job(job: dict) -> bool:
    if job.get("type") not in {"clip_job", "gen_job"}:
        logger.warning("Flow worker skipping non-clip job: %s", job.get("type"))
        return False
    # Same queue, same retention, same gallery — only the pipeline differs.
    factory = GenRunner if job.get("type") == "gen_job" else ClipRunner
    runner = factory(session_factory=session_context, publish=event_bus.publish)
    try:
        await runner.run(str(job["job_id"]))
    except Exception:
        logger.exception("Clip job %s failed", job.get("job_id"))
        return False
    return True


async def run_retention_sweeper() -> None:
    """Delete the artefacts of jobs whose browser session is gone.

    Lives in the worker, not the API: it is the only Flow process guaranteed to
    be single-instance, and the API must never block a request on disk I/O.
    """
    interval = max(5, settings.CLIP_SWEEP_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(interval)
        try:
            summary = await sweep_once(session_context)
        except Exception:
            logger.exception("retention sweep failed")
            continue
        if summary["cancelled"] or summary["purged"]:
            logger.info(
                "retention sweep: cancelled=%d purged=%d files=%d bytes=%d",
                summary["cancelled"], summary["purged"], summary["files"], summary["bytes"],
            )


async def run_flow_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Flow Studio worker started")
    sweeper = (
        asyncio.create_task(run_retention_sweeper())
        if settings.CLIP_RETENTION_ENABLED
        else None
    )
    try:
        while True:
            job = await dequeue_clip_job(timeout_seconds=5)
            if job is None:
                continue
            await process_clip_job(job)
    finally:
        if sweeper is not None:
            sweeper.cancel()
        await close_redis()
        await close_db()


def main() -> None:
    asyncio.run(run_flow_worker())


if __name__ == "__main__":
    main()
