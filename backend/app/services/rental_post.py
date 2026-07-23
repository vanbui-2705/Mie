"""RentalPostService — publishes rental rooms to matched Facebook groups
on a throttled, per-config schedule with retry handling.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.models.sqlmodels import (
    RentalConfig,
    RentalRoom,
    TaskRun,
    TaskRunStatus,
    CommentAction,
    FacebookGroup,
)

logger = logging.getLogger("flowmeta.rental_post")
MAX_RETRIES = 3


class RentalPostService:
    """Posts due RentalRoom listings to their matched Facebook groups.

    One call to `post_due` posts at most one remaining Facebook group per
    eligible RentalConfig (throttled by `post_spacing_seconds`), so repeated
    scheduler ticks gradually drain the backlog of matched groups per room.
    """

    def __init__(self, get_session, run_post=None):
        self._get_session = get_session
        self._run_post = run_post

    def _runner(self):
        if self._run_post is not None:
            return self._run_post
        from app.routers.page_tasks import _run_page_post_task
        return _run_page_post_task

    async def post_due(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        fired: list[dict] = []
        async with self._get_session() as session:
            configs = list((await session.execute(select(RentalConfig).where(
                RentalConfig.auto_post == True,  # noqa: E712
                RentalConfig.status == "active",
            ))).scalars())

            for cfg in configs:
                if cfg.last_post_at and (now - cfg.last_post_at) < timedelta(seconds=cfg.post_spacing_seconds):
                    continue

                room = (await session.execute(select(RentalRoom).where(
                    RentalRoom.config_id == cfg.id, RentalRoom.status == "new",
                ).order_by(RentalRoom.created_at).limit(1))).scalar_one_or_none()
                if room is None:
                    continue

                group_ids = json.loads(room.matched_group_ids_json or "[]")
                posted = json.loads(room.post_urls_json or "{}")
                remaining = [g for g in group_ids if g not in posted]

                if not remaining:
                    room.status = "posted"
                    room.posted_at = now
                    await session.commit()
                    continue

                # Resolve remaining fbids to FacebookGroup rows, skipping any
                # that don't resolve, until we find one we can actually post.
                fbid = None
                row = None
                for candidate in remaining:
                    candidate_row = (await session.execute(select(FacebookGroup).where(
                        FacebookGroup.user_id == cfg.user_id,
                        FacebookGroup.group_id == candidate,
                    ))).scalar_one_or_none()
                    if candidate_row is None:
                        logger.warning(
                            "rental room %s: facebook group_id %s not found for user %s, skipping",
                            room.id, candidate, cfg.user_id,
                        )
                        continue
                    fbid = candidate
                    row = candidate_row
                    break

                if row is None:
                    # None of the remaining fbids resolved to a group row.
                    # This is NOT success — leave the room out of "posted" so
                    # it doesn't silently vanish from the queue with 0 posts.
                    room.status = "waiting_groups"
                    room.error = f"no matching facebook groups resolved for {remaining}"
                    cfg.last_post_at = now
                    await session.commit()
                    fired.append({
                        "config_id": str(cfg.id), "room_id": str(room.id),
                        "group_id": None, "status": room.status, "skipped": True,
                    })
                    continue

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

                try:
                    await self._runner()(
                        run_id=str(run.id),
                        page_ids=[],
                        group_ids=[str(row.id)],
                        personal_account_ids=[],
                        message=room.caption,
                        link=None,
                        media_paths=[],
                    )
                    posted[fbid] = str(run.id)
                    room.post_urls_json = json.dumps(posted)
                    still_remaining = [g for g in group_ids if g not in posted]
                    if not still_remaining:
                        room.status = "posted"
                        room.posted_at = now
                    else:
                        room.status = "new"
                    room.error = None
                except Exception as exc:  # noqa: BLE001 - persist failure onto room
                    room.retry_count += 1
                    room.status = "error" if room.retry_count >= MAX_RETRIES else "new"
                    room.error = str(exc)
                    logger.warning("post room %s failed: %s", room.id, exc)

                cfg.last_post_at = now
                await session.commit()
                fired.append({
                    "config_id": str(cfg.id), "room_id": str(room.id),
                    "group_id": fbid, "status": room.status,
                })

        return fired


async def run_rental_posting(get_session=None) -> None:
    """Post one throttled batch of due rental rooms.

    `get_session` is injectable so tests can pass the shared SQLite test
    session instead of the production Postgres `session_context`.
    """
    if get_session is None:
        from app.db.postgres import session_context
        get_session = session_context
    try:
        await RentalPostService(get_session).post_due()
    except Exception:
        logger.exception("rental posting failed")
