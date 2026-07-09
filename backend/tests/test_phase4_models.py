from __future__ import annotations

import uuid

from datetime import datetime, timedelta, timezone

from app.models.sqlmodels import BrowserSession, BrowserSessionStatus, TaskItem, TaskItemStatus, TaskRun, TaskRunStatus


def test_task_run_and_items_use_phase4_statuses() -> None:
    run_id = uuid.uuid4()
    user_id = uuid.uuid4()
    run = TaskRun(
        id=run_id,
        user_id=user_id,
        status=TaskRunStatus.PENDING,
        action="edit",
        max_threads=3,
    )
    item = TaskItem(
        run_id=run_id,
        user_id=user_id,
        item_index=1,
        uid="10001",
        target_link="https://facebook.com/comment/1",
        action="edit",
        status=TaskItemStatus.PENDING,
    )

    assert run.status == TaskRunStatus.PENDING
    assert item.status == TaskItemStatus.PENDING
    assert item.user_id == user_id


def test_browser_session_model_tracks_provider_and_status() -> None:
    session = BrowserSession(
        user_id=uuid.uuid4(),
        facebook_account_id=uuid.uuid4(),
        status=BrowserSessionStatus.READY,
        provider="kasm",
        remote_url="http://localhost:8000/remote/session-id",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )

    assert session.status == BrowserSessionStatus.READY
    assert session.provider == "kasm"
    assert "/remote/" in session.remote_url
