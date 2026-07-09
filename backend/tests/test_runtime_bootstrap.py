from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import postgres
from app.db.postgres import get_session
from app.event_bus import event_bus
from app.services.proxy_manager import ProxyManager
from app.services.task_runner import TaskRunner


def test_session_factory_creates_async_session() -> None:
    factory = postgres._get_session_factory()
    session = factory()
    try:
        assert isinstance(session, AsyncSession)
    finally:
        # No IO happens here; close sync-side object to avoid warnings.
        session.sync_session.close()


def test_task_runner_constructor_matches_app_bootstrap() -> None:
    runner = TaskRunner(
        get_session=get_session,
        proxy_manager=ProxyManager(),
        publish=event_bus.publish,
    )
    assert runner.active_run_id is None
