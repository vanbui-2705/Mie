"""Flow Studio worker — drains the clip queue only.

    python -m app.flow_worker

Separate from app.worker so Flow runs without the Face worker, and the two
never contend for each other's jobs (distinct Redis keys).
"""
from __future__ import annotations

import asyncio
import logging

from app.db.postgres import close_db, session_context
from app.db.redis import close_redis
from app.event_bus import event_bus
from app.services.clip_queue import dequeue_clip_job
from app.services.clip_runner import ClipRunner

logger = logging.getLogger("flowmeta.flow_worker")


async def process_clip_job(job: dict) -> bool:
    if job.get("type") != "clip_job":
        logger.warning("Flow worker skipping non-clip job: %s", job.get("type"))
        return False
    runner = ClipRunner(session_factory=session_context, publish=event_bus.publish)
    try:
        await runner.run(str(job["job_id"]))
    except Exception:
        logger.exception("Clip job %s failed", job.get("job_id"))
        return False
    return True


async def run_flow_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Flow Studio worker started")
    try:
        while True:
            job = await dequeue_clip_job(timeout_seconds=5)
            if job is None:
                continue
            await process_clip_job(job)
    finally:
        await close_redis()
        await close_db()


def main() -> None:
    asyncio.run(run_flow_worker())


if __name__ == "__main__":
    main()
