"""Production worker process for queued FlowMeta jobs."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.db.postgres import close_db, get_session
from app.db.postgres import session_context
from app.db.redis import close_redis
from app.event_bus import event_bus
from app.models.sqlmodels import TaskItem, TaskItemStatus, TaskRun, TaskRunStatus
from app.schemas import DelaySettingsDTO
from app.services.proxy_manager import ProxyManager
from app.services.task_queue import dequeue_task
from app.services.task_runner import TaskRunner
from sqlalchemy import select

logger = logging.getLogger("flowmeta.worker")


async def run_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    proxy_manager = ProxyManager()
    runner = TaskRunner(
        get_session=get_session,
        proxy_manager=proxy_manager,
        publish=event_bus.publish,
    )
    logger.info("FlowMeta worker started")
    try:
        while True:
            job = await dequeue_task(timeout_seconds=5)
            if job is None:
                continue
            await process_job(job, runner)
    finally:
        await proxy_manager.stop_async()
        await close_redis()
        await close_db()


async def process_job(job: dict, runner: TaskRunner) -> bool:
    job_type = job.get("type")
    if job_type != "comment_task":
        logger.warning("Skipping unknown job type: %s", job_type)
        return False

    run_id = str(job["run_id"])
    if await _is_canceled(run_id):
        logger.info("Skipping canceled task %s", run_id)
        return False

    payload = job.get("payload") or {}
    delay_raw = payload.get("delay") or {}
    delay = DelaySettingsDTO(
        min_seconds=int(delay_raw.get("min_seconds") or 0),
        max_seconds=int(delay_raw.get("max_seconds") or 0),
        every_rounds=int(delay_raw.get("every_rounds") or 1),
    )
    try:
        await runner.run_existing(
            run_id=run_id,
            action=str(payload.get("action") or "edit"),
            max_threads=int(payload.get("max_threads") or 5),
            delay=delay,
            uid_text=str(payload.get("raw_uid_text") or ""),
            link_text=str(payload.get("raw_link_text") or ""),
            post_text=str(payload.get("raw_post_text") or ""),
            new_text=str(payload.get("new_text_input") or ""),
            image_input=str(payload.get("image_input") or ""),
        )
    except asyncio.CancelledError:
        if await _is_canceled(run_id):
            logger.info("Task %s canceled while running", run_id)
            return False
        raise
    except Exception as exc:
        logger.exception("Task %s failed in worker", run_id)
        await _mark_failed(run_id, str(exc))
        return False
    return True


async def _is_canceled(run_id: str) -> bool:
    run_uuid = uuid.UUID(run_id)
    async with session_context() as session:
        run = await session.get(TaskRun, run_uuid)
        return run is not None and run.status == TaskRunStatus.CANCELED


async def _mark_failed(run_id: str, error: str) -> None:
    run_uuid = uuid.UUID(run_id)
    async with session_context() as session:
        run = await session.get(TaskRun, run_uuid)
        if run is not None:
            run.status = TaskRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
        result = await session.execute(
            select(TaskItem).where(
                TaskItem.run_id == run_uuid,
                TaskItem.status.in_([TaskItemStatus.PENDING, TaskItemStatus.RUNNING]),
            )
        )
        for item in result.scalars().all():
            item.status = TaskItemStatus.FAILED
            item.error = error
        await session.commit()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
