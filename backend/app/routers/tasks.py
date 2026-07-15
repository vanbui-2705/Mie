"""Task execution router — start/stop tasks, list runs, SSE log streaming."""
from __future__ import annotations

from typing import List
import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.rbac import require_permission
from app.db.postgres import get_session
from app.event_bus import event_bus
from app.models.sqlmodels import TaskItem, TaskItemStatus, TaskLog, TaskRun, TaskRunStatus, User
from app.schemas import (
    DelaySettingsDTO,
    TaskStartRequest,
    TaskRunResponse,
    TaskRunSummary,
)
from app.services.proxy_manager import DirectLease, ProxyManager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# set from main.py via dependency injection
_task_runner = None # type: ignore

def _get_task_runner():
    if _task_runner is None:
        raise RuntimeError("TaskRunner not initialized")
    return _task_runner


@router.post("/start", response_model=dict)
async def start_task(
    user: User = Depends(require_permission("task:create")),
    body: TaskStartRequest | None = Body(default=None),
    action: str = Query("edit", pattern="^(edit|delete|new_comment)$"),
    uid_text: str = Query(""),
    link_text: str = Query(""),
    post_text: str = Query(""),
    max_threads: int = Query(5, ge=1, le=200),
    new_text: str = Query(""),
    image_input: str = Query(""),
    delay_min: int = Query(0),
    delay_max: int = Query(0),
    delay_every_rounds: int = Query(1),
):
    if body is not None:
        action = body.action
        uid_text = body.raw_uid_text
        link_text = body.raw_link_text
        post_text = body.raw_post_text
        max_threads = body.max_threads
        new_text = body.new_text_input
        image_input = body.image_input
        delay_min = body.delay.min_seconds
        delay_max = body.delay.max_seconds
        delay_every_rounds = body.delay.every_rounds

    runner = _get_task_runner()
    delay = DelaySettingsDTO(
        min_seconds=delay_min,
        max_seconds=delay_max,
        every_rounds=delay_every_rounds,
    )
    run_id = await runner.start(
        action=action,
        max_threads=max_threads,
        delay=delay,
        uid_text=uid_text,
        link_text=link_text,
        post_text=post_text,
        new_text=new_text,
        image_input=image_input,
        user_id=user.id,
    )
    return {"run_id": run_id, "status": "started"}


@router.post("/stop", response_model=dict)
async def stop_task(
    user: User = Depends(require_permission("task:cancel")),
):
    runner = _get_task_runner()
    runner.stop()
    return {"status": "stopping"}


@router.post("/{run_id}/cancel", response_model=dict)
async def cancel_task(
    run_id: str,
    user: User = Depends(require_permission("task:cancel")),
    session: AsyncSession = Depends(get_session),
):
    run = await _get_user_run(session, user.id, run_id)
    runner = _get_task_runner()
    if runner.active_run_id == str(run.id):
        runner.stop()
    run.status = TaskRunStatus.CANCELED
    items_result = await session.execute(
        select(TaskItem).where(
            TaskItem.run_id == run.id,
            TaskItem.status.in_([TaskItemStatus.PENDING, TaskItemStatus.RUNNING]),
        )
    )
    for item in items_result.scalars().all():
        item.status = TaskItemStatus.CANCELED
    await session.commit()
    return {"status": "canceled"}


@router.get("", response_model=List[TaskRunSummary])
async def list_tasks(
    user: User = Depends(require_permission("task:read")),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TaskRun)
        .where(TaskRun.user_id == user.id)
        .order_by(desc(TaskRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    summaries: List[TaskRunSummary] = []
    for run in rows:
        counts = await _item_counts(session, run.id)
        summaries.append(TaskRunSummary(
            id=str(run.id),
            status=run.status,
            action=run.action,
            created_at=run.created_at,
            finished_at=run.finished_at,
            **counts,
        ))
    return summaries


@router.get("/{run_id}", response_model=TaskRunResponse)
async def get_task(
    run_id: str,
    user: User = Depends(require_permission("task:read")),
    session: AsyncSession = Depends(get_session),
):
    run = await _get_user_run(session, user.id, run_id)
    counts = await _item_counts(session, run.id)
    return TaskRunResponse(
        id=str(run.id),
        status=run.status,
        action=run.action,
        max_threads=run.max_threads,
        created_at=run.created_at,
        finished_at=run.finished_at,
        **counts,
        waiting_proxy=0,
    )


@router.get("/{run_id}/logs", response_model=list[dict])
async def get_task_logs(
    run_id: str,
    user: User = Depends(require_permission("task:read")),
    session: AsyncSession = Depends(get_session),
):
    run = await _get_user_run(session, user.id, run_id)
    logs_result = await session.execute(
        select(TaskLog).where(TaskLog.run_id == run.id).order_by(TaskLog.log_index)
    )
    return [
        {
            "id": log.id,
            "run_id": str(log.run_id),
            "log_index": log.log_index,
            "uid": log.uid or "",
            "comment_link": log.comment_link,
            "action": log.action,
            "proxy": log.proxy,
            "status": log.status,
            "error": log.error or "",
            "output_link": log.output_link or "",
            "created_at": log.created_at,
        }
        for log in logs_result.scalars().all()
    ]


@router.get("/{run_id}/items", response_model=list[dict])
async def get_task_items(
    run_id: str,
    user: User = Depends(require_permission("task:read")),
    session: AsyncSession = Depends(get_session),
):
    run = await _get_user_run(session, user.id, run_id)
    items_result = await session.execute(
        select(TaskItem).where(TaskItem.run_id == run.id).order_by(TaskItem.item_index)
    )
    return [
        {
            "id": item.id,
            "run_id": str(item.run_id),
            "item_index": item.item_index,
            "uid": item.uid or "",
            "target_link": item.target_link,
            "action": item.action,
            "status": item.status.value if hasattr(item.status, "value") else item.status,
            "error": item.error or "",
            "output_link": item.output_link or "",
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in items_result.scalars().all()
    ]


async def _get_user_run(session: AsyncSession, user_id: uuid.UUID, run_id: str) -> TaskRun:
    run = await session.get(TaskRun, _uuid(run_id))
    if run is None or run.user_id != user_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


async def _item_counts(session: AsyncSession, run_id: uuid.UUID) -> dict:
    result = await session.execute(
        select(TaskItem.status, func.count(TaskItem.id))
        .where(TaskItem.run_id == run_id)
        .group_by(TaskItem.status)
    )
    counts = {status: count for status, count in result.all()}
    success = counts.get(TaskItemStatus.SUCCESS, 0)
    failed = counts.get(TaskItemStatus.FAILED, 0)
    canceled = counts.get(TaskItemStatus.CANCELED, 0)
    running = counts.get(TaskItemStatus.RUNNING, 0)
    pending = counts.get(TaskItemStatus.PENDING, 0)
    total = success + failed + canceled + running + pending
    return {
        "total": total,
        "processed": success + failed + canceled,
        "success": success,
        "failed": failed + canceled,
    }


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run id") from None
