"""Browser worker for personal profile posting jobs."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.db.postgres import close_db, session_context
from app.db.redis import close_redis
from app.event_bus import event_bus
from sqlalchemy import select

from app.models.sqlmodels import FacebookAccount, ShareTarget, TaskItem, TaskItemStatus, TaskLog, TaskRun, TaskRunStatus
from app.services.browser_profiles import profile_path
from app.services.personal_browser import post_to_group, post_to_timeline, share_to_target
from app.services.task_queue import acquire_browser_account_lock, dequeue_browser_job, release_browser_account_lock

logger = logging.getLogger("flowmeta.browser_worker")


async def run_browser_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("FlowMeta browser worker started")
    try:
        while True:
            job = await dequeue_browser_job(timeout_seconds=5)
            if job is None:
                continue
            await process_browser_job(job)
    finally:
        await close_redis()
        await close_db()


async def process_browser_job(job: dict) -> bool:
    job_type = str(job.get("type") or "")
    if job_type not in {"personal_post", "group_post", "share_to_group", "share_to_external_page", "share_to_managed_page"}:
        logger.warning("Skipping unknown browser job type: %s", job.get("type"))
        return False

    run_id = str(job.get("run_id") or "")
    user_id = str(job.get("user_id") or "")
    account_id = str(job.get("account_id") or "")
    uid = str(job.get("uid") or "")
    message = str(job.get("message") or "")
    link = str(job.get("link") or "")
    media_paths = [str(path) for path in job.get("media_paths") or [] if str(path)]
    final_message = f"{message}\n\n{link}".strip() if link else message
    target_url = str(job.get("target_url") or "")
    source_url = str(job.get("source_url") or "")
    action = _action_for_job(job_type)
    log_index = int(job.get("log_index") or 999999)
    task_item_id = job.get("task_item_id")
    share_target_id = job.get("share_target_id")
    lock_owner = f"{run_id}:{task_item_id or log_index}"

    try:
        while not await acquire_browser_account_lock(account_id, lock_owner):
            logger.info("Waiting for browser lock for account %s", account_id)
            await asyncio.sleep(3)
        await _mark_item_running(task_item_id)
        profile_dir = str(profile_path(user_id, account_id))
        if job_type == "personal_post":
            result = await asyncio.to_thread(post_to_timeline, profile_dir, final_message, media_paths, True)
        elif job_type == "group_post":
            result = await asyncio.to_thread(post_to_group, profile_dir, target_url, final_message, media_paths)
        else:
            result = await asyncio.to_thread(
                share_to_target,
                profile_dir,
                target_url,
                source_url,
                message,
                job_type,
                True,
                str(job.get("target_name") or ""),
            )
        await _write_result(run_id, log_index, uid or target_url, result, account_id, task_item_id, action, share_target_id)
        return bool(result.get("success"))
    except Exception as exc:
        logger.exception("Browser job failed")
        await _write_result(run_id, log_index, uid or target_url, {"success": False, "message": str(exc)}, account_id, task_item_id, action, share_target_id)
        return False
    finally:
        await release_browser_account_lock(account_id, lock_owner)


async def _mark_item_running(task_item_id) -> None:
    if not task_item_id:
        return
    async with session_context() as session:
        item = await session.get(TaskItem, int(task_item_id))
        if item is not None and item.status == TaskItemStatus.PENDING:
            item.status = TaskItemStatus.RUNNING
            await session.commit()


async def _write_result(run_id: str, log_index: int, uid: str, result: dict, account_id: str, task_item_id=None, action: str = "post_personal", share_target_id=None) -> None:
    success = bool(result.get("success"))
    pending_review = bool(result.get("pending_review"))
    async with session_context() as session:
        account = await session.get(FacebookAccount, uuid.UUID(account_id))
        message = str(result.get("message") or "")
        result_status = str(result.get("status") or "").lower()
        if account is not None and not success and (result_status == "checkpoint" or "checkpoint" in message.lower() or "xac thuc" in message.lower() or "xác thực" in message.lower()):
            account.browser_status = "checkpoint"
            account.browser_last_error = message
            account.browser_last_checked_at = datetime.now(timezone.utc)
        elif account is not None and not success and "login" in message.lower():
            account.browser_status = "expired"
            account.browser_last_error = message
            account.browser_last_checked_at = datetime.now(timezone.utc)

        if task_item_id:
            item = await session.get(TaskItem, int(task_item_id))
            if item is not None:
                item.status = TaskItemStatus.PENDING_REVIEW if pending_review else (TaskItemStatus.SUCCESS if success else TaskItemStatus.FAILED)
                item.error = "" if success or pending_review else str(result.get("message") or "")
                item.output_link = str(result.get("post_url") or "") or None

        if share_target_id:
            target = await session.get(ShareTarget, uuid.UUID(str(share_target_id)))
            if target is not None:
                target.status = "pending_review" if pending_review else ("success" if success else "failed")
                target.error = "" if success or pending_review else str(result.get("message") or "")
                target.output_post_id = str(result.get("post_url") or "") or None

        log = TaskLog(
            run_id=uuid.UUID(run_id),
            log_index=log_index,
            uid=uid,
            comment_link=str(result.get("post_url") or uid),
            action=action,
            proxy="Browser",
            status="Cho duyet" if pending_review else ("Thanh cong" if success else "That bai"),
            error="" if success or pending_review else str(result.get("message") or ""),
            output_link=str(result.get("post_url") or "") or None,
        )
        session.add(log)

        await _finish_run_if_complete(session, run_id)
        await session.commit()

    await event_bus.publish("log", "log", {
        "user_id": str(account.user_id) if account is not None else "",
        "run_id": run_id,
        "log_index": log_index,
        "uid": uid,
        "comment_link": result.get("post_url") or uid,
        "action": action,
        "proxy": "Browser",
        "status": "Cho duyet" if pending_review else ("Thanh cong" if success else "That bai"),
        "error": "" if success or pending_review else str(result.get("message") or ""),
        "output_link": result.get("post_url") or None,
    })


async def _finish_run_if_complete(session, run_id: str) -> None:
    run = await session.get(TaskRun, uuid.UUID(run_id))
    if run is None or run.status != TaskRunStatus.RUNNING:
        return
    result = await session.execute(select(TaskItem).where(TaskItem.run_id == run.id))
    items = result.scalars().all()
    if not items:
        return
    if any(item.status in (TaskItemStatus.PENDING, TaskItemStatus.RUNNING) for item in items):
        return
    run.status = TaskRunStatus.FAILED if any(item.status == TaskItemStatus.FAILED for item in items) else TaskRunStatus.SUCCESS
    run.finished_at = datetime.now(timezone.utc)


def _action_for_job(job_type: str) -> str:
    return {
        "personal_post": "post_personal",
        "group_post": "post_group",
        "share_to_group": "share_group",
        "share_to_external_page": "share_external_page",
        "share_to_managed_page": "share_page_browser",
    }.get(job_type, job_type)


def main() -> None:
    asyncio.run(run_browser_worker())


if __name__ == "__main__":
    main()
