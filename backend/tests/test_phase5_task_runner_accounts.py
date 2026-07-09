from __future__ import annotations

import uuid

from app.models.sqlmodels import FacebookAccount, Profile, TaskItemStatus, TokenStatus
from app.services.task_runner import _account_uid, _task_item_status_from_log, _token_enc


def test_task_runner_supports_legacy_profile_and_facebook_account_tokens() -> None:
    profile = Profile(
        uid="10001",
        token_enc="legacy-token-enc",
        token_status=TokenStatus.DA_NAP,
    )
    account = FacebookAccount(
        user_id=uuid.uuid4(),
        uid="10002",
        user_token_enc="account-token-enc",
        token_status=TokenStatus.DA_NAP,
    )

    assert _account_uid(profile) == "10001"
    assert _token_enc(profile) == "legacy-token-enc"
    assert _account_uid(account) == "10002"
    assert _token_enc(account) == "account-token-enc"


def test_task_runner_maps_logs_to_task_item_statuses() -> None:
    assert _task_item_status_from_log("Cho chay") == TaskItemStatus.RUNNING
    assert _task_item_status_from_log("Dang chay") == TaskItemStatus.RUNNING
    assert _task_item_status_from_log("Thanh cong") == TaskItemStatus.SUCCESS
    assert _task_item_status_from_log("That bai") == TaskItemStatus.FAILED
    assert _task_item_status_from_log("Dung profile") == TaskItemStatus.FAILED
    assert _task_item_status_from_log("Dung") == TaskItemStatus.CANCELED
    assert _task_item_status_from_log("ignored") is None
