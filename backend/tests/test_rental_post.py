import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.sqlmodels import (
    FacebookGroup,
    PublicationJob,
    RentalConfig,
    RentalRoom,
    TaskItem,
    TaskItemStatus,
)
from app.services.publication_jobs import (
    reconcile_publication_jobs,
    recover_stale_publication_jobs,
)
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


async def _queued_fake_runner(session, user_id, calls, **kw):
    item = TaskItem(
        run_id=uuid.UUID(kw["run_id"]),
        user_id=user_id,
        item_index=1,
        uid="account",
        target_link="group",
        action="post_group",
        status=TaskItemStatus.PENDING,
    )
    session.add(item)
    await session.flush()
    calls.append(kw)
    return {
        "accepted": True,
        "task_run_id": kw["run_id"],
        "task_item_ids": [item.id],
        "status": "queued",
    }


@pytest.mark.asyncio
async def test_enqueue_is_not_posted_and_final_result_is_reconciled(
    session, session_factory, user_id, _ensure_user,
):
    cfg = _make_config(user_id, last_post_at=None)
    session.add(cfg)
    await session.flush()
    group = FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=uuid.uuid4(),
        group_url="u1",
        group_id="10",
        group_name="Thuê trọ Gò Vấp",
        status="available",
    )
    session.add(group)
    room = RentalRoom(
        config_id=cfg.id,
        user_id=user_id,
        external_room_id="P1",
        title="P1",
        caption="cap",
        status="new",
        matched_group_ids_json=json.dumps(["10"]),
    )
    session.add(room)
    await session.commit()

    calls = []

    async def fake_run(**kw):
        return await _queued_fake_runner(session, user_id, calls, **kw)

    fired = await RentalPostService(session_factory, run_post=fake_run).post_due()
    assert len(fired) == 1
    assert fired[0]["status"] == "queued"
    assert fired[0]["accepted"] is True

    await session.refresh(room)
    assert room.status == "posting"
    assert room.posted_at is None
    assert room.post_urls_json is None

    job = (await session.execute(
        select(PublicationJob).where(PublicationJob.rental_room_id == room.id)
    )).scalar_one()
    assert job.status == "queued"
    item = await session.get(TaskItem, job.task_item_id)
    item.status = TaskItemStatus.SUCCESS
    item.output_link = "https://facebook.example/posts/123"
    await session.commit()

    result = await reconcile_publication_jobs(session_factory)
    assert result["succeeded"] == 1
    await session.refresh(room)
    assert room.status == "posted"
    assert room.posted_at is not None
    assert json.loads(room.post_urls_json) == {
        "10": "https://facebook.example/posts/123"
    }


@pytest.mark.asyncio
async def test_post_due_respects_spacing(
    session, session_factory, user_id, _ensure_user,
):
    cfg = _make_config(user_id)
    session.add(cfg)
    await session.flush()
    session.add(FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=uuid.uuid4(),
        group_url="u1",
        group_id="10",
        group_name="Thuê trọ Gò Vấp",
        status="available",
    ))
    session.add(RentalRoom(
        config_id=cfg.id,
        user_id=user_id,
        external_room_id="P1",
        title="P1",
        caption="cap",
        status="new",
        matched_group_ids_json=json.dumps(["10"]),
    ))
    await session.commit()

    calls = []

    async def fake_run(**kw):
        return await _queued_fake_runner(session, user_id, calls, **kw)

    svc = RentalPostService(session_factory, run_post=fake_run)
    assert await svc.post_due(now=datetime.now(timezone.utc)) == []
    assert calls == []

    later = datetime.now(timezone.utc) + timedelta(seconds=601)
    fired = await svc.post_due(now=later)
    assert len(fired) == 1 and len(calls) == 1
    uuid.UUID(calls[0]["group_ids"][0])


@pytest.mark.asyncio
async def test_dispatch_error_schedules_job_retry(
    session, session_factory, user_id, _ensure_user,
):
    cfg = _make_config(user_id, last_post_at=None)
    session.add(cfg)
    await session.flush()
    session.add(FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=uuid.uuid4(),
        group_url="u3",
        group_id="20",
        group_name="Thuê trọ Q1",
        status="available",
    ))
    room = RentalRoom(
        config_id=cfg.id,
        user_id=user_id,
        external_room_id="P2",
        title="P2",
        caption="cap",
        status="new",
        matched_group_ids_json=json.dumps(["20"]),
    )
    session.add(room)
    await session.commit()

    async def fake_run_fail(**kw):
        raise RuntimeError("boom")

    fired = await RentalPostService(
        session_factory, run_post=fake_run_fail,
    ).post_due(now=datetime.now(timezone.utc))
    assert len(fired) == 1
    assert fired[0]["accepted"] is False

    job = (await session.execute(
        select(PublicationJob).where(PublicationJob.rental_room_id == room.id)
    )).scalar_one()
    assert job.attempt_count == 1
    assert job.status == "pending"
    assert job.next_retry_at is not None
    assert "boom" in (job.error or "")
    await session.refresh(room)
    assert room.status != "posted"
    assert room.retry_count == 1


@pytest.mark.asyncio
async def test_no_owned_group_resolves_to_waiting_groups(
    session, session_factory, user_id, _ensure_user,
):
    cfg = _make_config(user_id, last_post_at=None)
    session.add(cfg)
    await session.flush()
    room = RentalRoom(
        config_id=cfg.id,
        user_id=user_id,
        external_room_id="P3",
        title="P3",
        caption="cap",
        status="new",
        matched_group_ids_json=json.dumps(["999"]),
    )
    session.add(room)
    await session.commit()

    calls = []

    async def fake_run(**kw):
        calls.append(kw)

    fired = await RentalPostService(
        session_factory, run_post=fake_run,
    ).post_due(now=datetime.now(timezone.utc))
    assert len(fired) == 1
    assert calls == []

    await session.refresh(room)
    assert room.status == "waiting_groups"
    assert room.posted_at is None
    assert room.error is not None and "999" in room.error


@pytest.mark.asyncio
async def test_stale_ambiguous_dispatch_requires_review_instead_of_retry(
    session, session_factory, user_id, _ensure_user,
):
    now = datetime.now(timezone.utc)
    cfg = _make_config(user_id, last_post_at=None)
    session.add(cfg)
    await session.flush()
    room = RentalRoom(
        config_id=cfg.id,
        user_id=user_id,
        external_room_id="STALE",
        title="STALE",
        caption="cap",
        status="posting",
        matched_group_ids_json=json.dumps(["10"]),
    )
    session.add(room)
    await session.flush()
    from app.models.sqlmodels import TaskRun, TaskRunStatus, CommentAction
    run = TaskRun(
        user_id=user_id,
        status=TaskRunStatus.RUNNING,
        action=CommentAction.POST_PAGE,
        max_threads=1,
    )
    session.add(run)
    await session.flush()
    item = TaskItem(
        run_id=run.id,
        user_id=user_id,
        item_index=1,
        target_link="group",
        action="post_group",
        status=TaskItemStatus.PENDING,
    )
    session.add(item)
    await session.flush()
    job = PublicationJob(
        user_id=user_id,
        rental_room_id=room.id,
        target_type="group",
        target_id=uuid.uuid4(),
        target_external_id="10",
        status="queued",
        attempt_count=1,
        task_run_id=run.id,
        task_item_id=item.id,
        scheduled_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=2),
    )
    session.add(job)
    await session.commit()

    assert await recover_stale_publication_jobs(
        session_factory, now=now, stale_after_seconds=1800,
    ) == 1
    await session.refresh(job)
    await session.refresh(room)
    assert job.status == "pending_review"
    assert room.status == "pending_review"
    assert job.next_retry_at is None
