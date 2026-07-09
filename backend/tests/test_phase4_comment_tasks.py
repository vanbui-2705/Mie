from __future__ import annotations

import pytest

from app.routers.comment_tasks import _build_task_items
from app.schemas import TaskStartRequest
from app.worker import process_job


def test_build_task_items_pairs_uid_and_links_for_edit_delete() -> None:
    body = TaskStartRequest(
        action="edit",
        raw_uid_text="10001\n10002\n10003",
        raw_link_text="link-1\nlink-2",
    )

    assert _build_task_items(body) == [
        {"uid": "10001", "link": "link-1"},
        {"uid": "10002", "link": "link-2"},
    ]


def test_build_task_items_uses_posts_for_new_comment() -> None:
    body = TaskStartRequest(
        action="new_comment",
        raw_post_text="post-1\n\npost-2",
    )

    assert _build_task_items(body) == [
        {"uid": "", "link": "post-1"},
        {"uid": "", "link": "post-2"},
    ]


class FakeRunner:
    def __init__(self) -> None:
        self.calls = []

    async def run_existing(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_process_job_runs_comment_task(monkeypatch) -> None:
    async def not_canceled(run_id: str) -> bool:
        return False

    monkeypatch.setattr("app.worker._is_canceled", not_canceled)
    runner = FakeRunner()

    result = await process_job(
        {
            "type": "comment_task",
            "run_id": "00000000-0000-0000-0000-000000000001",
            "payload": {
                "action": "edit",
                "raw_uid_text": "10001",
                "raw_link_text": "link-1",
                "raw_post_text": "",
                "max_threads": 4,
                "new_text_input": "updated",
                "image_input": "",
                "delay": {"min_seconds": 1, "max_seconds": 2, "every_rounds": 3},
            },
        },
        runner,
    )

    assert result is True
    assert runner.calls[0]["run_id"] == "00000000-0000-0000-0000-000000000001"
    assert runner.calls[0]["max_threads"] == 4
    assert runner.calls[0]["delay"].every_rounds == 3


@pytest.mark.asyncio
async def test_process_job_skips_canceled_task(monkeypatch) -> None:
    async def canceled(run_id: str) -> bool:
        return True

    monkeypatch.setattr("app.worker._is_canceled", canceled)
    runner = FakeRunner()

    result = await process_job(
        {
            "type": "comment_task",
            "run_id": "00000000-0000-0000-0000-000000000001",
            "payload": {"action": "edit"},
        },
        runner,
    )

    assert result is False
    assert runner.calls == []
