# Auto-Post Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recurring post scheduler so users can define a post package (content + media + targets + delay settings) that the backend fires on a schedule without manual intervention each time.

**Architecture:** Reuse the existing `/api/page-post-tasks` end-to-end execution logic. A new `scheduled_posts` table stores the recurring schedule spec; a lightweight in-process cron job (1-minute tick inside the FastAPI lifespan) creates `TaskRun` rows via the same internal functions the existing endpoint uses, kicking off immediate runs when it's time.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, PostgreSQL, pytest, Next.js + shadcn/ui (existing stack — no new dependencies).

**Global Constraints:**
- Python 3.12, net9.0 for the WinForms host only.
- All DB writes go through the existing `get_session` / `session_context` pattern.
- Tests use pytest + pytest-asyncio with fixtures matching `tests/conftest.py` style (shared async engine/event-loop).
- Frontend uses existing shadcn/ui components and `apiFetch` from `frontend/src/lib/api-client.ts`.
- No Alembic — add the table through `create_all_tables()` and raw `ALTER TABLE … ADD COLUMN IF NOT EXISTS` in `backend/app/db/postgres.py` (same pattern used for `browser_status` migration).

---

### File Structure

| File | Responsibility |
|---|---|
| `backend/app/models/sqlmodels.py` | New `ScheduledPost` ORM model |
| `backend/app/db/postgres.py` | Migration: `CREATE TABLE scheduled_posts` + `CREATE EXTENSION IF NOT EXISTS pg_cron if not exists` (or manual ticker) |
| `backend/app/services/scheduled_post_service.py` | Core business logic: enqueue ready posts, compute next fire time |
| `backend/app/routers/scheduled_posts.py` | REST endpoints (CRUD) |
| `backend/app/main.py` | Wire cron ticker into lifespan, add router |
| `backend/tests/test_scheduled_posts.py` | Backend unit tests |
| `backend/tests/test_scheduled_post_integration.py` | End-to-end API contract tests |
| `frontend/src/app/scheduled-posts/page.tsx` | New page for managing scheduled posts |
| `frontend/src/components/scheduled-posts/ScheduleForm.tsx` | Form component shared by create/edit dialog |
| `frontend/src/components/scheduled-posts/ScheduleList.tsx` | List/cancel/pause/resume table |

### Task 1: Database Model

**Files:**
- Modify: `backend/app/models/sqlmodels.py` (append after `ShareCampaign` model, before `ShareTarget`)
- Modify: `backend/app/db/postgres.py` (add migration SQL in `create_all_tables`)
- Test: `backend/tests/test_scheduled_posts.py`

**Interfaces:**
- Consumes: `Base` declarative class, `ForeignKey("users.id")`, `Enum` mappings (follow existing pattern)
- Produces: `ScheduledPost` SQLAlchemy model used by `ScheduledPostService` and the router

```python
# Add to backend/app/models/sqlmodels.py
# Insert after the ShareCampaign class (after line ~392) and before ShareTarget


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Human-readable label")
    action: Mapped[CommentAction] = mapped_column(
        Enum(CommentAction, name="comment_action", native_enum=False),
        nullable=False,
        default=CommentAction.POST_PAGE,
    )
    targets_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None, comment="JSON-encoded target IDs list"
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    link: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    media_paths_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None, comment="JSON array of saved media file paths"
    )
    max_threads: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    start_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
        comment="First fire time; NULL means fire immediately on enable",
    )
    interval_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=None,
        comment="Seconds between fires; NULL means one-shot",
    )
    next_fire_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True,
    )
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    stop_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
        comment="End time; after this no more fires",
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="paused")
    # status values: paused | scheduled | running | completed | failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_scheduled_posts_user_next_fire", user_id, next_fire_at),
    )
```

- [ ] **Step 3: Write the migration in `backend/app/db/postgres.py`**

Add at the bottom of `create_all_tables` (after the existing `ALTER TABLE` blocks):

```python
# --- scheduled_posts migration ---
async with engine.begin() as conn:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name            VARCHAR(255) NOT NULL,
            action          VARCHAR(32) NOT NULL DEFAULT 'post_page',
            targets_json    TEXT NULL,
            message         TEXT NULL,
            link            TEXT NULL,
            media_paths_json TEXT NULL,
            max_threads     INTEGER NOT NULL DEFAULT 3,
            start_at        TIMESTAMPTZ NULL,
            interval_seconds INTEGER NULL,
            next_fire_at    TIMESTAMPTZ NULL,
            last_fired_at   TIMESTAMPTZ NULL,
            stop_at         TIMESTAMPTZ NULL,
            status          VARCHAR(32) NOT NULL DEFAULT 'paused',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_scheduled_posts_user_next_fire
        ON scheduled_posts (user_id, next_fire_at)
    """))
```

This runs inside `await conn.run_sync(Base.metadata.create_all)` path — actually, since we're also creating the table via raw SQL for idempotent field additions, add these raw statements after the existing `conn.run_sync(Base.metadata.create_all)` block inside `create_all_tables`. That way the ORM `Base.metadata.create_all` handles the ORM-declared table and raw SQL adds the index (which ORM metadata won't manage for you).

Actually, to keep it consistent, declare the table via ORM so `create_all()` handles it, and only use raw SQL for the `ALTER TABLE` patches. Cleaner:

Move `ScheduledPost` to the ORM (done above), and in `postgres.py` only add new `ALTER TABLE … ADD COLUMN IF NOT EXISTS` blocks inside the existing raw-section if needed for future patches — for the first version the ORM `create_all()` covers everything.

- [ ] **Step 4: Write the failing test**

Create `backend/tests/test_scheduled_posts.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import session_context
from app.models.sqlmodels import ScheduledPost, User, TaskRunStatus
from app.services.scheduled_post_service import (
    ScheduledPostService,
    ScheduledPostNotFound,
    enqueue_due_posts,
)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
async def _ensure_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    # Ensure a user row exists for FK integrity
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    if result.scalar_one_or_none() is None:
        session.add(
            User(id=user_id, username=f"test-{user_id.hex[:8]}", password_hash=None)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_compute_next_fire_sets_next_fire_at(
    session: AsyncSession, user_id: uuid.UUID, _ensure_user: None
) -> None:
    now = datetime.now(timezone.utc)
    sp = ScheduledPost(
        user_id=user_id,
        name="Test post",
        action="post_page",
        max_threads=2,
        start_at=now - timedelta(hours=1),
        interval_seconds=3600,
        status="scheduled",
        next_fire_at=None,
    )
    session.add(sp)
    await session.commit()
    await session.refresh(sp)

    service = ScheduledPostService(get_session=lambda: session_context())
    updated = await service.compute_next_fire(sp.id)

    assert updated.next_fire_at is not None
    assert updated.next_fire_at > now
    # interval_seconds=3600 → next fire ≈ now + 3600s
    delta = updated.next_fire_at - now
    assert timedelta(minutes=59) < delta < timedelta(minutes=61)


@pytest.mark.asyncio
async def test_compute_next_fire_sets_none_when_interval_is_none(
    session: AsyncSession, user_id: uuid.UUID, _ensure_user: None
) -> None:
    now = datetime.now(timezone.utc)
    sp = ScheduledPost(
        user_id=user_id,
        name="One-shot",
        action="post_page",
        max_threads=2,
        start_at=now,
        interval_seconds=None,  # one-shot
        status="scheduled",
        next_fire_at=None,
    )
    session.add(sp)
    await session.commit()
    await session.refresh(sp)

    service = ScheduledPostService(get_session=lambda: session_context())
    updated = await service.compute_next_fire(sp.id)

    assert updated.status == "completed"
    assert updated.next_fire_at is None
    assert updated.last_fired_at is not None


@pytest.mark.asyncio
async def test_compute_next_fire_marks_completed_when_stop_at_exceeded(
    session: AsyncSession, user_id: uuid.UUID, _ensure_user: None
) -> None:
    now = datetime.now(timezone.utc)
    sp = ScheduledPost(
        user_id=user_id,
        name="Expired",
        action="post_page",
        max_threads=2,
        start_at=now - timedelta(hours=2),
        interval_seconds=600,
        stop_at=now - timedelta(minutes=30),  # already past
        status="scheduled",
        next_fire_at=now - timedelta(minutes=10),
    )
    session.add(sp)
    await session.commit()
    await session.refresh(sp)

    service = ScheduledPostService(get_session=lambda: session_context())
    updated = await service.compute_next_fire(sp.id)

    assert updated.status == "completed"
    assert updated.next_fire_at is None


@pytest.mark.asyncio
async def test_enqueue_due_posts_creates_task_run(
    session: AsyncSession, user_id: uuid.UUID, _ensure_user: None
) -> None:
    now = datetime.now(timezone.utc)
    sp = ScheduledPost(
        user_id=user_id,
        name="Due post",
        action="post_page",
        targets_json='["page-1"]',
        message="Hello scheduler",
        link=None,
        media_paths_json="[]",
        max_threads=3,
        start_at=now - timedelta(hours=1),
        interval_seconds=None,
        status="scheduled",
        next_fire_at=now - timedelta(minutes=1),  # overdue → ready to fire
    )
    session.add(sp)
    await session.commit()

    queued = await enqueue_due_posts(now=now)

    assert len(queued) == 1
    assert queued[0]["scheduled_post_id"] == str(sp.id)
    assert queued[0]["run_id"] is not None

    # Verify TaskRun row exists with correct fields
    from app.models.sqlmodels import TaskRun
    run = await session.get(TaskRun, uuid.UUID(queued[0]["run_id"]))
    assert run is not None
    assert run.status == TaskRunStatus.RUNNING
    assert run.max_threads == 3

    # Verify ScheduledPost was updated
    await session.refresh(sp)
    assert sp.last_fired_at is not None
    assert sp.status == "completed"  # one-shot → completed after firing


@pytest.mark.asyncio
async def test_enqueue_due_posts_skips_paused(
    session: AsyncSession, user_id: uuid.UUID, _ensure_user: None
) -> None:
    now = datetime.now(timezone.utc)
    sp = ScheduledPost(
        user_id=user_id,
        name="Paused post",
        action="post_page",
        targets_json='[]',
        message="should not fire",
        max_threads=2,
        start_at=now - timedelta(hours=1),
        interval_seconds=3600,
        status="paused",
        next_fire_at=now - timedelta(minutes=1),
    )
    session.add(sp)
    await session.commit()

    queued = await enqueue_due_posts(now=now)
    assert len(queued) == 0
```

- [ ] **Step 5: Run test to verify it fails**

```bash
cd backend && pytest tests/test_scheduled_posts.py -v
```

Expected: FAIL with `ImportError: cannot import name 'ScheduledPost' from 'app.models.sqlmodels'` or `ImportError: cannot import name 'ScheduledPostService' from 'app.services.scheduled_post_service'`.

- [ ] **Step 6: Write minimal implementation**

Create `backend/app/services/scheduled_post_service.py`:

```python
from __future__ import annotations

import uuid
import json
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Awaitable

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqlmodels import ScheduledPost, TaskRun, TaskRunStatus


class ScheduledPostNotFound(Exception):
    pass


class ScheduledPostService:
    def __init__(self, get_session: Callable[[], Awaitable[AsyncSession]]) -> None:
        self._session = get_session

    async def compute_next_fire(self, sp_id: uuid.UUID) -> ScheduledPost:
        async with self._session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None:
                raise ScheduledPostNotFound(str(sp_id))

            now = datetime.now(timezone.utc)
            if sp.stop_at and now >= sp.stop_at:
                sp.status = "completed"
                sp.next_fire_at = None
            elif sp.interval_seconds is None:
                sp.status = "completed"
                sp.next_fire_at = None
                sp.last_fired_at = now
            else:
                sp.last_fired_at = now
                if sp.start_at and sp.start_at > now:
                    sp.next_fire_at = sp.start_at
                elif sp.next_fire_at is None or sp.next_fire_at <= now:
                    sp.next_fire_at = now + timedelta(seconds=sp.interval_seconds)
                if sp.stop_at and sp.next_fire_at is not None and sp.next_fire_at > sp.stop_at:
                    sp.status = "completed"
                    sp.next_fire_at = None

            await session.commit()
            await session.refresh(sp)
            return sp

    async def create(self, *, user_id: uuid.UUID, name: str, action: str,
                     targets: list[str], message: str, link: str | None,
                     media_paths: list[str], max_threads: int,
                     start_at: datetime | None, interval_seconds: int | None,
                     stop_at: datetime | None) -> ScheduledPost:
        now = datetime.now(timezone.utc)
        next_fire = start_at if start_at and start_at > now else now

        if interval_seconds is None and (stop_at is not None and stop_at > now):
            pass  # one-shot respected

        sp = ScheduledPost(
            user_id=user_id,
            name=name,
            action=action,
            targets_json=json.dumps(targets),
            message=message,
            link=link,
            media_paths_json=json.dumps(media_paths),
            max_threads=max_threads,
            start_at=start_at,
            interval_seconds=interval_seconds,
            next_fire_at=next_fire if start_at is None or start_at <= now else start_at,
            stop_at=stop_at,
            status="scheduled" if (start_at is None or start_at <= now) else "paused",
        )
        async with self._session() as session:
            session.add(sp)
            await session.commit()
            await session.refresh(sp)
        return sp

    async def list_for_user(self, user_id: uuid.UUID, sp_id: uuid.UUID | None = None) -> list[ScheduledPost] | ScheduledPost:
        async with self._session() as session:
            if sp_id is not None:
                sp = await session.get(ScheduledPost, sp_id)
                if sp is None or sp.user_id != user_id:
                    raise ScheduledPostNotFound(str(sp_id))
                return sp
            result = await session.execute(
                select(ScheduledPost)
                .where(ScheduledPost.user_id == user_id)
                .order_by(ScheduledPost.created_at.desc())
            )
            return list(result.scalars().all())

    async def set_status(self, sp_id: uuid.UUID, user_id: uuid.UUID, status: str) -> ScheduledPost:
        allowed = {"paused", "scheduled", "completed", "failed"}
        if status not in allowed:
            raise ValueError(f"Invalid status: {status}")
        async with self._session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            sp.status = status
            if status == "paused":
                sp.next_fire_at = None
            elif status == "scheduled" and sp.next_fire_at is None:
                now = datetime.now(timezone.utc)
                sp.next_fire_at = sp.start_at if sp.start_at and sp.start_at > now else now
            await session.commit()
            await session.refresh(sp)
            return sp

    async def delete(self, sp_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._session() as session:
            sp = await session.get(ScheduledPost, sp_id)
            if sp is None or sp.user_id != user_id:
                raise ScheduledPostNotFound(str(sp_id))
            await session.delete(sp)
            await session.commit()


async def enqueue_due_posts(*, now: datetime | None = None) -> list[dict]:
    """Find all scheduled posts whose next_fire_at <= now and create a TaskRun for each."""
    from app.db.postgres import session_context

    now = now or datetime.now(timezone.utc)
    results: list[dict] = []

    async with session_context() as session:
        due = (await session.execute(
            select(ScheduledPost).where(
                ScheduledPost.status == "scheduled",
                ScheduledPost.next_fire_at.is_not(None),
                ScheduledPost.next_fire_at <= now,
            )
        )).scalars().all()

        for sp in due:
            from app.routers.page_tasks import _enqueue_page_post_run

            run = await _enqueue_page_post_run(
                session=session,
                user_id=sp.user_id,
                targets_json=sp.targets_json,
                message=sp.message or "",
                link=sp.link,
                media_paths_json=sp.media_paths_json,
                max_threads=sp.max_threads,
                action=sp.action,
            )
            await session.commit()
            await session.refresh(run)

            sp.last_fired_at = now
            sp_id_str = str(sp.id)
            if sp.interval_seconds is None:
                sp.status = "completed"
                sp.next_fire_at = None
            else:
                nxt = now + timedelta(seconds=sp.interval_seconds)
                if sp.stop_at and nxt > sp.stop_at:
                    sp.status = "completed"
                    sp.next_fire_at = None
                else:
                    sp.next_fire_at = nxt

            await session.commit()
            results.append({
                "scheduled_post_id": sp_id_str,
                "run_id": str(run.id),
                "status": sp.status,
            })

    return results
```

- [ ] **Step 7: Run test to verify it passes**

```bash
cd backend && pytest tests/test_scheduled_posts.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd E:\Tools\cmt_face\Comment_Edit_Delete
git add backend/app/models/sqlmodels.py backend/app/services/scheduled_post_service.py backend/tests/test_scheduled_posts.py
git commit -m "feat: add ScheduledPost ORM model and scheduled post service (TDD)"
```

---

### Task 2: Cron Ticker + Scheduled Router

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/app/routers/scheduled_posts.py`
- Test: `backend/tests/test_scheduled_posts.py` (extend)

**Interfaces:**
- Consumes: `ScheduledPostService`, `enqueue_due_posts`, `event_bus.publish`, `current_user` auth dependency
- Produces: REST endpoints `GET /api/scheduled-posts`, `POST /api/scheduled-posts`, `DELETE /api/scheduled-posts/{id}`, `POST /api/scheduled-posts/{id}/pause`, `POST /api/scheduled-posts/{id}/resume`; cron ticker fires `enqueue_due_posts`

- [ ] **Step 1: Write the failing test (extend existing file)**

Add to `backend/tests/test_scheduled_posts.py`:

```python
from httpx import AsyncClient, ASGITransport
from app.main import app as fastapi_app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(client: AsyncClient, user_id: uuid.UUID) -> dict[str, str]:
    # Use the test user token — match what current_user dependency accepts
    # See app/auth.py get_or_create_default_user pattern for test tokens
    return {"Authorization": f"Bearer test-{user_id.hex}"}


@pytest.mark.asyncio
async def test_create_scheduled_post_returns_201(
    client: AsyncClient, auth_headers: dict[str, str], user_id: uuid.UUID
) -> None:
    payload = {
        "name": "Daily promo",
        "action": "post_page",
        "targets": ["page-abc"],
        "message": "Uu dai hom nay!",
        "link": "https://example.com",
        "max_threads": 3,
        "start_at": None,
        "interval_seconds": 86400,
    }
    resp = await client.post("/api/scheduled-posts", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Daily promo"
    assert body["status"] == "scheduled"
    assert uuid.UUID(body["id"]) is not None


@pytest.mark.asyncio
async def test_list_scheduled_posts_returns_only_own(
    client: AsyncClient, auth_headers: dict[str, str], user_id: uuid.UUID,
    _ensure_user: None,
) -> None:
    # Pre-seed one entry
    async with session_context() as session:
        sp = ScheduledPost(
            user_id=user_id,
            name="Mine",
            action="post_page",
            status="scheduled",
        )
        session.add(sp)
        other_id = uuid.uuid4()
        sp2 = ScheduledPost(
            user_id=other_id,
            name="Not mine",
            action="post_page",
            status="scheduled",
        )
        session.add(sp2)
        await session.commit()

    resp = await client.get("/api/scheduled-posts", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Mine"


@pytest.mark.asyncio
async def test_pause_sets_status_to_paused(
    client: AsyncClient, auth_headers: dict[str, str], user_id: uuid.UUID,
    _ensure_user: None,
) -> None:
    async with session_context() as session:
        sp = ScheduledPost(
            user_id=user_id,
            name="Pausable",
            action="post_page",
            status="scheduled",
            next_fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(sp)
        await session.commit()
        sp_id = str(sp.id)

    resp = await client.post(f"/api/scheduled-posts/{sp_id}/pause", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "paused"
    assert body["next_fire_at"] is None


@pytest.mark.asyncio
async def test_delete_returns_204(
    client: AsyncClient, auth_headers: dict[str, str], user_id: uuid.UUID,
    _ensure_user: None,
) -> None:
    async with session_context() as session:
        sp = ScheduledPost(user_id=user_id, name="To delete", action="post_page")
        session.add(sp)
        await session.commit()
        sp_id = str(sp.id)

    resp = await client.delete(f"/api/scheduled-posts/{sp_id}", headers=auth_headers)
    assert resp.status_code == 204

    with pytest.raises(ScheduledPostNotFound):
        async with session_context() as session:
            await session.get(ScheduledPost, uuid.UUID(sp_id))
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && pytest tests/test_scheduled_posts.py::test_create_scheduled_post_returns_201 -v
```

Expected: FAIL — `ImportError` for the router, or `404` for `/api/scheduled-posts`.

- [ ] **Step 3: Write router and wire cron**

**Modify `backend/app/main.py`** — add imports and router:

```python
# Add to imports section
from app.routers import (
    auth, browser_sessions, comment_tasks, extension_connector,
    facebook_accounts, facebook_oauth, graph, health, page_tasks,
    profiles, proxy, settings as settings_router, tasks, scheduled_posts,  # <-- add
)

# In lifespan(), after runner = TaskRunner(...):
app.state.scheduled_post_service = ScheduledPostService(get_session=get_session)

# After all router registrations (around line after router mounts):
app.include_router(scheduled_posts.router)

# After all router setup in lifespan, add the cron ticker:
import asyncio

async def _scheduler_tick() -> None:
    service: ScheduledPostService = app.state.scheduled_post_service
    from app.services.scheduled_post_service import enqueue_due_posts
    while True:
        try:
            await asyncio.sleep(60)
            await enqueue_due_posts()
        except asyncio.CancelledError:
            break
        except Exception:
            import logging
            logging.getLogger("flowmeta.scheduler").exception("scheduler tick failed")

lifespan_tasks.append(asyncio.create_task(_scheduler_tick()))
```

Then create `backend/app/routers/scheduled_posts.py`:

```python
"""Scheduled post CRUD + pause/resume endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import uuid
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db.postgres import get_session
from app.models.sqlmodels import User
from app.services.scheduled_post_service import ScheduledPostService, ScheduledPostNotFound

logger = logging.getLogger("flowmeta.scheduled_posts")
router = APIRouter(tags=["scheduled-posts"])


@router.get("/api/scheduled-posts", response_model=list[dict])
async def list_scheduled_posts(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    service = ScheduledPostService(get_session=lambda: _session_ctx(session))
    posts = await service.list_for_user(user.id)
    return [_serialize(p) for p in posts]


@router.post("/api/scheduled-posts", response_model=dict, status_code=201)
async def create_scheduled_post(
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = ScheduledPostService(get_session=lambda: _session_ctx(session))
    try:
        interval = body.get("interval_seconds")
        sp = await service.create(
            user_id=user.id,
            name=str(body.get("name") or "Untitled"),
            action=str(body.get("action") or "post_page"),
            targets=_json_list(body, "targets"),
            message=str(body.get("message") or ""),
            link=body.get("link"),
            media_paths=_json_list(body, "media_paths"),
            max_threads=int(body.get("max_threads") or 3),
            start_at=_parse_dt(body.get("start_at")),
            interval_seconds=int(interval) if interval is not None else None,
            stop_at=_parse_dt(body.get("stop_at")),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(sp)


@router.delete("/api/scheduled-posts/{sp_id}", status_code=204)
async def delete_scheduled_post(
    sp_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    service = ScheduledPostService(get_session=lambda: _session_ctx(session))
    try:
        await service.delete(uuid.UUID(sp_id), user.id)
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found")


@router.post("/api/scheduled-posts/{sp_id}/pause", response_model=dict)
async def pause_scheduled_post(
    sp_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = ScheduledPostService(get_session=lambda: _session_ctx(session))
    try:
        sp = await service.set_status(uuid.UUID(sp_id), user.id, "paused")
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    return _serialize(sp)


@router.post("/api/scheduled-posts/{sp_id}/resume", response_model=dict)
async def resume_scheduled_post(
    sp_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = ScheduledPostService(get_session=lambda: _session_ctx(session))
    try:
        sp = await service.set_status(uuid.UUID(sp_id), user.id, "scheduled")
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    return _serialize(sp)


def _serialize(sp: Any) -> dict:
    return {
        "id": str(sp.id),
        "user_id": str(sp.user_id),
        "name": sp.name,
        "action": sp.action,
        "targets": json.loads(sp.targets_json or "[]"),
        "message": sp.message,
        "link": sp.link,
        "media_paths": json.loads(sp.media_paths_json or "[]"),
        "max_threads": sp.max_threads,
        "start_at": sp.start_at.isoformat() if sp.start_at else None,
        "interval_seconds": sp.interval_seconds,
        "next_fire_at": sp.next_fire_at.isoformat() if sp.next_fire_at else None,
        "last_fired_at": sp.last_fired_at.isoformat() if sp.last_fired_at else None,
        "stop_at": sp.stop_at.isoformat() if sp.stop_at else None,
        "status": sp.status,
        "created_at": sp.created_at.isoformat(),
        "updated_at": sp.updated_at.isoformat(),
    }


def _json_list(body: dict, key: str) -> list[str]:
    raw = body.get(key)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


from collections.abc import AsyncGenerator
@asynccontextmanager
async def _session_ctx(session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    yield session
```

**Critical integration point — `enqueue_due_posts` calls `_enqueue_page_post_run`:**
Extract the internal task-creation logic from `page_tasks.py` into a reusable function. Add to `backend/app/routers/page_tasks.py`:

```python
# Add these two public helpers at module level (outside the router), after the helper functions:

async def _enqueue_page_post_run(
    session: AsyncSession,
    user_id: uuid.UUID,
    targets_json: str | None,
    message: str,
    link: str | None,
    media_paths_json: str | None,
    max_threads: int,
    action: str,
) -> TaskRun:
    """Create a TaskRun + BackgroundTasks for the scheduled post runner."""
    from fastapi import BackgroundTasks
    from app.models.sqlmodels import TaskRun, TaskRunStatus, FacebookPage, FacebookGroup, FacebookAccount

    parsed = json.loads(targets_json or "[]")
    page_ids = [t for t in parsed if t.startswith("page:")]
    group_ids = [t for t in parsed if t.startswith("group:")]
    personal_ids = [t for t in parsed if t.startswith("personal:")]

    pages, groups, personal = [], [], []
    if page_ids:
        pages = (await session.execute(
            select(FacebookPage).where(FacebookPage.id.in_([p.split(":")[1] for p in page_ids]))
        )).scalars().all()
    # (same fetch for groups and personal as existing endpoint)

    total = len(pages) + len(groups) + len(personal)
    run = TaskRun(
        user_id=user_id,
        status=TaskRunStatus.RUNNING,
        action=CommentAction(action),
        max_threads=max(1, max_threads),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run

# Also expose _parse_post_targets importable from this module (it's already in page_tasks.py):
#   from app.routers.page_tasks import _parse_post_targets  # already importable
```

**Important:** Rather than duplicating business logic, `_enqueue_page_post_run` should delegate to the same task-runner that the existing endpoint uses. The simplest path is to keep `_run_page_post_task` callable via BackgroundTasks (already is) and determine invocation context: if called from within a request, use BackgroundTasks; if called from the cron ticker (no request context), invoke the task directly using the framework already set up in `worker.py`.

For MVP scope, the cron ticker can use `create_task` directly in the lifespan loop — it already has the same `runner` and `proxy_manager` singletons.

Wire into `backend/app/main.py` lifespan:

```python
# In lifespan, after existing services are wired:
from app.services.scheduled_post_service import ScheduledPostService
sps = ScheduledPostService(get_session=get_session)
app.state.scheduled_post_service = sps

# Register the router:
app.include_router(scheduled_posts.router)

# Start cron ticker in lifespan startup:
async def _scheduler_tick() -> None:
    import logging
    log = logging.getLogger("flowmeta.scheduler")
    while True:
        try:
            await asyncio.sleep(60)
            from app.services.scheduled_post_service import enqueue_due_posts
            results = await enqueue_due_posts()
            for r in results:
                log.info("scheduled post fired: sp=%s run=%s status=%s",
                         r["scheduled_post_id"], r["run_id"], r["status"])
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("scheduler tick error")

lifespan_tasks.append(asyncio.create_task(_scheduler_tick()))
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_scheduled_posts.py -v
```

Expected: All PASS (model, service, and router tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scheduled_posts.py backend/app/main.py backend/app/routers/page_tasks.py backend/tests/test_scheduled_posts.py
git commit -m "feat: add scheduled-posts REST router and 60s cron ticker"
```

---

### Task 3: Frontend Scheduled Posts Page

**Files:**
- Create: `frontend/src/app/scheduled-posts/page.tsx`
- Create: `frontend/src/components/scheduled-posts/ScheduleForm.tsx`
- Create: `frontend/src/components/scheduled-posts/ScheduleList.tsx`
- Modify: `frontend/src/components/layout/SideNav.tsx` (add nav link)
- Modify: `frontend/src/types/index.ts` (add types if needed)

**Interfaces:**
- Consumes: `apiFetch` from `@/lib/api-client.ts`, shadcn/ui components (Button, Input, Textarea, Table, Badge, Dialog), lucide-react icons
- Produces: `/scheduled-posts` page with CRUD UI

- [ ] **Step 1: Create the page skeleton**

File: `frontend/src/app/scheduled-posts/page.tsx`

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api-client";
import { ScheduleForm } from "@/components/scheduled-posts/ScheduleForm";
import { ScheduleList } from "@/components/scheduled-posts/ScheduleList";

type ScheduledPostItem = {
  id: string;
  name: string;
  action: string;
  targets: string[];
  message: string;
  link: string;
  max_threads: number;
  start_at: string | null;
  interval_seconds: number | null;
  next_fire_at: string | null;
  last_fired_at: string | null;
  stop_at: string | null;
  status: string;
  created_at: string;
};

export default function ScheduledPostsPage() {
  const [items, setItems] = useState<ScheduledPostItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/api/scheduled-posts");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ScheduledPostItem[];
      setItems(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không tải được lịch đăng");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleCreated = (item: ScheduledPostItem) => {
    setItems((prev) => [item, ...prev]);
    setShowForm(false);
  };

  const handleDeleted = (id: string) => {
    setItems((prev) => prev.filter((p) => p.id !== id));
  };

  const handleStatusChanged = (id: string, newStatus: string) => {
    setItems((prev) => prev.map((p) => (p.id === id ? { ...p, status: newStatus } : p)));
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>
            Lịch đăng bài
          </h1>
          <p className="text-[9pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
            Tạo nội dung đăng lặp lại hoặc một lần theo lịch hẹn giờ
          </p>
        </div>
        <Button
          className="btn-frost-primary h-8 gap-1.5 text-[9pt] text-white"
          style={{ backgroundColor: "var(--accent)" }}
          onClick={() => { setEditingId(null); setShowForm(true); }}
        >
          <Plus className="h-3.5 w-3.5" /> Tạo lịch mới
        </Button>
      </div>

      <ScheduleList
        items={items}
        loading={loading}
        onRefresh={load}
        onDeleted={handleDeleted}
        onStatusChanged={handleStatusChanged}
        onEdit={(id) => { setEditingId(id); setShowForm(true); }}
      />

      {showForm && (
        <Dialog open={showForm} onOpenChange={(open) => { setShowForm(open); if (!open) setEditingId(null); }}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editingId ? "Sửa lịch đăng" : "Tạo lịch đăng mới"}</DialogTitle>
            </DialogHeader>
            <ScheduleForm
              editId={editingId}
              onDone={(item) => {
                if (editingId) {
                  setItems((prev) => prev.map((p) => (p.id === item.id ? item : p)));
                } else {
                  handleCreated(item);
                }
                setShowForm(false);
                setEditingId(null);
              }}
              onCancel={() => { setShowForm(false); setEditingId(null); }}
            />
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write `ScheduleForm.tsx`**

File: `frontend/src/components/scheduled-posts/ScheduleForm.tsx`

```tsx
"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api-client";

type Props = {
  editId: string | null;
  onDone: (item: Record<string, unknown>) => void;
  onCancel: () => void;
};

const INTERVAL_OPTIONS = [
  { label: "Một lần (không lặp)", value: "0" },
  { label: "Mỗi 1 giờ", value: "3600" },
  { label: "Mỗi 3 giờ", value: "10800" },
  { label: "Mỗi 6 giờ", value: "21600" },
  { label: "Mỗi 12 giờ", value: "43200" },
  { label: "Mỗi 24 giờ", value: "86400" },
];

export function ScheduleForm({ editId, onDone, onCancel }: Props) {
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [link, setLink] = useState("");
  const [interval, setInterval] = useState("86400");
  const [maxThreads, setMaxThreads] = useState(3);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/api/scheduled-posts`);
        const all = (await res.json()) as Record<string, unknown>[];
        const found = all.find((p) => p.id === editId);
        if (cancelled || !found) return;
        setName(found.name as string);
        setMessage(found.message as string || "");
        setLink((found.link as string) || "");
        setInterval(String(found.interval_seconds ?? 0));
        setMaxThreads(found.max_threads as number || 3);
      } catch { /* noop in edit pre-load */ }
    })();
    return () => { cancelled = true; };
  }, [editId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) { toast.error("Nhập tên lịch đăng"); return; }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        action: "post_page",
        targets: [],      // TODO Phase 2: add target selector UI
        message: message,
        link: link || undefined,
        media_paths: [],  // TODO Phase 2: add media upload
        max_threads: maxThreads,
        interval_seconds: interval === "0" ? undefined : Number(interval),
      };
      const url = editId ? `/api/scheduled-posts/${editId}` : "/api/scheduled-posts";
      const method = editId ? "PUT" : "POST";
      const res = await apiFetch(url, {
        method,
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as Record<string, unknown>;
      toast.success(editId ? "Đã cập nhật lịch" : "Đã tạo lịch đăng");
      onDone(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Lỗi lưu lịch");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label className="text-[9pt]">Tên lịch</Label>
        <Input value={name} onChange={(e) => setName(e.target.value)} disabled={saving} />
      </div>
      <div className="space-y-1.5">
        <Label className="text-[9pt]">Nội dung bài đăng</Label>
        <Textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} disabled={saving} />
      </div>
      <div className="space-y-1.5">
        <Label className="text-[9pt]">Link đính kèm (tùy chọn)</Label>
        <Input value={link} onChange={(e) => setLink(e.target.value)} disabled={saving} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-[9pt]">Tần suất</Label>
          <Select value={interval} onValueChange={setInterval}>
            <SelectTrigger className="h-8 text-[9pt]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {INTERVAL_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-[9pt]">Threads</Label>
          <Input type="number" min={1} max={20} value={maxThreads} onChange={(e) => setMaxThreads(Number(e.target.value) || 1)} disabled={saving} className="h-8 text-[9pt]" />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>Huỷ</Button>
        <Button type="submit" disabled={saving} className="btn-frost-primary text-[9pt] text-white" style={{ backgroundColor: "var(--accent)" }}>
          {saving ? "Đang lưu..." : editId ? "Cập nhật" : "Tạo lịch"}
        </Button>
      </div>
    </form>
  );
}
```

- [ ] **Step 3: Write `ScheduleList.tsx`**

File: `frontend/src/components/scheduled-posts/ScheduleList.tsx`

```tsx
"use client";

import { useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/shared/EmptyState";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { Play, Pause, Trash2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api-client";

type ScheduledPostItem = {
  id: string;
  name: string;
  action: string;
  message: string;
  interval_seconds: number | null;
  next_fire_at: string | null;
  status: string;
};

type Props = {
  items: ScheduledPostItem[];
  loading: boolean;
  onRefresh: () => void;
  onDeleted: (id: string) => void;
  onStatusChanged: (id: string, status: string) => void;
  onEdit: (id: string) => void;
};

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    scheduled: "Đang chạy",
    paused: "Tạm dừng",
    completed: "Hoàn tất",
    failed: "Lỗi",
  };
  return <Badge variant="outline" className="text-[8pt]">{map[status] ?? status}</Badge>;
}

function formatInterval(seconds: number | null) {
  if (seconds === null || seconds === 0) return "Một lần";
  if (seconds < 3600) return `Mỗi ${seconds / 60:.0f} phút`;
  if (seconds < 86400) return `Mỗi ${seconds / 3600:.0f} giờ`;
  return `Mỗi ${seconds / 86400:.0f} ngày`;
}

export function ScheduleList({ items, loading, onRefresh, onDeleted, onStatusChanged, onEdit }: Props) {
  const changeStatus = useCallback(async (id: string, status: "paused" | "scheduled") => {
    try {
      const endpoint = status === "paused" ? `/api/scheduled-posts/${id}/pause` : `/api/scheduled-posts/${id}/resume`;
      const res = await apiFetch(endpoint, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { status: string };
      onStatusChanged(id, data.status);
      toast.success(status === "paused" ? "Đã tạm dừng" : "Đã tiếp tục");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Thao tác thất bại");
    }
  }, [onStatusChanged]);

  const deleteItem = useCallback(async (id: string) => {
    if (!confirm("Xóa lịch đăng này?")) return;
    try {
      const res = await apiFetch(`/api/scheduled-posts/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onDeleted(id);
      toast.success("Đã xóa");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Xóa thất bại");
    }
  }, [onDeleted]);

  if (loading) return <EmptyState message="Đang tải..." />;
  if (items.length === 0) return <EmptyState message="Chưa có lịch đăng nào. Bấm 'Tạo lịch mới' để bắt đầu." />;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <SectionEyebrow label="Danh sách lịch ({items.length})" />
        <Button variant="outline" className="h-7 px-2 text-[8pt]" onClick={onRefresh} disabled={loading}>
          <RefreshCw className="h-3 w-3 mr-1" /> Làm mới
        </Button>
      </div>
      <div className="rounded-md border overflow-auto" style={{ borderColor: "var(--border)" }}>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-[8pt]">Tên</TableHead>
              <TableHead className="text-[8pt]">Nội dung</TableHead>
              <TableHead className="text-[8pt]">Tần suất</TableHead>
              <TableHead className="text-[8pt]">Lần đăng sau</TableHead>
              <TableHead className="text-[8pt]">Trạng thái</TableHead>
              <TableHead className="text-right text-[8pt]">Hành động</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="text-[9pt] font-medium">{item.name}</TableCell>
                <TableCell className="text-[9pt] max-w-[200px] truncate">{item.message || item.link || "—"}</TableCell>
                <TableCell className="text-[9pt]">{formatInterval(item.interval_seconds)}</TableCell>
                <TableCell className="text-[9pt]">{item.next_fire_at ? new Date(item.next_fire_at).toLocaleString("vi-VN") : "—"}</TableCell>
                <TableCell><StatusBadge status={item.status} /></TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    {item.status === "scheduled" ? (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => changeStatus(item.id, "paused")}>
                        <Pause className="h-3 w-3" />
                      </Button>
                    ) : item.status === "paused" ? (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => changeStatus(item.id, "scheduled")}>
                        <Play className="h-3 w-3" />
                      </Button>
                    ) : null}
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onEdit(item.id)}>
                      <RefreshCw className="h-3 w-3" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => deleteItem(item.id)}>
                      <Trash2 className="h-3 w-3" style={{ color: "var(--danger)" }} />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add sidebar nav link**

Modify `frontend/src/components/layout/SideNav.tsx` — add the link to the existing navigation list (next to other pages like `/accounts`, `/auto-post`, etc.):

```tsx
{ href: "/scheduled-posts", label: "Lịch đăng", icon: CalendarIcon },
```

(CalendarIcon from lucide-react — add to existing icon imports.)

- [ ] **Step 5: Add Dialog imports**

Ensure `frontend/src/app/scheduled-posts/page.tsx` has:
```tsx
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
```

- [ ] **Step 6: Run frontend typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/scheduled-posts/ frontend/src/components/scheduled-posts/ frontend/src/components/layout/SideNav.tsx
git commit -m "feat: add scheduled posts frontend — page, form, list, sidebar"
```

---

### Task 4: Manual Trigger + Edge Cases

**Files:**
- Modify: `backend/app/routers/scheduled_posts.py`
- Modify: `backend/app/services/scheduled_post_service.py`
- Test: `backend/tests/test_scheduled_posts.py`

**Interfaces:**
- Adds `POST /api/scheduled-posts/{id}/fire-now` endpoint — forces immediate enqueue regardless of `next_fire_at`
- Adds validation for `max_threads` range (1–50)
- Handles `enqueue_due_posts` when the cron ticker fires but no Redis queue is available (direct `asyncio.create_task` call)

- [ ] **Step 1: Add fire-now endpoint test**

```python
@pytest.mark.asyncio
async def test_fire_now_enqueues_immediately(
    client: AsyncClient, auth_headers: dict[str, str], user_id: uuid.UUID, _ensure_user: None
) -> None:
    now = datetime.now(timezone.utc)
    sp = ScheduledPost(
        user_id=user_id,
        name="Future post",
        action="post_page",
        targets_json="[]",
        message="manual fire",
        max_threads=2,
        start_at=now + timedelta(hours=2),  # future — would not fire via cron
        interval_seconds=None,
        status="scheduled",
        next_fire_at=now + timedelta(hours=2),
    )
    async with session_context() as session:
        session.add(sp)
        await session.commit()
        sp_id = str(sp.id)

    resp = await client.post(f"/api/scheduled-posts/{sp_id}/fire-now", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
pytest tests/test_scheduled_posts.py::test_fire_now_enqueues_immediately -v
```

- [ ] **Step 3: Add endpoint + `fire_now` method**

Add to `ScheduledPostService`:
```python
async def fire_now(self, sp_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    async with self._session() as session:
        sp = await session.get(ScheduledPost, sp_id)
        if sp is None or sp.user_id != user_id:
            raise ScheduledPostNotFound(str(sp_id))
        # Override next_fire_at to now temporarily
        original = sp.next_fire_at
        sp.next_fire_at = datetime.now(timezone.utc)
        await session.commit()
        try:
            results = await enqueue_due_posts(now=sp.next_fire_at)
        finally:
            sp.next_fire_at = original
            await session.commit()
    if not results:
        raise ValueError("Không thể tạo tác vụ đăng — kiểm tra targets và nội dung")
    return {"run_id": results[0]["run_id"], "status": results[0]["status"]}
```

Add route to `scheduled_posts.py`:
```python
@router.post("/api/scheduled-posts/{sp_id}/fire-now", response_model=dict)
async def fire_now_scheduled_post(
    sp_id: str, user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = ScheduledPostService(get_session=lambda: _session_ctx(session))
    try:
        return await service.fire_now(uuid.UUID(sp_id), user.id)
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_scheduled_posts.py -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scheduled_post_service.py backend/app/routers/scheduled_posts.py backend/tests/test_scheduled_posts.py
git commit -m "feat: add fire-now endpoint and max_threads validation"
```

---

### Task 5: Integration Smoke Test

**Files:**
- Modify: `backend/tests/test_scheduled_post_integration.py` (create)

- [ ] **Step 1: Write integration test**

```python
"""End-to-end scheduled post contract test — same pattern as
tests/test_phase0_phase1_api_contract.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app as fastapi_app
from app.db.postgres import session_context
from app.models.sqlmodels import ScheduledPost, User

API_ROUTES = [
    "GET /api/scheduled-posts",
    "POST /api/scheduled-posts",
    "DELETE /api/scheduled-posts/{id}",
    "POST /api/scheduled-posts/{id}/pause",
    "POST /api/scheduled-posts/{id}/resume",
    "POST /api/scheduled-posts/{id}/fire-now",
]


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_contract_scheduled_posts_routes_exist(client: AsyncClient, user_id: uuid.UUID) -> None:
    async with session_context() as session:
        user = User(id=user_id, username=f"contract-{user_id.hex[:8]}", password_hash=None)
        session.add(user)
        sp = ScheduledPost(
            user_id=user_id, name="Contract post", action="post_page",
            targets_json="[]", status="scheduled", next_fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(sp)
        await session.commit()
        sp_id = str(sp.id)

    token = f"Bearer test-{user_id.hex}"
    headers = {"Authorization": token}

    # GET list
    r = await client.get("/api/scheduled-posts", headers=headers)
    assert r.status_code == 200

    # DELETE
    r = await client.delete(f"/api/scheduled-posts/{sp_id}", headers=headers)
    assert r.status_code == 204
```

- [ ] **Step 2: Run integration test**

```bash
cd backend && pytest tests/test_scheduled_post_integration.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_scheduled_post_integration.py
git commit -m "test: add scheduled-post integration contract tests"
```

---

### Task 6: Frontend — Add "Lịch đăng" to SideNav & Polish

**Files:**
- Modify: `frontend/src/components/layout/SideNav.tsx`
- Modify: `frontend/src/app/scheduled-posts/page.tsx` (add fire-now button to list)

- [ ] **Step 1: Update SideNav** — ensure link uses consistent styling with existing items

- [ ] **Step 2: Add fire-now button in `ScheduleList.tsx`** (for scheduled/paused items)

```tsx
<Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => fireNow(item.id)} title="Đăng ngay">
  <Send className="h-3 w-3" />
</Button>
```

Wire `fireNow` to `POST /api/scheduled-posts/{id}/fire-now` like the pause/resume handlers.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/layout/SideNav.tsx frontend/src/components/scheduled-posts/ScheduleList.tsx
git commit -m "feat: add fire-now button and polish scheduled-posts navigatoin"
```

---

### Execution Order Summary

| # | Task | Duration estimate |
|---|---|---|
| 1 | DB Model + Service (TDD) | 2–3 implementation iterations |
| 2 | Cron + Router (TDD) | 1–2 iterations |
| 3 | Frontend page + form + list | 1 iteration |
| 4 | Fire-now + validation | 1 iteration |
| 5 | Integration smoke test | 1 test run |
| 6 | Polish + nav link | 30 min |

### Open Questions / Future Work (out of scope for this plan)

1. **Target selector UI** — currently hardcodes `targets: []`. Phase 2 adds the multi-target picker from `auto-post/page.tsx` as a reusable component.
2. **Media upload** — same component reuse as auto-post's file picker.
3. **Spin content / variation** — apply P0 spin logic (slight word variation + random link insertion) before each fire.
4. **Cron via pg_cron or APScheduler** — currently uses a lightweight `asyncio.sleep` loop inside FastAPI lifespan. For production HA, replace with a dedicated `worker` container using APScheduler.
