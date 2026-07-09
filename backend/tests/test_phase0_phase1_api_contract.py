from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.main import app
from app.routers import tasks
from app.routers.page_tasks import _parse_post_targets


def test_canonical_routes_are_registered() -> None:
    routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes}
    expected = {
        ("/api/profiles/import", "POST"),
        ("/api/tasks/start", "POST"),
        ("/api/proxy/monitor/start", "POST"),
        ("/api/proxy/monitor/stop", "POST"),
        ("/api/proxy/status", "GET"),
        ("/api/facebook-accounts/import", "POST"),
        ("/api/facebook-accounts", "GET"),
        ("/api/facebook-accounts/{account_id}/browser-login/start", "POST"),
        ("/api/facebook-accounts/{account_id}/browser-login/status", "GET"),
        ("/api/facebook-accounts/{account_id}/browser-login/stop", "POST"),
        ("/api/facebook-accounts/{account_id}/connect-browser/start", "POST"),
        ("/api/facebook-accounts/{account_id}/connect-browser/status", "GET"),
        ("/api/facebook-accounts/{account_id}/connect-browser/stop", "POST"),
        ("/api/facebook-pages", "GET"),
        ("/api/post-targets", "GET"),
        ("/api/share-targets", "GET"),
        ("/api/facebook-groups/import", "POST"),
        ("/api/facebook-groups", "GET"),
        ("/api/facebook-groups/{group_id}/check", "POST"),
        ("/api/facebook-groups/{group_id}", "DELETE"),
        ("/api/external-pages/import", "POST"),
        ("/api/external-pages", "GET"),
        ("/api/external-pages/{page_id}/check", "POST"),
        ("/api/external-pages/{page_id}", "DELETE"),
        ("/api/comment-tasks", "POST"),
        ("/api/page-post-tasks", "POST"),
        ("/api/page-post-tasks/{task_id}", "GET"),
        ("/api/share-campaigns", "POST"),
        ("/api/share-campaigns/{campaign_id}/start", "POST"),
        ("/api/share-campaigns/{campaign_id}", "GET"),
        ("/api/extension/connect", "POST"),
        ("/api/extension/heartbeat", "POST"),
        ("/api/extension/jobs", "GET"),
        ("/api/extension/jobs/{job_id}/complete", "POST"),
        ("/api/extension/status", "GET"),
    }
    missing = expected - routes
    assert not missing


class FakeRunner:
    active_run_id = None

    async def start(self, **kwargs):
        assert kwargs["action"] == "edit"
        assert kwargs["uid_text"] == "10001"
        assert kwargs["link_text"] == "https://facebook.com/comment/1"
        assert kwargs["max_threads"] == 2
        assert kwargs["delay"].min_seconds == 1
        return "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_tasks_start_accepts_json_body_contract() -> None:
    original_runner = tasks._task_runner
    tasks._task_runner = FakeRunner()
    try:
        async with AsyncClient(app=app, base_url="http://testserver") as client:
            response = await client.post(
                "/api/tasks/start",
                json={
                    "action": "edit",
                    "raw_uid_text": "10001",
                    "raw_link_text": "https://facebook.com/comment/1",
                    "raw_post_text": "",
                    "max_threads": 2,
                    "new_text_input": "updated",
                    "image_input": "",
                    "delay": {"min_seconds": 1, "max_seconds": 3, "every_rounds": 1},
                },
            )
        assert response.status_code == 200
        assert response.json() == {
            "run_id": "00000000-0000-0000-0000-000000000001",
            "status": "started",
        }
    finally:
        tasks._task_runner = original_runner


def test_page_post_task_accepts_mixed_targets_contract() -> None:
    parsed = _parse_post_targets({
        "targets": [
            "page:11111111-1111-1111-1111-111111111111",
            "group:44444444-4444-4444-4444-444444444444",
            "personal:22222222-2222-2222-2222-222222222222",
        ],
        "page_ids": ["33333333-3333-3333-3333-333333333333"],
    })
    assert parsed == {
        "page_ids": [
            "33333333-3333-3333-3333-333333333333",
            "11111111-1111-1111-1111-111111111111",
        ],
        "group_ids": ["44444444-4444-4444-4444-444444444444"],
        "personal_account_ids": ["22222222-2222-2222-2222-222222222222"],
    }
