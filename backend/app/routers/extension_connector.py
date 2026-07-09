"""Chrome Extension connector endpoints.

The extension runs in the user's real Chrome/Edge browser, polls jobs for one
Facebook account, executes them on facebook.com, then reports the result here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db.postgres import get_session
from app.event_bus import event_bus
from app.models.sqlmodels import FacebookAccount, ShareTarget, TaskItem, TaskItemStatus, TaskLog, TaskRun, TaskRunStatus, User
from app.services.extension_queue import dequeue_extension_job, is_extension_online, mark_extension_online

router = APIRouter(tags=["extension-connector"])


@router.post("/api/extension/connect", response_model=dict)
async def connect_extension(
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_user_account(session, user.id, str(body.get("account_id") or ""))
    client_id = str(body.get("client_id") or uuid.uuid4())
    await mark_extension_online(str(account.id), client_id)
    account.browser_status = "extension_online"
    account.browser_last_error = ""
    account.browser_last_checked_at = datetime.now(timezone.utc)
    await session.commit()
    return {
        "client_id": client_id,
        "account_id": str(account.id),
        "status": account.browser_status,
        "message": "Extension connected. Jobs will run in the user's real browser.",
    }


@router.post("/api/extension/heartbeat", response_model=dict)
async def extension_heartbeat(
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_user_account(session, user.id, str(body.get("account_id") or ""))
    client_id = str(body.get("client_id") or "")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    await mark_extension_online(str(account.id), client_id)
    if account.browser_status != "extension_online":
        account.browser_status = "extension_online"
        account.browser_last_error = ""
        account.browser_last_checked_at = datetime.now(timezone.utc)
        await session.commit()
    return {"status": "online"}


@router.get("/api/extension/jobs", response_model=dict)
async def poll_extension_job(
    account_id: str = Query(...),
    client_id: str = Query(...),
    timeout: int = Query(20, ge=1, le=30),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_user_account(session, user.id, account_id)
    await mark_extension_online(str(account.id), client_id)
    job = await dequeue_extension_job(str(account.id), timeout)
    return {"job": job}


@router.post("/api/extension/jobs/{job_id}/complete", response_model=dict)
async def complete_extension_job(
    job_id: str,
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_user_account(session, user.id, str(body.get("account_id") or ""))
    client_id = str(body.get("client_id") or "")
    if client_id:
        await mark_extension_online(str(account.id), client_id)
    run_id = str(body.get("run_id") or "")
    task_item_id = body.get("task_item_id")
    share_target_id = body.get("share_target_id")
    action = str(body.get("action") or "extension_job")
    uid = str(body.get("uid") or account.uid)
    success = bool(body.get("success"))
    pending_review = bool(body.get("pending_review"))
    message = str(body.get("message") or "")
    output_link = str(body.get("post_url") or body.get("output_link") or "") or None
    log_index = int(body.get("log_index") or 999999)

    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    run_uuid = _uuid(run_id)

    if not success and _looks_checkpoint(message):
        account.browser_status = "checkpoint"
        account.browser_last_error = message
        account.browser_last_checked_at = datetime.now(timezone.utc)

    if task_item_id:
        item = await session.get(TaskItem, int(task_item_id))
        if item is not None and item.run_id == run_uuid:
            item.status = TaskItemStatus.PENDING_REVIEW if pending_review else (TaskItemStatus.SUCCESS if success else TaskItemStatus.FAILED)
            item.error = "" if success or pending_review else message
            item.output_link = output_link

    if share_target_id:
        target = await session.get(ShareTarget, _uuid(str(share_target_id)))
        if target is not None and target.user_id == user.id:
            target.status = "pending_review" if pending_review else ("success" if success else "failed")
            target.error = "" if success or pending_review else message
            target.output_post_id = output_link

    log = TaskLog(
        run_id=run_uuid,
        log_index=log_index,
        uid=uid,
        comment_link=output_link or str(body.get("target_url") or uid),
        action=action,
        proxy="Extension",
        status="Cho duyet" if pending_review else ("Thanh cong" if success else "That bai"),
        error="" if success or pending_review else message,
        output_link=output_link,
    )
    session.add(log)
    await _finish_run_if_complete(session, run_uuid)
    await session.commit()

    await event_bus.publish("log", "log", {
        "run_id": run_id,
        "log_index": log_index,
        "uid": uid,
        "comment_link": log.comment_link,
        "action": action,
        "proxy": "Extension",
        "status": log.status,
        "error": log.error,
        "output_link": output_link,
    })
    return {"status": "saved", "job_id": job_id}


@router.get("/api/extension/status", response_model=dict)
async def extension_status(
    account_id: str = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_user_account(session, user.id, account_id)
    return {"account_id": str(account.id), "online": await is_extension_online(str(account.id))}


async def _get_user_account(session: AsyncSession, user_id: uuid.UUID, account_id: str) -> FacebookAccount:
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id is required")
    account = await session.get(FacebookAccount, _uuid(account_id))
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=404, detail="Facebook account not found")
    return account


async def _finish_run_if_complete(session: AsyncSession, run_id: uuid.UUID) -> None:
    run = await session.get(TaskRun, run_id)
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


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id") from None


def _looks_checkpoint(message: str) -> bool:
    text = message.lower()
    return any(mark in text for mark in ["checkpoint", "security check", "confirm your identity", "xác minh", "xac minh"])
