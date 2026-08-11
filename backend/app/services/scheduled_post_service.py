"""Scheduled post service — computes next fire time and enqueues due posts."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt
from app.models.sqlmodels import (
    FacebookAccount,
    FacebookGroup,
    FacebookPage,
    ScheduledPost,
    TaskRun,
    TaskRunStatus,
)

logger = logging.getLogger("flowmeta.scheduled_posts")

# Strong references to the post coroutines we hand to the event loop. asyncio
# only keeps a weak reference to a running task, so without this the garbage
# collector is free to drop a scheduled post before it has posted anything.
_running_posts: set = set()


class ScheduledPostNotFound(Exception):
    pass


class ScheduleTargetError(Exception):
    """Raised when a schedule points at targets its owner does not hold."""


SessionProvider = Callable[[], AsyncIterator[AsyncSession]]

TARGET_MODELS = {
    "page": FacebookPage,
    "group": FacebookGroup,
    "personal": FacebookAccount,
}
TARGET_KEYS = {
    "page": "page_ids",
    "group": "group_ids",
    "personal": "personal_account_ids",
}


async def resolve_owned_targets(
    session: AsyncSession, user_id: uuid.UUID, targets: list[str],
) -> tuple[dict[str, list[str]], list[str]]:
    """Split `type:uuid` targets into publisher lists, keeping only this user's.

    The publisher loads each target by primary key and posts with the token
    stored on it, so a target that belongs to someone else is not a broken
    reference — it is a post made as them. Ownership has to be settled here,
    before the ids leave this function.
    """
    lists: dict[str, list[str]] = {
        "page_ids": [], "group_ids": [], "personal_account_ids": [],
    }
    rejected: list[str] = []
    for raw in targets:
        value = str(raw or "").strip()
        try:
            target_type, raw_id = value.split(":", 1)
            target_id = uuid.UUID(raw_id)
        except (ValueError, AttributeError):
            rejected.append(value)
            continue
        model = TARGET_MODELS.get(target_type)
        if model is None:
            rejected.append(value)
            continue
        target = await session.get(model, target_id)
        if target is None or target.user_id != user_id:
            rejected.append(value)
            continue
        lists[TARGET_KEYS[target_type]].append(str(target_id))
    return lists, rejected


class ScheduledPostService:
    def __init__(self, get_session: SessionProvider) -> None:
        self._get_session = get_session

    async def assert_targets_owned(self, user_id: uuid.UUID, targets: list[str]) -> None:
        async with self._get_session() as session:
            _, rejected = await resolve_owned_targets(session, user_id, targets)
        if rejected:
            raise ScheduleTargetError(
                "Không thể lên lịch cho mục tiêu không thuộc tài khoản này: "
                + ", ".join(rejected)
            )

    async def get_for_user(self, sp_id: uuid.UUID, user_id: uuid.UUID) -> ScheduledPost:
        async with self._get_session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            return sp

    async def list_for_user(self, user_id: uuid.UUID) -> list[ScheduledPost]:
        async with self._get_session() as session:
            result = await session.execute(
                select(ScheduledPost)
                .where(ScheduledPost.user_id == user_id)
                .order_by(ScheduledPost.created_at.desc())
            )
            return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        action: str,
        targets: list[str],
        message: str,
        link: str | None,
        media_paths: list[str],
        max_threads: int,
        start_at: datetime | None,
        interval_seconds: int | None,
        stop_at: datetime | None,
        post_items: list[dict] | None = None,
    ) -> ScheduledPost:
        now = datetime.now(timezone.utc)
        initial_status = "scheduled"
        next_fire = start_at if start_at and start_at > now else now
        normalized_items = _normalize_post_items(message, link, media_paths, post_items)
        first_item = normalized_items[0] if normalized_items else {"message": message or "", "link": link, "media_paths": media_paths}

        sp = ScheduledPost(
            user_id=user_id,
            name=name,
            action=action,
            targets_json=json.dumps(targets) if targets else None,
            message=str(first_item.get("message") or "") or None,
            link=str(first_item.get("link") or "") or None,
            media_paths_json=json.dumps(first_item.get("media_paths") or []) if first_item.get("media_paths") else None,
            post_items_json=json.dumps(normalized_items) if normalized_items else None,
            next_item_index=0,
            max_threads=max(1, min(max_threads, 50)),
            start_at=start_at,
            interval_seconds=interval_seconds,
            next_fire_at=next_fire,
            stop_at=stop_at,
            status=initial_status,
        )
        async with self._get_session() as session:
            session.add(sp)
            await session.commit()
            await session.refresh(sp)
        return sp

    async def set_status(
        self, sp_id: uuid.UUID, user_id: uuid.UUID, status: str
    ) -> ScheduledPost:
        async with self._get_session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            sp.status = status
            if status == "paused":
                sp.next_fire_at = None
            elif status == "scheduled" and sp.next_fire_at is None:
                now = datetime.now(timezone.utc)
                sp.next_fire_at = sp.start_at if sp.start_at and sp.start_at > now else now
            session.add(sp)
            await session.commit()
            await session.refresh(sp)
            return sp

    async def update(
        self,
        *,
        sp_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        targets: list[str],
        message: str,
        link: str | None,
        max_threads: int,
        start_at: datetime | None,
        interval_seconds: int | None,
        stop_at: datetime | None,
        post_items: list[dict] | None = None,
    ) -> ScheduledPost:
        now = datetime.now(timezone.utc)
        normalized_items = _normalize_post_items(message, link, [], post_items)
        first_item = normalized_items[0] if normalized_items else {"message": message or "", "link": link, "media_paths": []}
        async with self._get_session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            sp.name = name
            sp.targets_json = json.dumps(targets) if targets else None
            sp.message = str(first_item.get("message") or "") or None
            sp.link = str(first_item.get("link") or "") or None
            sp.post_items_json = json.dumps(normalized_items) if normalized_items else None
            sp.next_item_index = min(sp.next_item_index or 0, max(len(normalized_items) - 1, 0))
            sp.max_threads = max(1, min(max_threads, 50))
            sp.start_at = start_at
            sp.interval_seconds = interval_seconds
            sp.stop_at = stop_at
            if sp.status != "paused":
                sp.status = "scheduled"
                sp.next_fire_at = start_at if start_at and start_at > now else now
            session.add(sp)
            await session.commit()
            await session.refresh(sp)
            return sp

    async def set_post_items(self, sp_id: uuid.UUID, user_id: uuid.UUID, post_items: list[dict]) -> ScheduledPost:
        async with self._get_session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            normalized_items = _normalize_post_items(sp.message or "", sp.link, [], post_items)
            first_item = normalized_items[0] if normalized_items else {"message": sp.message or "", "link": sp.link, "media_paths": []}
            sp.post_items_json = json.dumps(normalized_items) if normalized_items else None
            sp.next_item_index = min(sp.next_item_index or 0, max(len(normalized_items) - 1, 0))
            sp.message = str(first_item.get("message") or "") or None
            sp.link = str(first_item.get("link") or "") or None
            first_media = first_item.get("media_paths") or []
            sp.media_paths_json = json.dumps(first_media) if first_media else None
            session.add(sp)
            await session.commit()
            await session.refresh(sp)
            return sp

    async def set_media_paths(self, sp_id: uuid.UUID, user_id: uuid.UUID, media_paths: list[str]) -> ScheduledPost:
        async with self._get_session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            sp.media_paths_json = json.dumps(media_paths) if media_paths else None
            session.add(sp)
            await session.commit()
            await session.refresh(sp)
            return sp

    async def delete(self, sp_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._get_session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            await session.delete(sp)
            await session.commit()

    async def fire_now(self, sp_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        async with self._get_session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            sp.status = "scheduled"
            sp.next_fire_at = datetime.now(timezone.utc)
            session.add(sp)
            await session.commit()
        fired = await enqueue_due_posts(now=datetime.now(timezone.utc))
        return next((item for item in fired if item.get("scheduled_post_id") == str(sp_id)), {"scheduled_post_id": str(sp_id), "run_id": None, "status": "not_due"})


async def enqueue_due_posts(
    *,
    now: datetime | None = None,
    get_session: SessionProvider | None = None,
    create_background_task: Callable[[Awaitable[None]], object] | None = None,
) -> list[dict]:
    """Find scheduled posts due to fire, create a TaskRun and run it directly.

    Returns list of dicts with scheduled_post_id and run_id/status.
    Runs _run_page_post_task via asyncio.create_task — no HTTP context needed.
    """
    import asyncio
    from app.db.postgres import session_context

    now = now or datetime.now(timezone.utc)
    results: list[dict] = []

    session_provider = get_session or session_context
    task_creator = create_background_task or asyncio.create_task

    async with session_provider() as session:
        # skip_locked, so a fire-now request and the scheduler tick cannot both
        # claim the same row and post it twice. Whichever gets the lock first
        # advances next_fire_at; the other simply does not see the row.
        due = (await session.execute(
            select(ScheduledPost)
            .where(
                ScheduledPost.status == "scheduled",
                ScheduledPost.next_fire_at.is_not(None),
                ScheduledPost.next_fire_at <= now,
            )
            .with_for_update(skip_locked=True)
        )).scalars().all()

        for sp in due:
            targets = json.loads(sp.targets_json or "[]")
            lists, rejected = await resolve_owned_targets(session, sp.user_id, targets)
            if rejected:
                logger.warning(
                    "scheduled post %s lists targets user %s does not own: %s",
                    sp.id, sp.user_id, ", ".join(rejected),
                )
            if not any(lists.values()):
                # Nothing left to post to. Retrying every minute would only
                # repeat the same refusal, so stop and record why.
                sp.status = "error"
                sp.next_fire_at = None
                sp.last_error = (
                    "Không còn mục tiêu hợp lệ thuộc tài khoản này: "
                    + (", ".join(rejected) or "targets trống")
                )
                session.add(sp)
                await session.commit()
                continue

            logger.info("enqueueing scheduled post %s for user %s", sp.id, sp.user_id)
            item_index, post_item, post_count = _select_post_item(sp)
            post_message = str(post_item.get("message") or "")
            post_link = str(post_item.get("link") or "") or None
            post_media = [str(path) for path in (post_item.get("media_paths") or []) if str(path)]
            run = TaskRun(
                user_id=sp.user_id,
                status=TaskRunStatus.RUNNING,
                action=sp.action,
                max_threads=sp.max_threads,
                # Encrypted like every other writer of this column. It used to
                # store the post body in clear text.
                text_input_enc=encrypt(post_message) if post_message else None,
                image_path=None,
            )
            session.add(run)
            await session.flush()
            await session.refresh(run)

            sp.last_fired_at = now
            sp.last_error = None
            if sp.interval_seconds is None:
                sp.status = "completed"
                sp.next_fire_at = None
            else:
                proposed = now + timedelta(seconds=sp.interval_seconds)
                if sp.stop_at and proposed > sp.stop_at:
                    sp.status = "completed"
                    sp.next_fire_at = None
                else:
                    sp.next_fire_at = proposed
            if post_count > 0:
                sp.next_item_index = (item_index + 1) % post_count

            session.add(sp)
            await session.commit()

            from app.routers.page_tasks import _run_page_post_task
            _track(task_creator(
                _run_page_post_task(
                    run_id=str(run.id),
                    page_ids=lists["page_ids"],
                    group_ids=lists["group_ids"],
                    personal_account_ids=lists["personal_account_ids"],
                    message=post_message,
                    link=post_link,
                    media_paths=post_media,
                )
            ), sp.id)

            results.append({
                "scheduled_post_id": str(sp.id),
                "run_id": str(run.id),
                "post_item_index": item_index,
                "status": sp.status,
            })

    return results


def _track(task: object, sp_id: uuid.UUID) -> None:
    """Hold the task and surface its failure instead of losing it silently."""
    if not hasattr(task, "add_done_callback"):
        return
    _running_posts.add(task)

    def _done(finished) -> None:
        _running_posts.discard(finished)
        try:
            error = finished.exception()
        except Exception:  # cancelled, or not a future after all
            return
        if error is not None:
            logger.error("scheduled post %s failed while posting: %s", sp_id, error)

    task.add_done_callback(_done)


def _normalize_post_items(
    message: str | None,
    link: str | None,
    media_paths: list[str] | None,
    post_items: list[dict] | None,
) -> list[dict]:
    raw_items = post_items if isinstance(post_items, list) and post_items else [
        {"message": message or "", "link": link or "", "media_paths": media_paths or []}
    ]
    normalized: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item_message = str(raw.get("message") or "")
        item_link = str(raw.get("link") or "")
        item_media = raw.get("media_paths") or raw.get("media") or []
        if not isinstance(item_media, list):
            item_media = []
        clean_media = [str(path) for path in item_media if str(path)]
        if not item_message.strip() and not item_link.strip() and not clean_media:
            continue
        normalized.append({
            "message": item_message,
            "link": item_link,
            "media_paths": clean_media,
        })
    return normalized


def _select_post_item(sp: ScheduledPost) -> tuple[int, dict, int]:
    items: list[dict] = []
    if sp.post_items_json:
        try:
            parsed = json.loads(sp.post_items_json)
            if isinstance(parsed, list):
                items = _normalize_post_items(None, None, None, parsed)
        except json.JSONDecodeError:
            items = []
    if not items:
        try:
            media = json.loads(sp.media_paths_json or "[]")
        except json.JSONDecodeError:
            media = []
        items = _normalize_post_items(sp.message, sp.link, media if isinstance(media, list) else [], None)
    if not items:
        return 0, {"message": "", "link": "", "media_paths": []}, 0
    index = max(0, sp.next_item_index or 0) % len(items)
    return index, items[index], len(items)
