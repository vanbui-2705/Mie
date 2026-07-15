from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.sqlmodels import FacebookAccount
from app.routers.facebook_accounts import _expires_at_from_exchange, _token_refresh_due
from app.services.facebook_graph import detect_token_issue, extract_comment_id, extract_post_id


def test_extract_comment_id_from_url_and_raw_id() -> None:
    assert extract_comment_id("123456") == "123456"
    assert extract_comment_id("https://www.facebook.com/story.php?comment_id=987654") == "987654"


def test_extract_post_id_from_common_facebook_urls() -> None:
    assert extract_post_id("pfbid02abc") == "pfbid02abc"
    assert extract_post_id("https://www.facebook.com/some.page/posts/pfbid02abc") == "pfbid02abc"
    assert extract_post_id("https://www.facebook.com/permalink.php?story_fbid=111&id=222") == "111"


def test_detect_token_issue_classifies_checkpoint_and_expired_token() -> None:
    checkpoint = detect_token_issue("Checkpoint required", "", 0, 0)
    expired = detect_token_issue("The access token expired", "", 190, 463)

    assert checkpoint is not None
    assert checkpoint["kind"] == "Checkpoint"
    assert expired is not None
    assert expired["kind"] == "Token out"


def test_exchange_expiry_and_refresh_due_helpers() -> None:
    expires_at = _expires_at_from_exchange({"expires_in": 3600})
    assert expires_at is not None
    assert expires_at > datetime.now(timezone.utc)

    soon = FacebookAccount(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        uid="123",
        user_token_enc="encrypted",
        token_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    later = FacebookAccount(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        uid="456",
        user_token_enc="encrypted",
        token_expires_at=datetime.now(timezone.utc) + timedelta(days=45),
    )
    assert _token_refresh_due(soon) is True
    assert _token_refresh_due(later) is False
