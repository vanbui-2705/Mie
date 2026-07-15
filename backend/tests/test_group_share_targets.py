from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

import pytest

from app import browser_worker
from app.services import personal_browser
from app.models.sqlmodels import ExternalPage, FacebookGroup, ShareTarget, TaskItem, TaskItemStatus
from app.routers import page_tasks
from app.routers.page_tasks import (
    _is_invalid_graph_link_error,
    _facebook_url_label,
    _normalize_facebook_url,
    _parse_named_facebook_lines,
    _parse_post_targets,
    _parse_share_targets,
    _share_browser_target_available,
)


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


def test_imported_target_names_and_profile_ids_are_preserved() -> None:
    assert _parse_named_facebook_lines(
        "Page Demo|https://www.facebook.com/page.demo\nhttps://www.facebook.com/second.page|Page Hai"
    ) == [
        ("https://www.facebook.com/page.demo", "Page Demo"),
        ("https://www.facebook.com/second.page", "Page Hai"),
    ]
    normalized = _normalize_facebook_url("https://www.facebook.com/profile.php?id=12345&utm_source=test")
    assert normalized == "https://www.facebook.com/profile.php?id=12345"
    assert _facebook_url_label(normalized, "Page") == "Page 12345"
    assert _facebook_url_label("https://www.facebook.com/song-lanh-an-nhien", "Page") == "song lanh an nhien"


def test_share_browser_target_available_when_extension_online() -> None:
    assert _share_browser_target_available("not_checked", True) is True
    assert _share_browser_target_available("login_required", True) is True
    assert _share_browser_target_available("available", False) is True
    assert _share_browser_target_available("not_checked", False) is False
    assert _share_browser_target_available("not_found", True) is False
    assert _share_browser_target_available("no_permission", True) is False


def test_invalid_graph_link_error_is_detected() -> None:
    assert _is_invalid_graph_link_error(
        "Graph API 400: The url you supplied is invalid (code 1500, subcode 1611248). Không thể phân tích cú pháp URL"
    )
    assert not _is_invalid_graph_link_error("Graph API 400: Permission denied")


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


@pytest.mark.asyncio
async def test_browser_worker_routes_native_group_share_without_appending_source_link(monkeypatch) -> None:
    captured: dict = {}

    async def lock(account_id: str, owner: str) -> bool:
        return True

    async def release(account_id: str, owner: str) -> bool:
        return True

    async def mark_running(task_item_id):
        return None

    async def write_result(run_id, log_index, uid, result, account_id, task_item_id=None, action="post_personal", share_target_id=None):
        captured["action"] = action

    def fake_native_share(profile_dir, target_url, source_url, message, job_type, headless, target_name):
        captured.update({
            "target_url": target_url,
            "source_url": source_url,
            "message": message,
            "job_type": job_type,
            "target_name": target_name,
        })
        return {"success": True, "post_url": source_url}

    monkeypatch.setattr(browser_worker, "acquire_browser_account_lock", lock)
    monkeypatch.setattr(browser_worker, "release_browser_account_lock", release)
    monkeypatch.setattr(browser_worker, "_mark_item_running", mark_running)
    monkeypatch.setattr(browser_worker, "_write_result", write_result)
    monkeypatch.setattr(browser_worker, "share_to_target", fake_native_share)

    result = await browser_worker.process_browser_job({
        "type": "share_to_group",
        "run_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "account_id": str(uuid.uuid4()),
        "target_url": "https://www.facebook.com/groups/test-group",
        "target_name": "Test Group",
        "source_url": "https://www.facebook.com/test-user/posts/123",
        "message": "Caption only",
        "task_item_id": 13,
    })

    assert result is True
    assert captured == {
        "target_url": "https://www.facebook.com/groups/test-group",
        "source_url": "https://www.facebook.com/test-user/posts/123",
        "message": "Caption only",
        "job_type": "share_to_group",
        "target_name": "Test Group",
        "action": "share_group",
    }


def test_native_share_post_identity_tokens_cover_facebook_permalink_formats() -> None:
    assert personal_browser._facebook_post_identity_tokens(
        "https://www.facebook.com/test-user/posts/123456"
    ) == ["123456"]
    assert personal_browser._facebook_post_identity_tokens(
        "https://www.facebook.com/permalink.php?story_fbid=987&id=111"
    ) == ["987"]
    assert personal_browser._facebook_post_identity_tokens(
        "https://www.facebook.com/share/p/AbCdEf/"
    ) == ["abcdef"]


@pytest.mark.asyncio
async def test_share_task_falls_back_to_browser_when_extension_offline(monkeypatch, caplog) -> None:
    run_id = str(uuid.uuid4())
    target = ShareTarget(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        target_type="group",
        facebook_group_id=uuid.uuid4(),
        facebook_account_id=uuid.uuid4(),
    )
    queued_browser_jobs: list[dict] = []
    queued_extension_jobs: list[dict] = []

    class FakeSession:
        async def get(self, model, item_id):
            return target if model is ShareTarget and item_id == target.id else None

        def add(self, item) -> None:
            if isinstance(item, TaskItem) and item.id is None:
                item.id = 42

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

    @asynccontextmanager
    async def fake_session_context():
        yield FakeSession()

    async def fake_resolve(session, share_target):
        assert share_target is target
        return {
            "job_type": "share_to_group",
            "action": "share_group",
            "account_id": target.facebook_account_id,
            "target_url": "https://www.facebook.com/groups/test-group",
            "target_name": "Test Group",
            "target_kind": "group",
            "status": "available",
            "error": None,
        }

    async def extension_offline(account_id: str) -> bool:
        assert account_id == str(target.facebook_account_id)
        return False

    async def enqueue_browser(payload: dict) -> None:
        queued_browser_jobs.append(payload)

    async def enqueue_extension(account_id: str, payload: dict) -> None:
        queued_extension_jobs.append(payload)

    monkeypatch.setattr(page_tasks, "session_context", fake_session_context)
    monkeypatch.setattr(page_tasks, "_resolve_browser_share_target", fake_resolve)
    monkeypatch.setattr(page_tasks, "is_extension_online", extension_offline)
    monkeypatch.setattr(page_tasks, "enqueue_browser_job", enqueue_browser)
    monkeypatch.setattr(page_tasks, "enqueue_extension_job", enqueue_extension)

    with caplog.at_level(logging.INFO, logger="flowmeta.page_tasks"):
        await page_tasks._run_share_task(
            run_id,
            [str(target.id)],
            "Caption",
            "https://www.facebook.com/source/posts/123",
        )

    assert queued_extension_jobs == []
    assert len(queued_browser_jobs) == 1
    payload = queued_browser_jobs[0]
    assert payload["type"] == "share_to_group"
    assert payload["target_url"] == "https://www.facebook.com/groups/test-group"
    assert payload["source_url"] == "https://www.facebook.com/source/posts/123"
    assert payload["message"] == "Caption"
    assert payload["action"] == "share_group"
    assert payload["task_item_id"] == 42
    assert "Extension offline" in caplog.text
    assert "falling back to browser worker" in caplog.text


@pytest.mark.asyncio
async def test_unclaimed_extension_share_falls_back_to_browser(monkeypatch, caplog) -> None:
    queued: list[dict] = []

    async def remove_job(account_id: str, job_id: str) -> bool:
        assert account_id == "account-1"
        assert job_id == "job-1"
        return True

    async def enqueue_browser(payload: dict) -> None:
        queued.append(payload)

    monkeypatch.setattr(page_tasks, "remove_queued_extension_job", remove_job)
    monkeypatch.setattr(page_tasks, "enqueue_browser_job", enqueue_browser)

    payload = {"type": "share_to_group", "task_item_id": 99}
    with caplog.at_level(logging.WARNING, logger="flowmeta.page_tasks"):
        fell_back = await page_tasks._fallback_unclaimed_extension_share(
            "account-1", "job-1", payload, delay_seconds=0
        )

    assert fell_back is True
    assert queued == [payload]
    assert "did not claim share job" in caplog.text
    assert "falling back to browser worker" in caplog.text


@pytest.mark.asyncio
async def test_resolve_facebook_group_id_calls_graph_search_and_returns_id(monkeypatch) -> None:
    from app.services.facebook_graph import resolve_facebook_group_id

    captured_url = None

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "data": [
                    {"id": "1234567890", "name": "Test Group Name"},
                ]
            }

        @property
        def text(self):
            return "{}"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def get(self, url, **kwargs):
            nonlocal captured_url
            captured_url = url
            return FakeResp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.services.facebook_graph.httpx.AsyncClient", FakeClient)
    result = await resolve_facebook_group_id(
        token="test_token",
        group_url="https://www.facebook.com/groups/test-group-slug",
    )
    assert result["success"] is True
    assert result["group_id"] == "1234567890"
    assert result["group_name"] == "Test Group Name"
    assert captured_url is not None
    assert "search?q=test-group-slug" in captured_url
    assert "type=group" in captured_url
    assert "fields=id,name" in captured_url
    assert "access_token=test_token" in captured_url


@pytest.mark.asyncio
async def test_resolve_facebook_group_id_returns_failure_on_graph_error(monkeypatch) -> None:
    from app.services.facebook_graph import resolve_facebook_group_id

    class FakeResp:
        status_code = 400
        text = '{"error": {"message": "Invalid query", "code": 100}}'

        def json(self):
            return {"error": {"message": "Invalid query", "code": 100}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def get(self, url, **kwargs):
            return FakeResp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.services.facebook_graph.httpx.AsyncClient", FakeClient)
    result = await resolve_facebook_group_id(
        token="test_token",
        group_url="https://www.facebook.com/groups/bad-slug",
    )
    assert result["success"] is False
    assert "message" in result


@pytest.mark.asyncio
async def test_import_facebook_groups_calls_resolve_on_new_group(monkeypatch) -> None:
    """When a new group is imported, resolve_facebook_group_id is called and the result is used."""
    from app.models.sqlmodels import FacebookAccount, FacebookGroup
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    account = FacebookAccount(
        id=account_id,
        user_id=user_id,
        uid="12345",
        user_token_enc="encrypted-token",
        token_status="live",
        browser_status="logged_in",
    )
    added: list[FacebookGroup] = []

    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        async def get(self, model, pk):
            return account if model is FacebookAccount and pk == account_id else None

        async def execute(self, statement):
            return FakeResult()

        def add(self, item):
            added.append(item)

        async def commit(self):
            return None

    resolve_calls: list[tuple[str, str]] = []

    async def fake_resolve_facebook_group_id(token: str, group_url: str, proxy_url=None):
        resolve_calls.append((token, group_url))
        return {
            "success": True,
            "group_id": "9876543210",
            "group_name": "Resolved Group Name",
        }

    monkeypatch.setattr(page_tasks, "resolve_facebook_group_id", fake_resolve_facebook_group_id)
    monkeypatch.setattr(page_tasks, "decrypt", lambda value: "EAA_TEST_TOKEN")

    result = await page_tasks.import_facebook_groups(
        body={
            "facebook_account_id": str(account_id),
            "raw_text": "https://www.facebook.com/groups/my-test-group",
        },
        user=type("FakeUser", (), {"id": user_id})(),
        session=FakeSession(),
    )

    assert result["created"] == 1
    assert result["updated"] == 0

    # Verify resolve_facebook_group_id was called
    assert len(resolve_calls) == 1
    assert "my-test-group" in resolve_calls[0][1]

    # Verify group_id is stored
    assert len(added) == 1
    assert added[0].group_id == "9876543210"
    assert added[0].group_name == "Resolved Group Name"


@pytest.mark.asyncio
async def test_import_facebook_groups_resets_group_id_on_update(monkeypatch) -> None:
    """Re-import refreshes an existing group's numeric ID."""
    from app.models.sqlmodels import FacebookAccount, FacebookGroup
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    account = FacebookAccount(
        id=account_id,
        user_id=user_id,
        uid="12345",
        user_token_enc="encrypted-token",
        token_status="live",
        browser_status="logged_in",
    )
    existing_group = FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=account_id,
        group_url="https://www.facebook.com/groups/my-test-group",
        group_name="Old Name",
        group_id="1111111111",
        status="available",
    )
    class FakeResult:
        def scalar_one_or_none(self):
            return existing_group

    class FakeSession:
        async def get(self, model, pk):
            return account if model is FacebookAccount and pk == account_id else None

        async def execute(self, statement):
            return FakeResult()

        async def commit(self):
            return None

    async def fake_resolve_facebook_group_id(token: str, group_url: str, proxy_url=None):
        return {
            "success": True,
            "group_id": "9999999999",
            "group_name": None,  # resolved name is None; fallback to provided name
        }

    monkeypatch.setattr(page_tasks, "resolve_facebook_group_id", fake_resolve_facebook_group_id)

    result = await page_tasks.import_facebook_groups(
        body={
            "facebook_account_id": str(account_id),
            "raw_text": "https://www.facebook.com/groups/my-test-group|New Provided Name",
        },
        user=type("FakeUser", (), {"id": user_id})(),
        session=FakeSession(),
    )

    assert result["created"] == 0
    assert result["updated"] == 1

    # group_id should be overwritten with new resolution
    assert existing_group.group_id == "9999999999"
    # provided_name wins over resolved name when resolved name is None
    assert existing_group.group_name == "New Provided Name"


@pytest.mark.asyncio
async def test_check_group_preserves_existing_group_id_without_resolving(monkeypatch) -> None:
    from app.models.sqlmodels import FacebookAccount

    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    group = FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=account_id,
        group_url="https://www.facebook.com/groups/test-group",
        group_id="999888777",
        status="not_checked",
    )
    account = FacebookAccount(
        id=account_id,
        user_id=user_id,
        uid="12345",
        user_token_enc="encrypted-token",
    )

    class FakeSession:
        async def get(self, model, pk):
            if model is FacebookGroup and pk == group.id:
                return group
            if model is FacebookAccount and pk == account_id:
                return account
            return None

        async def commit(self):
            return None

    async def fake_check(*args):
        return {"success": True, "status": "available", "title": "Test Group"}

    async def unexpected_resolve(*args, **kwargs):
        raise AssertionError("existing group_id must not be re-resolved during Check")

    monkeypatch.setattr(page_tasks, "_check_browser_target", fake_check)
    monkeypatch.setattr(page_tasks, "resolve_facebook_group_id", unexpected_resolve)

    result = await page_tasks.check_facebook_group(
        str(group.id),
        user=type("User", (), {"id": user_id})(),
        session=FakeSession(),
    )

    assert result["group_id"] == "999888777"
    assert group.status == "available"


@pytest.mark.asyncio
async def test_check_group_resolves_missing_group_id(monkeypatch) -> None:
    from app.models.sqlmodels import FacebookAccount

    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    group = FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=account_id,
        group_url="https://www.facebook.com/groups/test-group",
        group_id=None,
        status="not_checked",
    )
    account = FacebookAccount(
        id=account_id,
        user_id=user_id,
        uid="12345",
        user_token_enc="encrypted-token",
    )

    class FakeSession:
        async def get(self, model, pk):
            if model is FacebookGroup and pk == group.id:
                return group
            if model is FacebookAccount and pk == account_id:
                return account
            return None

        async def commit(self):
            return None

    async def fake_check(*args):
        return {"success": True, "status": "available", "title": "Browser Group Name"}

    async def fake_resolve(token, group_url):
        assert token == "plain-token"
        assert group_url == group.group_url
        return {"success": True, "group_id": "123456789", "group_name": "Graph Group Name"}

    monkeypatch.setattr(page_tasks, "_check_browser_target", fake_check)
    monkeypatch.setattr(page_tasks, "decrypt", lambda value: "plain-token")
    monkeypatch.setattr(page_tasks, "resolve_facebook_group_id", fake_resolve)

    result = await page_tasks.check_facebook_group(
        str(group.id),
        user=type("User", (), {"id": user_id})(),
        session=FakeSession(),
    )

    assert result["group_id"] == "123456789"
    assert result["group_name"] == "Graph Group Name"


@pytest.mark.asyncio
async def test_resolve_group_id_endpoint_updates_group(monkeypatch) -> None:
    from app.models.sqlmodels import FacebookAccount

    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    group = FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=account_id,
        group_url="https://www.facebook.com/groups/test-group",
        group_id=None,
        status="not_checked",
    )
    account = FacebookAccount(
        id=account_id,
        user_id=user_id,
        uid="12345",
        user_token_enc="encrypted-token",
    )
    committed = False

    class FakeSession:
        async def get(self, model, pk):
            if model is FacebookGroup and pk == group.id:
                return group
            if model is FacebookAccount and pk == account_id:
                return account
            return None

        async def commit(self):
            nonlocal committed
            committed = True

    async def fake_resolve(token, group_url):
        return {"success": True, "group_id": "456789123", "group_name": "Resolved Name"}

    monkeypatch.setattr(page_tasks, "resolve_facebook_group_id", fake_resolve)

    result = await page_tasks.resolve_facebook_group_id_endpoint(
        str(group.id),
        user=type("User", (), {"id": user_id})(),
        session=FakeSession(),
    )

    assert committed is True
    assert result["group_id"] == "456789123"
    assert result["group_name"] == "Resolved Name"
    assert result["status"] == "available"
    assert group.status == "available"
