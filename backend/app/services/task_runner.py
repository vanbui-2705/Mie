"""TaskRunner — core task execution engine. Ported from CommentTaskManager.cs."""
from __future__ import annotations

import asyncio
import random
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.crypto import decrypt, encrypt
from app.db.postgres import session_context
from app.models.sqlmodels import FacebookAccount, Profile, TaskItem, TaskItemStatus, TaskLog, TaskRun, TaskRunStatus
from app.schemas import DelaySettingsDTO
from app.services.facebook_graph import execute_comment_action
from app.services.kiotproxy_client import ProxyEndpointData
from app.services.proxy_manager import DirectLease, ProxyLease


async def _find_profile_sql(session, uid: str):
    from sqlalchemy import select, func
    result = await session.execute(
        select(Profile).where(func.lower(Profile.uid) == uid.strip().lower()),
    )
    return result.scalar_one_or_none()


async def _find_facebook_account_sql(session, user_id, uid: str):
    from sqlalchemy import select, func
    result = await session.execute(
        select(FacebookAccount).where(
            FacebookAccount.user_id == user_id,
            func.lower(FacebookAccount.uid) == uid.strip().lower(),
        ),
    )
    return result.scalar_one_or_none()


def _token_enc(account: Profile | FacebookAccount) -> str:
    return account.user_token_enc if isinstance(account, FacebookAccount) else account.token_enc


def _account_uid(account: Profile | FacebookAccount) -> str:
    return account.uid


class TaskRunner:
    """
    Executes batch comment tasks (edit/delete/new_comment) using profiles
    + proxy pool. Single-task-at-a-time: start() cancels previous run.
    Fires SSE events through EventBus.
    """

    def __init__(self, get_session, proxy_manager, publish) -> None:
        self._get_session = get_session
        self._proxy_mgr = proxy_manager
        self._event_publish = publish
        self._stop_event: Optional[asyncio.Event] = None
        self._current_task: Optional[asyncio.Task] = None
        self._active_run_id: Optional[str] = None
        self._stats: Dict[str, int] = {}
        self._log_index: int = 0

    @property
    def is_running(self) -> bool:
        return self._current_task is not None and not self._current_task.done()

    @property
    def active_run_id(self) -> Optional[str]:
        return self._active_run_id

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    async def start(
        self,
        action: str,
        max_threads: int,
        delay: DelaySettingsDTO,
        uid_text: str,
        link_text: str,
        post_text: str,
        new_text: str,
        image_input: str,
    ) -> str:
        """Cancel previous run and start fresh. Returns run_id (UUID string)."""
        self.stop()
        stop_event = asyncio.Event()
        self._stop_event = stop_event
        run_id = str(uuid.uuid4())
        self._active_run_id = run_id
        self._log_index = 0

        tasks = self._build_tasks(action, uid_text, link_text, post_text)
        images = _load_images(image_input)
        variants = _load_text_variants(new_text)
        rnd = random.Random()
        self._stats = {"total": len(tasks)}
        await self._pub_stats()

        self._current_task = asyncio.ensure_future(
            self._run(run_id, action, max_threads, delay, tasks, variants, images, rnd, stop_event)
        )
        self._current_task.add_done_callback(lambda _: self._clear_run(run_id))
        return run_id

    async def run_existing(
        self,
        run_id: str,
        action: str,
        max_threads: int,
        delay: DelaySettingsDTO,
        uid_text: str,
        link_text: str,
        post_text: str,
        new_text: str,
        image_input: str,
    ) -> str:
        """Run a DB-created pending task. Used by the production worker."""
        self.stop()
        stop_event = asyncio.Event()
        self._stop_event = stop_event
        self._active_run_id = run_id
        self._log_index = 0

        tasks = self._build_tasks(action, uid_text, link_text, post_text)
        images = _load_images(image_input)
        variants = _load_text_variants(new_text)
        rnd = random.Random()
        self._stats = {"total": len(tasks)}
        await self._pub_stats()

        self._current_task = asyncio.ensure_future(
            self._run(
                run_id,
                action,
                max_threads,
                delay,
                tasks,
                variants,
                images,
                rnd,
                stop_event,
                create_run=False,
            )
        )
        self._current_task.add_done_callback(lambda _: self._clear_run(run_id))
        await self._current_task
        return run_id

    def _clear_run(self, run_id: str) -> None:
        if self._active_run_id == run_id:
            self._active_run_id = None

    # -- task list builder ------------------------------------------------------

    @staticmethod
    def _build_tasks(action, uid_text, link_text, post_text):
        tasks = []
        if action == "new_comment":
            for line in post_text.replace("\r\n", "\n").split("\n"):
                line = line.strip()
                if line:
                    tasks.append({"uid": "", "link": line})
        else:
            uids = [l.strip() for l in uid_text.replace("\r\n", "\n").split("\n") if l.strip()]
            links = [l.strip() for l in link_text.replace("\r\n", "\n").split("\n") if l.strip()]
            for i in range(min(len(uids), len(links))):
                tasks.append({"uid": uids[i], "link": links[i]})
        return tasks

    # -- main loop -------------------------------------------------------------

    async def _run(
        self,
        run_id,
        action,
        max_threads,
        delay,
        tasks,
        variants,
        images,
        rnd,
        stop,
        create_run: bool = True,
    ):
        active_user_id = None
        # Persist or activate TaskRun row.
        async with session_context() as session:
            if create_run:
                run = TaskRun(
                    id=uuid.UUID(run_id),
                    status=TaskRunStatus.RUNNING,
                    action=action,
                    max_threads=max_threads,
                    delay_min=delay.min_seconds,
                    delay_max=delay.max_seconds,
                    delay_every_rounds=delay.every_rounds,
                    text_input_enc=encrypt("\n\n".join(variants)) if variants else None,
                    image_path="\n".join(images) if images else None,
                )
                session.add(run)
            else:
                run = await session.get(TaskRun, uuid.UUID(run_id))
                if run is not None:
                    run.status = TaskRunStatus.RUNNING
                    active_user_id = run.user_id
            await session.commit()

        # Resolve author UIDs
        checker = await self._first_profile(active_user_id)
        resolved = []
        for task in tasks:
            if stop.is_set():
                break
            uid = task["uid"].strip()
            if uid:
                resolved.append({"uid": uid, "link": task["link"]})
                continue
            if checker is None:
                await self._pub_log(stop, run_id, "", task["link"], action, "", "That bai",
                                    "Chưa có token để kiểm tra UID bằng Graph.")
                self._incr(0, 1, 1, 0)
                await self._pub_stats()
                continue
            try:
                token = decrypt(_token_enc(checker))
                from app.services.facebook_graph import resolve_author_uid
                res = await resolve_author_uid(task["link"], token)
                uid = res.get("uid") or ""
                if not uid:
                    await self._pub_log(stop, run_id, _account_uid(checker), task["link"], action, "", "That bai",
                        f"Không lấy được UID bằng Graph. {res.get('message', '')}")
                    self._incr(0, 1, 1, 0)
                    await self._pub_stats()
                    continue
                resolved.append({"uid": uid, "link": task["link"]})
            except Exception as ex:
                await self._pub_log(stop, run_id, _account_uid(checker), task["link"], action, "", "That bai", str(ex))
                self._incr(0, 1, 1, 0)
                await self._pub_stats()

        if not resolved or stop.is_set():
            await self._finish(run_id, not resolved)
            return

        # Round-robin batch
        groups = defaultdict(list)
        for t in resolved:
            groups[t["uid"]].append(t)
        batches = _uid_batches(list(groups.values()), max(1, max_threads))

        round_num = 0
        blocked: Dict[str, dict] = {}

        for bi, batch in enumerate(batches):
            if stop.is_set():
                break
            active = [t for t in batch if t["uid"] not in blocked]
            skipped = len(batch) - len(active)
            if skipped:
                self._incr(0, skipped, skipped, 0)
                await self._pub_stats()
            if not active:
                continue

            for task in active:
                await self._pub_log(stop, run_id, task["uid"], task["link"], action, "", "Cho chay", "")

            await asyncio.gather(
                *[self._process_one(run_id, t, action, variants, images, rnd, stop, blocked)
                  for t in active],
                return_exceptions=True,
            )

            round_num += 1
            if stop.is_set():
                break
            if _should_delay(delay, round_num, bi < len(batches) - 1):
                secs = _pick_delay(delay, rnd)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=secs)
                except asyncio.TimeoutError:
                    pass
                if stop.is_set():
                    break

        await self._finish(run_id, not resolved)

    # -- single task -----------------------------------------------------------

    async def _process_one(self, run_id, task, action, variants, images, rnd, stop, blocked):
        uid = task["uid"]
        link = task["link"]

        if uid in blocked:
            await self._pub_log(stop, run_id, uid, link, action, "", "Dung profile",
                                f"Profile đã dừng do {blocked[uid].get('status', '')}.")
            self._incr(0, 1, 1, 0)
            await self._pub_stats()
            return

        profile = await self._find_profile_any(run_id, uid)
        if profile is None:
            await self._pub_log(stop, run_id, uid, link, action, "", "That bai",
                                "UID comment không có trong tab Hồ sơ.")
            self._incr(0, 1, 1, 0)
            await self._pub_stats()
            return

        lease = None
        waiting = False
        try:
            if self._proxy_mgr.is_started:
                lease = await self._proxy_mgr.try_acquire_async()
                if lease is None:
                    await self._pub_log(stop, run_id, uid, link, action, "", "Dang cho proxy",
                                        "Proxy đang lấy IP mới hoặc chưa sẵn sàng.")
                    self._incr(0, 0, 0, 1)
                    await self._pub_stats()
                    waiting = True
                    lease = await self._proxy_mgr.acquire(stop)
                    self._incr(0, 0, 0, -1)
                    waiting = False

            ep = lease.endpoint if isinstance(lease, ProxyLease) else None
            proxy_url = ep.proxy_url() if ep else None
            proxy_display = ep.display if ep else "Direct"
            img = _pick(images, rnd)
            txt = _pick(variants, rnd) or ""
            token = decrypt(_token_enc(profile))

            await self._pub_log(stop, run_id, uid, link, action, proxy_display, "Dang chay",
                                f"Ảnh: {img.split('/')[-1]}" if img else "")

            result = await execute_comment_action(
                action=action,
                comment_link=link,
                token=token,
                new_text=txt or None,
                image_path=img,
                proxy_url=proxy_url,
            )

            if stop.is_set():
                if lease:
                    lease.dispose()
                pd = lease.endpoint.display if isinstance(lease, ProxyLease) else ""
                await self._pub_log(stop, run_id, uid, link, action, pd, "Dung",
                                    "Đã nhận lệnh dừng.")
                self._incr(processed=1)
                await self._pub_stats()
                return

            if isinstance(lease, ProxyLease):
                lease.mark_used()

            # Update profile in DB
            async with session_context() as session:
                db_p = await self._reload_task_account(session, run_id, uid)
                if db_p:
                    if hasattr(db_p, "task_count"):
                        db_p.task_count += 1
                    ok = result.get("success", False)
                    db_p.last_error = "" if ok else result.get("message", "")
                    if result.get("token_issue"):
                        ti = result["token_issue"]
                        db_p.token_status = _ti_status(ti)
                        blocked[uid] = ti
                        await self._publish("profile", "profile", {
                            "uid": _account_uid(db_p),
                            "token_status": db_p.token_status.value,
                            "last_error": result.get("message", ""),
                            "task_count": getattr(db_p, "task_count", 0),
                        })
                    await session.commit()

            status = "Thanh cong" if result.get("success") else blocked.get(uid, {}).get("status", "That bai")
            out = link
            if result.get("success") and action == "new_comment":
                out = result.get("output_link", link)
            err = result.get("message", "") if not result.get("success") else ""
            output_link = out if result.get("success") and action == "new_comment" else None
            await self._pub_log(stop, run_id, uid, link, action, proxy_display, status, err, output_link)

            if result.get("success"):
                self._incr(success=1)
            else:
                self._incr(failed=1)
            self._incr(processed=1)
            await self._pub_stats()

        except asyncio.CancelledError:
            if waiting:
                self._incr(0, 0, 0, -1)
            if isinstance(lease, ProxyLease):
                lease.dispose()
            pd = lease.endpoint.display if isinstance(lease, ProxyLease) else ""
            await self._pub_log(stop, run_id, uid, link, action, pd, "Dung",
                                "Đã nhận lệnh dừng.")
            self._incr(processed=1)
            await self._pub_stats()
        except Exception as ex:
            if waiting:
                self._incr(0, 0, 0, -1)
            if isinstance(lease, ProxyLease):
                lease.mark_used()
            pd = lease.endpoint.display if isinstance(lease, ProxyLease) else ""
            await self._pub_log(stop, run_id, uid, link, action, pd, "That bai", str(ex))
            self._incr(failed=1, processed=1)
            await self._pub_stats()

    # -- internal helpers -------------------------------------------------------

    async def _find_profile_any(self, run_id: str, uid: str):
        async with session_context() as session:
            run = await session.get(TaskRun, uuid.UUID(run_id))
            if run is not None and run.user_id is not None:
                account = await _find_facebook_account_sql(session, run.user_id, uid)
                if account is not None:
                    return account
            return await _find_profile_sql(session, uid)

    async def _first_profile(self, user_id=None):
        async with session_context() as session:
            from sqlalchemy import select
            if user_id is not None:
                r = await session.execute(
                    select(FacebookAccount)
                    .where(FacebookAccount.user_id == user_id)
                    .limit(1)
                )
                account = r.scalar_one_or_none()
                if account is not None:
                    return account
            r = await session.execute(select(Profile).limit(1))
            return r.scalar_one_or_none()

    async def _reload_task_account(self, session, run_id: str, uid: str):
        run = await session.get(TaskRun, uuid.UUID(run_id))
        if run is not None and run.user_id is not None:
            account = await _find_facebook_account_sql(session, run.user_id, uid)
            if account is not None:
                return account
        return await session.get(Profile, uid)

    async def _pub_log(self, stop, run_id, uid, link, action, proxy, status, error, output_link=None) -> None:
        if stop.is_set():
            return
        await self._publish("log", "log", {
            "run_id": run_id, "uid": uid, "comment_link": link,
            "action": action, "proxy": proxy, "status": status, "error": error,
            "output_link": output_link,
        })

    async def _pub_stats(self) -> None:
        await self._publish("stats", "stats", dict(self._stats))

    async def _publish(self, channel: str, event_type: str, data: dict) -> None:
        if channel == "log":
            self._log_index += 1
            data = {
                "log_index": self._log_index,
                **data,
            }
            await self._persist_log(data)
        await self._event_publish(channel, event_type, data)

    async def _persist_log(self, data: dict) -> None:
        run_id = data.get("run_id")
        if not run_id:
            return
        async with session_context() as session:
            session.add(TaskLog(
                run_id=uuid.UUID(run_id),
                log_index=data.get("log_index", 0),
                uid=data.get("uid") or None,
                comment_link=data.get("comment_link") or "",
                action=data.get("action") or "",
                proxy=data.get("proxy") or "",
                status=data.get("status") or "",
                error=data.get("error") or None,
                output_link=data.get("output_link") or None,
            ))
            await self._sync_task_item(session, data)
            await session.commit()

    async def _finish(self, run_id: str, empty: bool) -> None:
        async with session_context() as session:
            run = await session.get(TaskRun, uuid.UUID(run_id))
            if run is None:
                return
            if run.status == TaskRunStatus.CANCELED:
                run.finished_at = datetime.now(timezone.utc)
                await session.commit()
                return
            run.status = TaskRunStatus.FAILED if empty else TaskRunStatus.SUCCESS
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()

    async def _sync_task_item(self, session, data: dict) -> None:
        run_id = data.get("run_id")
        link = data.get("comment_link") or ""
        if not run_id or not link:
            return
        from sqlalchemy import select

        query = select(TaskItem).where(
            TaskItem.run_id == uuid.UUID(run_id),
            TaskItem.target_link == link,
        )
        uid = data.get("uid") or None
        if uid:
            query = query.where(TaskItem.uid == uid)
        result = await session.execute(query.order_by(TaskItem.item_index).limit(1))
        item = result.scalar_one_or_none()
        if item is None:
            return
        item_status = _task_item_status_from_log(data.get("status") or "")
        if item_status is not None:
            item.status = item_status
        item.error = data.get("error") or None
        item.output_link = data.get("output_link") or None

    def _incr(self, success=0, failed=0, processed=0, waiting_proxy=0) -> None:
        s = self._stats
        s.setdefault("total", 0)
        s["processed"] = max(0, s.get("processed", 0) + processed)
        s["success"] = max(0, s.get("success", 0) + success)
        s["failed"] = max(0, s.get("failed", 0) + failed)
        s["waiting_proxy"] = max(0, s.get("waiting_proxy", 0) + waiting_proxy)
        self._stats = s


# -- module-level helpers -------------------------------------------------------

def _load_images(image_input: str) -> List[str]:
    if not image_input or not image_input.strip():
        return []
    import os
    exts = frozenset({
        ".jpg", ".jpeg", ".jfif", ".pjpeg", ".pjp",
        ".png", ".gif", ".webp", ".bmp", ".dib",
        ".tif", ".tiff", ".heic", ".heif", ".avif",
        ".ico", ".svg",
    })
    results: List[str] = []
    for line in image_input.replace("\r\n", "\n").split("\n"):
        line = line.strip().strip('"')
        if not line:
            continue
        if os.path.isfile(line):
            ext = os.path.splitext(line)[1].lower()
            if ext in exts:
                results.append(os.path.abspath(line))
        elif os.path.isdir(line):
            try:
                for root, _ds, files in os.walk(line):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in exts:
                            results.append(os.path.abspath(os.path.join(root, f)))
            except OSError:
                for f in os.listdir(line):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in exts:
                        results.append(os.path.abspath(os.path.join(line, f)))
    seen: set = set()
    out: List[str] = []
    for img in results:
        k = img.lower()
        if k not in seen:
            seen.add(k)
            out.append(img)
    return out


def _task_item_status_from_log(status: str) -> TaskItemStatus | None:
    if status in ("Cho chay", "Dang chay", "Dang cho proxy"):
        return TaskItemStatus.RUNNING
    if status == "Thanh cong":
        return TaskItemStatus.SUCCESS
    if status == "Dung":
        return TaskItemStatus.CANCELED
    if status in ("That bai", "Dung profile"):
        return TaskItemStatus.FAILED
    return None


def _load_text_variants(text_input: str) -> List[str]:
    if not text_input or not text_input.strip():
        return []
    n = text_input.replace("\r\n", "\n").strip()
    blocks = [b.strip() for b in n.split("\n\n") if b.strip()]
    return blocks if blocks else [n]


def _pick(items: List[str], rnd: random.Random) -> Optional[str]:
    if not items:
        return None
    return items[rnd.randint(0, len(items) - 1)]


def _ti_status(issue: dict) -> str:
    kind = issue.get("kind", "")
    if kind == "Checkpoint":
        return "Checkpoint"
    if kind == "Token out":
        return "Token out"
    return "Die"


def _should_delay(d, rounds: int, has_more: bool) -> bool:
    return (
        has_more
        and d.enabled
        and d.every_rounds > 0
        and rounds % d.every_rounds == 0
    )


def _pick_delay(d, rnd: random.Random) -> int:
    lo, hi = min(d.min_seconds, d.max_seconds), max(d.min_seconds, d.max_seconds)
    if hi <= lo:
        return lo
    return rnd.randint(lo, hi)


def _uid_batches(groups: List[List[dict]], batch: int) -> List[List[dict]]:
    """Round-robin batch: take 1 from each group per round."""
    queues = [list(g) for g in groups if g]
    batches: List[List[dict]] = []
    cursor = 0
    while queues:
        row: List[dict] = []
        take = min(batch, len(queues))
        for _ in range(take):
            if cursor >= len(queues):
                cursor = 0
            row.append(queues[cursor].pop(0))
            if not queues[cursor]:
                queues.pop(cursor)
                if cursor >= len(queues):
                    cursor = 0
            else:
                cursor = (cursor + 1) % len(queues) if queues else 0
        if row:
            batches.append(row)
    return batches
