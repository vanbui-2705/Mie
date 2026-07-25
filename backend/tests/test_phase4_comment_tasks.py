from __future__ import annotations

import uuid
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.config import settings
from app.routers.comment_tasks import _build_task_items, upload_comment_image
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


def _upload(filename: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_upload_comment_image_saves_valid_image(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    user = SimpleNamespace(id=uuid.uuid4())

    result = await upload_comment_image(
        image=_upload("../../ảnh phòng.png", "image/png", b"\x89PNG\r\n\x1a\npayload"),
        user=user,
    )

    saved_path = tmp_path / "comment-tasks" / str(user.id) / result["filename"]
    assert saved_path.is_file()
    assert saved_path.read_bytes() == b"\x89PNG\r\n\x1a\npayload"
    assert result["path"] == str(saved_path)
    assert result["content_type"] == "image/png"
    assert ".." not in result["filename"]


@pytest.mark.asyncio
async def test_upload_comment_image_rejects_spoofed_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    user = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await upload_comment_image(
            image=_upload("not-really-an-image.png", "image/png", b"<script>alert(1)</script>"),
            user=user,
        )

    assert exc_info.value.status_code == 400
    assert not list(tmp_path.rglob("*"))


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
