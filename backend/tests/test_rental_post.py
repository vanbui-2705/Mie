import json
import uuid

import pytest
from datetime import datetime, timezone, timedelta

from app.models.sqlmodels import RentalConfig, RentalRoom, FacebookGroup
from app.services.rental_post import RentalPostService


def _make_config(user_id, **overrides):
    defaults = dict(
        user_id=user_id,
        name="c",
        source_type="nhatrovn",
        source_credentials_enc="e",
        province_code="79",
        province_name="HCM",
        district_code="764",
        district_name="Gò Vấp",
        caption_template="{title}",
        contact_phone="0",
        poll_interval_seconds=300,
        post_spacing_seconds=600,
        auto_post=True,
        status="active",
        last_post_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return RentalConfig(**defaults)


@pytest.mark.asyncio
async def test_post_due_respects_spacing(session, session_factory, user_id, _ensure_user):
    cfg = _make_config(user_id)
    session.add(cfg)
    await session.flush()
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
        group_url="u1", group_id="10", group_name="Thuê trọ Gò Vấp"))
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
        group_url="u2", group_id="11", group_name="Trọ Gò Vấp 2"))
    session.add(RentalRoom(config_id=cfg.id, user_id=user_id, external_room_id="P1", title="P1",
        caption="cap", status="new", matched_group_ids_json=json.dumps(["10", "11"])))
    await session.commit()

    calls = []

    async def fake_run(**kw):
        calls.append(kw)

    svc = RentalPostService(session_factory, run_post=fake_run)

    # chưa đủ spacing -> không đăng
    assert await svc.post_due(now=datetime.now(timezone.utc)) == []
    assert calls == []

    # đủ spacing -> đăng đúng 1 lượt (1 nhóm)
    later = datetime.now(timezone.utc) + timedelta(seconds=601)
    fired = await svc.post_due(now=later)
    assert len(fired) == 1 and len(calls) == 1

    # runner được gọi với FacebookGroup PK (uuid), không phải fbid "10"/"11"
    called_group_id = calls[0]["group_ids"][0]
    assert called_group_id not in ("10", "11")
    uuid.UUID(called_group_id)  # không raise -> là uuid hợp lệ

    # room vẫn "new" vì còn 1 group chưa đăng
    await session.refresh(cfg)
    from sqlalchemy import select
    room = (await session.execute(select(RentalRoom).where(RentalRoom.config_id == cfg.id))).scalar_one()
    assert room.status == "new"
    posted = json.loads(room.post_urls_json)
    assert set(posted.keys()) == {"10"} or set(posted.keys()) == {"11"}


@pytest.mark.asyncio
async def test_post_due_retries_on_runner_error(session, session_factory, user_id, _ensure_user):
    cfg = _make_config(user_id, last_post_at=None)
    session.add(cfg)
    await session.flush()
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
        group_url="u3", group_id="20", group_name="Thuê trọ Q1"))
    room = RentalRoom(config_id=cfg.id, user_id=user_id, external_room_id="P2", title="P2",
        caption="cap", status="new", matched_group_ids_json=json.dumps(["20"]))
    session.add(room)
    await session.commit()

    async def fake_run_fail(**kw):
        raise RuntimeError("boom")

    svc = RentalPostService(session_factory, run_post=fake_run_fail)
    fired = await svc.post_due(now=datetime.now(timezone.utc))
    assert len(fired) == 1

    from sqlalchemy import select
    await session.refresh(room)
    assert room.retry_count == 1
    assert room.status == "new"  # retry_count(1) < MAX_RETRIES(3)
    assert room.error is not None and "boom" in room.error
