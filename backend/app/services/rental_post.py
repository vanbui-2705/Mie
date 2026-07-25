"""Durable, throttled rental-room publication dispatch and reconciliation."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.models.sqlmodels import (
    CommentAction,
    FacebookGroup,
    PublicationJob,
    RentalConfig,
    RentalRoom,
    TaskRun,
    TaskRunStatus,
)
from app.services.publication_jobs import (
    aggregate_rental_room,
    as_utc,
    ensure_rental_publication_jobs,
    reconcile_publication_jobs,
    schedule_job_retry,
)

logger = logging.getLogger("flowmeta.rental_post")


class RentalPostService:
    """Claim and dispatch at most one target per eligible rental config."""

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
        now: datetime | None = None,
        *,
        config_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        force: bool = False,
    ) -> list[dict]:
        now = as_utc(now) or datetime.now(timezone.utc)
        async with self._get_session() as session:
            query = select(RentalConfig.id).where(
                RentalConfig.auto_post == True,  # noqa: E712
                RentalConfig.status == "active",
            )
            if config_id is not None:
                query = query.where(RentalConfig.id == config_id)
            if user_id is not None:
                query = query.where(RentalConfig.user_id == user_id)
            config_ids = list((await session.execute(query)).scalars())

        fired: list[dict] = []
        for candidate_id in config_ids:
            result = await self._dispatch_for_config(candidate_id, now, force=force)
            if result:
                fired.append(result)
        return fired

    async def _dispatch_for_config(
        self,
        config_id: uuid.UUID,
        now: datetime,
        *,
        force: bool,
    ) -> dict | None:
        async with self._get_session() as session:
            cfg = await session.get(RentalConfig, config_id)
            if cfg is None or not cfg.auto_post or cfg.status != "active":
                return None
            last_post_at = as_utc(cfg.last_post_at)
            if (
                not force
                and last_post_at
                and (now - last_post_at) < timedelta(seconds=cfg.post_spacing_seconds)
            ):
                return None

            room = (await session.execute(
                select(RentalRoom).where(
                    RentalRoom.config_id == cfg.id,
                    RentalRoom.status.in_(["new", "posting", "partial"]),
                ).order_by(RentalRoom.created_at).limit(1)
            )).scalar_one_or_none()
            if room is not None:
                base_time = as_utc(room.created_at) or now
                await ensure_rental_publication_jobs(
                    session,
                    room,
                    scheduled_at=base_time + timedelta(seconds=cfg.post_delay_seconds),
                )
                has_jobs = (await session.execute(
                    select(PublicationJob.id).where(
                        PublicationJob.rental_room_id == room.id
                    ).limit(1)
                )).scalar_one_or_none()
                if has_jobs is None and room.matched_group_ids_json:
                    unresolved = [
                        str(value)
                        for value in json.loads(room.matched_group_ids_json or "[]")
                        if str(value)
                    ]
                    if unresolved:
                        room.status = "waiting_groups"
                        room.error = f"No owned Facebook groups resolved for {unresolved}"
                        await session.commit()
                        return {
                            "config_id": str(cfg.id),
                            "room_id": str(room.id),
                            "group_id": None,
                            "job_id": None,
                            "status": room.status,
                            "accepted": False,
                        }

            job = (await session.execute(
                select(PublicationJob)
                .join(RentalRoom, RentalRoom.id == PublicationJob.rental_room_id)
                .where(
                    RentalRoom.config_id == cfg.id,
                    RentalRoom.status.not_in(["rented", "inactive", "skipped"]),
                    PublicationJob.status == "pending",
                    PublicationJob.scheduled_at <= now,
                    or_(
                        PublicationJob.next_retry_at.is_(None),
                        PublicationJob.next_retry_at <= now,
                    ),
                )
                .order_by(PublicationJob.scheduled_at, PublicationJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if job is None:
                await session.commit()
                return None

            room = await session.get(RentalRoom, job.rental_room_id)
            group = await session.get(FacebookGroup, job.target_id)
            if (
                room is None
                or group is None
                or group.user_id != cfg.user_id
                or group.status != "available"
            ):
                job.attempt_count += 1
                schedule_job_retry(job, "Facebook group is missing or unavailable", now)
                if room is not None:
                    await aggregate_rental_room(session, room.id, now)
                await session.commit()
                return {
                    "config_id": str(cfg.id),
                    "room_id": str(job.rental_room_id) if job.rental_room_id else None,
                    "group_id": job.target_external_id,
                    "job_id": str(job.id),
                    "status": job.status,
                    "accepted": False,
                }

            run = TaskRun(
                user_id=cfg.user_id,
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
            job.error = None
            room.status = "posting"
            room.error = None
            cfg.last_post_at = now
            dispatch = {
                "job_id": job.id,
                "run_id": run.id,
                "room_id": room.id,
                "config_id": cfg.id,
                "group_id": group.id,
                "group_external_id": group.group_id,
                "message": room.caption,
                "media_paths": [
                    str(path)
                    for path in json.loads(room.media_paths_json or "[]")
                    if str(path)
                ],
            }
            await session.commit()

        try:
            result = await self._runner()(
                run_id=str(dispatch["run_id"]),
                page_ids=[],
                group_ids=[str(dispatch["group_id"])],
                personal_account_ids=[],
                message=dispatch["message"],
                link=None,
                media_paths=dispatch["media_paths"],
                publication_job_id=str(dispatch["job_id"]),
            )
        except Exception as exc:  # noqa: BLE001 - persist dispatch failure
            logger.warning("dispatch publication job %s failed: %s", dispatch["job_id"], exc)
            result = {"accepted": False, "error": str(exc), "task_item_ids": []}

        async with self._get_session() as session:
            job = await session.get(PublicationJob, dispatch["job_id"])
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
            if job.rental_room_id:
                await aggregate_rental_room(session, job.rental_room_id, now)
            await session.commit()
            return {
                "config_id": str(dispatch["config_id"]),
                "room_id": str(dispatch["room_id"]),
                "group_id": dispatch["group_external_id"],
                "job_id": str(job.id),
                "run_id": str(dispatch["run_id"]),
                "task_item_id": job.task_item_id,
                "status": job.status,
                "accepted": accepted,
            }


async def run_rental_posting(get_session=None) -> None:
    """Reconcile completed posts, then dispatch one due target per config."""
    if get_session is None:
        from app.db.postgres import session_context
        get_session = session_context
    try:
        await reconcile_publication_jobs(get_session)
        await RentalPostService(get_session).post_due()
    except Exception:
        logger.exception("rental posting failed")
