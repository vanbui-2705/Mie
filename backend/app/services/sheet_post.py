"""Dispatch due Google Sheet publication jobs through the existing publisher."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.models.sqlmodels import (
    CommentAction,
    PublicationJob,
    SheetSourceItem,
    TaskRun,
    TaskRunStatus,
)
from app.services.publication_jobs import (
    aggregate_sheet_source_item,
    reconcile_publication_jobs,
    schedule_job_retry,
)

logger = logging.getLogger("flowmeta.sheet_post")


class SheetPostService:
    def __init__(self, get_session, run_post=None):
        self._get_session = get_session
        self._run_post = run_post

    def _runner(self):
        if self._run_post is not None:
            return self._run_post
        from app.routers.page_tasks import _run_page_post_task
        return _run_page_post_task

    async def post_due(
        self,
        *,
        now: datetime | None = None,
        source_item_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        force: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        async with self._get_session() as session:
            query = (
                select(PublicationJob.id)
                .join(
                    SheetSourceItem,
                    SheetSourceItem.id == PublicationJob.sheet_source_item_id,
                )
                .where(
                    PublicationJob.status == "pending",
                    PublicationJob.sheet_source_item_id.is_not(None),
                    or_(
                        PublicationJob.next_retry_at.is_(None),
                        PublicationJob.next_retry_at <= now,
                    ),
                )
            )
            if not force:
                query = query.where(PublicationJob.scheduled_at <= now)
            if source_item_id:
                query = query.where(PublicationJob.sheet_source_item_id == source_item_id)
            if user_id:
                query = query.where(PublicationJob.user_id == user_id)
            job_ids = list((await session.execute(
                query.order_by(PublicationJob.scheduled_at).limit(limit)
            )).scalars())

        results = []
        for job_id in job_ids:
            result = await self._dispatch(job_id, now)
            if result:
                results.append(result)
        return results

    async def _dispatch(self, job_id: uuid.UUID, now: datetime) -> dict | None:
        async with self._get_session() as session:
            job = (await session.execute(
                select(PublicationJob)
                .where(
                    PublicationJob.id == job_id,
                    PublicationJob.status == "pending",
                )
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if job is None or job.sheet_source_item_id is None:
                return None
            source = await session.get(SheetSourceItem, job.sheet_source_item_id)
            if (
                source is None
                or source.user_id != job.user_id
                or source.source_version != job.source_version
                or source.status in {"invalid", "canceled"}
            ):
                job.status = "canceled"
                job.error = "Source item is missing, invalid, or superseded"
                job.finished_at = now
                await session.commit()
                return None

            run = TaskRun(
                user_id=job.user_id,
                status=TaskRunStatus.RUNNING,
                action=CommentAction.POST_PAGE,
                max_threads=1,
                text_input_enc=None,
                image_path=None,
            )
            session.add(run)
            await session.flush()
            job.status = "dispatching"
            job.claimed_at = now
            job.started_at = now
            job.attempt_count += 1
            job.task_run_id = run.id
            source.status = "posting"
            dispatch = {
                "job_id": job.id,
                "run_id": run.id,
                "source_item_id": source.id,
                "target_type": job.target_type,
                "target_id": job.target_id,
                "message": source.content,
                "link": source.link,
                "media_paths": json.loads(source.media_paths_json or "[]"),
            }
            await session.commit()

        target_lists = {
            "page_ids": [],
            "group_ids": [],
            "personal_account_ids": [],
        }
        key = {
            "page": "page_ids",
            "group": "group_ids",
            "personal": "personal_account_ids",
        }.get(dispatch["target_type"])
        if key is None:
            result = {"accepted": False, "error": "Unsupported target type"}
        else:
            target_lists[key] = [str(dispatch["target_id"])]
            try:
                result = await self._runner()(
                    run_id=str(dispatch["run_id"]),
                    **target_lists,
                    message=dispatch["message"],
                    link=dispatch["link"],
                    media_paths=dispatch["media_paths"],
                    publication_job_id=str(dispatch["job_id"]),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("sheet publication dispatch %s failed: %s", job_id, exc)
                result = {"accepted": False, "error": str(exc)}

        async with self._get_session() as session:
            job = await session.get(PublicationJob, job_id)
            if job is None:
                return None
            item_ids = list((result or {}).get("task_item_ids") or [])
            accepted = bool((result or {}).get("accepted")) and bool(item_ids)
            if accepted:
                job.status = "queued"
                job.task_item_id = int(item_ids[0])
                job.error = None
            else:
                schedule_job_retry(
                    job,
                    str((result or {}).get("error") or "Publisher did not accept the job"),
                    now,
                )
            await aggregate_sheet_source_item(
                session, dispatch["source_item_id"], now,
            )
            await session.commit()
            return {
                "job_id": str(job.id),
                "source_item_id": str(dispatch["source_item_id"]),
                "run_id": str(dispatch["run_id"]),
                "task_item_id": job.task_item_id,
                "status": job.status,
                "accepted": accepted,
            }


async def run_sheet_posting(get_session) -> None:
    await reconcile_publication_jobs(get_session)
    await SheetPostService(get_session).post_due()
