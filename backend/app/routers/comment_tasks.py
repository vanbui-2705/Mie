"""Queued comment/edit/delete task endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.crypto import encrypt
from app.db.postgres import get_session
from app.models.sqlmodels import CommentAction, TaskItem, TaskItemStatus, TaskRun, TaskRunStatus, User
from app.schemas import TaskStartRequest
from app.services.task_queue import build_comment_job, enqueue_task

router = APIRouter(tags=["comment-tasks"])


@router.post("/api/comment-tasks", response_model=dict)
async def create_comment_task(
    body: TaskStartRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    items = _build_task_items(body)
    if not items:
        raise HTTPException(status_code=400, detail="Task has no valid items")
    run = TaskRun(
        user_id=user.id,
        status=TaskRunStatus.PENDING,
        action=CommentAction(body.action),
        max_threads=body.max_threads,
        delay_min=body.delay.min_seconds,
        delay_max=body.delay.max_seconds,
        delay_every_rounds=body.delay.every_rounds,
        text_input_enc=encrypt(body.new_text_input) if body.new_text_input else None,
        image_path=body.image_input or None,
    )
    session.add(run)
    await session.flush()
    for index, item in enumerate(items, start=1):
        session.add(TaskItem(
            run_id=run.id,
            user_id=user.id,
            item_index=index,
            uid=item["uid"] or None,
            target_link=item["link"],
            action=body.action,
            status=TaskItemStatus.PENDING,
        ))
    await session.commit()
    await session.refresh(run)

    payload = body.model_dump()
    try:
        queue_length = await enqueue_task(build_comment_job(str(run.id), payload))
    except Exception as exc:
        run.status = TaskRunStatus.FAILED
        items_result = await session.execute(
            select(TaskItem).where(TaskItem.run_id == run.id)
        )
        for item in items_result.scalars().all():
            item.status = TaskItemStatus.FAILED
            item.error = "Could not enqueue task"
        await session.commit()
        raise HTTPException(status_code=503, detail=f"Could not enqueue task: {exc}") from exc
    return {
        "task_id": str(run.id),
        "status": TaskRunStatus.PENDING.value,
        "total": len(items),
        "queue_length": queue_length,
    }


def _build_task_items(body: TaskStartRequest) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if body.action == CommentAction.NEW_COMMENT.value:
        for line in body.raw_post_text.replace("\r\n", "\n").split("\n"):
            link = line.strip()
            if link:
                items.append({"uid": "", "link": link})
        return items

    uids = [line.strip() for line in body.raw_uid_text.replace("\r\n", "\n").split("\n") if line.strip()]
    links = [line.strip() for line in body.raw_link_text.replace("\r\n", "\n").split("\n") if line.strip()]
    for uid, link in zip(uids, links):
        items.append({"uid": uid, "link": link})
    return items
