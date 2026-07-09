from __future__ import annotations

import uuid

import pytest

from app import browser_worker
from app.models.sqlmodels import ExternalPage, FacebookGroup, ShareTarget, TaskItemStatus
from app.routers.page_tasks import _parse_post_targets, _parse_share_targets


def test_group_and_external_models_are_available() -> None:
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    group = FacebookGroup(
        user_id=user_id,
        facebook_account_id=account_id,
        group_url="https://www.facebook.com/groups/test",
        status="available",
    )
    page = ExternalPage(
        user_id=user_id,
        facebook_account_id=account_id,
        page_url="https://www.facebook.com/public.page",
        status="not_checked",
    )
    target = ShareTarget(
        campaign_id=uuid.uuid4(),
        user_id=user_id,
        target_type="group",
        facebook_group_id=uuid.uuid4(),
        facebook_account_id=account_id,
    )

    assert group.status == "available"
    assert page.status == "not_checked"
    assert target.target_type == "group"
    assert TaskItemStatus.PENDING_REVIEW.value == "pending_review"


def test_post_and_share_target_parsers_accept_group_and_external_page() -> None:
    post_targets = _parse_post_targets({
        "targets": ["page:11111111-1111-1111-1111-111111111111", "group:22222222-2222-2222-2222-222222222222"],
    })
    share_targets = _parse_share_targets({
        "targets": [
            "page:11111111-1111-1111-1111-111111111111",
            "group:22222222-2222-2222-2222-222222222222",
            "external_page:33333333-3333-3333-3333-333333333333",
        ],
    })

    assert post_targets["group_ids"] == ["22222222-2222-2222-2222-222222222222"]
    assert share_targets == {
        "page_ids": ["11111111-1111-1111-1111-111111111111"],
        "group_ids": ["22222222-2222-2222-2222-222222222222"],
        "external_page_ids": ["33333333-3333-3333-3333-333333333333"],
    }


@pytest.mark.asyncio
async def test_browser_worker_routes_group_post_job(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def lock(account_id: str, owner: str) -> bool:
        return True

    async def release(account_id: str, owner: str) -> bool:
        return True

    async def mark_running(task_item_id):
        calls.append(("mark", str(task_item_id)))

    async def write_result(run_id, log_index, uid, result, account_id, task_item_id=None, action="post_personal", share_target_id=None):
        calls.append((action, str(result["success"])))

    def fake_post_to_group(profile_dir: str, target_url: str, message: str, media_paths: list[str]):
        assert target_url == "https://www.facebook.com/groups/test"
        assert message == "hello"
        return {"success": True, "post_url": target_url}

    monkeypatch.setattr(browser_worker, "acquire_browser_account_lock", lock)
    monkeypatch.setattr(browser_worker, "release_browser_account_lock", release)
    monkeypatch.setattr(browser_worker, "_mark_item_running", mark_running)
    monkeypatch.setattr(browser_worker, "_write_result", write_result)
    monkeypatch.setattr(browser_worker, "post_to_group", fake_post_to_group)

    result = await browser_worker.process_browser_job({
        "type": "group_post",
        "run_id": "00000000-0000-0000-0000-000000000001",
        "user_id": "00000000-0000-0000-0000-000000000002",
        "account_id": "00000000-0000-0000-0000-000000000003",
        "target_url": "https://www.facebook.com/groups/test",
        "message": "hello",
        "task_item_id": 12,
    })

    assert result is True
    assert ("mark", "12") in calls
    assert ("post_group", "True") in calls
