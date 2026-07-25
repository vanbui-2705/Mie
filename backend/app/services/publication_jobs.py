"""Durable publication job state and TaskItem reconciliation."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.sqlmodels import (
    FacebookGroup,
    PublicationJob,
    RentalConfig,
    RentalRoom,
    SheetSourceItem,
    TaskItem,
    TaskItemStatus,
)


ACTIVE_JOB_STATUSES = {"pending", "dispatching", "queued", "running"}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "canceled"}
MAX_RETRY_DELAY_SECONDS = 3600


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def retry_delay(attempt_count: int) -> timedelta:
    seconds = min(60 * (2 ** max(0, attempt_count - 1)), MAX_RETRY_DELAY_SECONDS)
    return timedelta(seconds=seconds)


async def ensure_rental_publication_jobs(
    session,
    room: RentalRoom,
    *,
    scheduled_at: datetime | None = None,
) -> list[PublicationJob]:
    """Create missing per-group jobs for a room without duplicating existing ones."""
    raw_group_ids = json.loads(room.matched_group_ids_json or "[]")
    external_group_ids = [str(value) for value in raw_group_ids if str(value)]
    if not external_group_ids:
        return []

    groups = list((await session.execute(
        select(FacebookGroup).where(
            FacebookGroup.user_id == room.user_id,
            FacebookGroup.group_id.in_(external_group_ids),
        )
    )).scalars())
    existing_target_ids = set((await session.execute(
        select(PublicationJob.target_id).where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.target_type == "group",
        )
    )).scalars())

    created: list[PublicationJob] = []
    for group in groups:
        if group.id in existing_target_ids:
            continue
        job = PublicationJob(
            user_id=room.user_id,
            rental_room_id=room.id,
            target_type="group",
            target_id=group.id,
            target_external_id=group.group_id,
            scheduled_at=scheduled_at or datetime.now(timezone.utc),
            status="pending",
        )
        session.add(job)
        created.append(job)
        existing_target_ids.add(group.id)
    if created:
        await session.flush()
    return created


def schedule_job_retry(job: PublicationJob, error: str, now: datetime) -> None:
    job.error = str(error or "Publication failed")
    job.result_message = None
    job.finished_at = now
    job.claimed_at = None
    job.started_at = None
    if job.attempt_count >= job.max_attempts:
        job.status = "failed"
        job.next_retry_at = None
    else:
        job.status = "pending"
        job.next_retry_at = now + retry_delay(job.attempt_count)
    job.task_run_id = None
    job.task_item_id = None


async def aggregate_rental_room(session, room_id: uuid.UUID, now: datetime) -> None:
    room = await session.get(RentalRoom, room_id)
    if room is None or room.status in {"rented", "inactive", "skipped"}:
        return
    jobs = list((await session.execute(
        select(PublicationJob).where(PublicationJob.rental_room_id == room.id)
    )).scalars())
    if not jobs:
        return

    urls = {
        str(job.target_external_id or job.target_id): job.facebook_url
        for job in jobs
        if job.status == "succeeded" and job.facebook_url
    }
    room.post_urls_json = json.dumps(urls, ensure_ascii=False) if urls else None
    room.retry_count = max((job.attempt_count for job in jobs), default=0)

    statuses = {job.status for job in jobs}
    if statuses == {"succeeded"}:
        room.status = "posted"
        room.posted_at = now
        room.error = None
    elif "pending_review" in statuses:
        room.status = "pending_review"
        room.error = None
    elif statuses & ACTIVE_JOB_STATUSES:
        room.status = "posting" if statuses & {"dispatching", "queued", "running"} else "new"
        room.error = None
    elif "succeeded" in statuses:
        room.status = "partial"
        room.error = _combined_errors(jobs)
    elif statuses <= TERMINAL_JOB_STATUSES:
        room.status = "error"
        room.error = _combined_errors(jobs) or "All publication targets failed"

    config = await session.get(RentalConfig, room.config_id)
    if config is not None and config.google_sheet_connection_id:
        from app.services.rental_sheet_mirror import enqueue_rental_mirror
        await enqueue_rental_mirror(
            session, room, config.google_sheet_connection_id,
        )


async def reconcile_publication_jobs(get_session, now: datetime | None = None) -> dict[str, int]:
    """Copy final TaskItem outcomes into publication jobs and aggregate sources."""
    now = as_utc(now) or datetime.now(timezone.utc)
    counts = {"succeeded": 0, "failed": 0, "retried": 0, "pending_review": 0}
    touched_rooms: set[uuid.UUID] = set()
    touched_sheet_items: set[uuid.UUID] = set()

    async with get_session() as session:
        jobs = list((await session.execute(
            select(PublicationJob).where(
                PublicationJob.status.in_(["queued", "running"]),
                PublicationJob.task_item_id.is_not(None),
            )
        )).scalars())

        for job in jobs:
            item = await session.get(TaskItem, job.task_item_id)
            if item is None:
                schedule_job_retry(job, "Linked task item was not found", now)
                counts["failed" if job.status == "failed" else "retried"] += 1
            elif item.status == TaskItemStatus.PENDING:
                job.status = "queued"
            elif item.status == TaskItemStatus.RUNNING:
                job.status = "running"
                job.started_at = job.started_at or now
            elif item.status == TaskItemStatus.SUCCESS:
                job.status = "succeeded"
                job.facebook_url = item.output_link
                job.error = None
                job.result_message = "Published successfully"
                job.finished_at = now
                job.next_retry_at = None
                counts["succeeded"] += 1
            elif item.status == TaskItemStatus.PENDING_REVIEW:
                job.status = "pending_review"
                job.facebook_url = item.output_link
                job.error = None
                job.result_message = "Pending Facebook review"
                job.finished_at = now
                job.next_retry_at = None
                counts["pending_review"] += 1
            elif item.status in {
                TaskItemStatus.FAILED,
                TaskItemStatus.CANCELED,
            }:
                schedule_job_retry(job, item.error or f"Task ended as {item.status.value}", now)
                counts["failed" if job.status == "failed" else "retried"] += 1

            if job.rental_room_id:
                touched_rooms.add(job.rental_room_id)
            if job.sheet_source_item_id:
                touched_sheet_items.add(job.sheet_source_item_id)

        for room_id in touched_rooms:
            await aggregate_rental_room(session, room_id, now)
        for source_item_id in touched_sheet_items:
            await aggregate_sheet_source_item(session, source_item_id, now)
        await session.commit()

    return counts


async def recover_stale_publication_jobs(
    get_session,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 1800,
) -> int:
    """Quarantine ambiguous stale dispatches instead of risking a duplicate post."""
    now = as_utc(now) or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=max(60, stale_after_seconds))
    touched_rooms: set[uuid.UUID] = set()
    touched_sheet_items: set[uuid.UUID] = set()
    recovered = 0
    async with get_session() as session:
        jobs = list((await session.execute(
            select(PublicationJob).where(
                PublicationJob.status.in_(["dispatching", "queued", "running"]),
                PublicationJob.started_at.is_not(None),
                PublicationJob.started_at <= cutoff,
            )
        )).scalars())
        for job in jobs:
            item = await session.get(TaskItem, job.task_item_id) if job.task_item_id else None
            if item and item.status in {
                TaskItemStatus.SUCCESS,
                TaskItemStatus.FAILED,
                TaskItemStatus.CANCELED,
                TaskItemStatus.PENDING_REVIEW,
            }:
                continue
            job.status = "pending_review"
            job.error = (
                "Publication result timed out and is ambiguous; review Facebook "
                "before retrying to avoid a duplicate post"
            )
            job.finished_at = now
            job.next_retry_at = None
            if item and item.status in {TaskItemStatus.PENDING, TaskItemStatus.RUNNING}:
                item.status = TaskItemStatus.PENDING_REVIEW
                item.error = job.error
            if job.rental_room_id:
                touched_rooms.add(job.rental_room_id)
            if job.sheet_source_item_id:
                touched_sheet_items.add(job.sheet_source_item_id)
            recovered += 1
        for room_id in touched_rooms:
            await aggregate_rental_room(session, room_id, now)
        for source_id in touched_sheet_items:
            await aggregate_sheet_source_item(session, source_id, now)
        await session.commit()
    return recovered


async def aggregate_sheet_source_item(
    session,
    source_item_id: uuid.UUID,
    now: datetime,
) -> None:
    source = await session.get(SheetSourceItem, source_item_id)
    if source is None or source.status in {"invalid", "canceled"}:
        return
    jobs = list((await session.execute(
        select(PublicationJob).where(
            PublicationJob.sheet_source_item_id == source.id,
            PublicationJob.source_version == source.source_version,
        )
    )).scalars())
    if not jobs:
        return
    statuses = {job.status for job in jobs}
    if statuses == {"succeeded"}:
        source.status = "posted"
        source.completed_at = now
        source.validation_error = None
    elif "pending_review" in statuses:
        source.status = "pending_review"
    elif statuses & ACTIVE_JOB_STATUSES:
        source.status = "posting" if statuses & {"dispatching", "queued", "running"} else "queued"
    elif "succeeded" in statuses:
        source.status = "partial"
        source.completed_at = now
        source.validation_error = _combined_errors(jobs)
    elif statuses <= TERMINAL_JOB_STATUSES:
        source.status = "failed"
        source.completed_at = now
        source.validation_error = _combined_errors(jobs) or "All publication targets failed"
    from app.services.sheet_sync import enqueue_sheet_writeback
    await enqueue_sheet_writeback(session, source)


def _combined_errors(jobs: list[PublicationJob]) -> str | None:
    errors = [str(job.error).strip() for job in jobs if str(job.error or "").strip()]
    if not errors:
        return None
    return "; ".join(dict.fromkeys(errors))[:2000]
