from __future__ import annotations
import json, uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import current_user
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import (
    FacebookGroup,
    GoogleSheetConnection,
    PublicationJob,
    RentalConfig,
    RentalRoom,
    User,
)


async def _client_for(session, user):
    async def override_get_session():
        yield session
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = override_get_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_create_and_list_config(session: AsyncSession, user_id: uuid.UUID):
    user = User(id=user_id, username=f"rental-{user_id.hex[:8]}", password_hash=None)
    session.add(user)
    await session.commit()
    body = {"name": "Trọ Gò Vấp", "credentials": {"username": "user", "password": "pass"},
            "province_code": "79", "province_name": "HCM", "district_code": "764",
            "district_name": "Gò Vấp", "caption_template": "{title}", "contact_phone": "0900",
            "post_spacing_seconds": 600, "poll_interval_seconds": 300}
    try:
        client = await _client_for(session, user)
        async with client:
            r = await client.post("/api/rental/configs", json=body)
            assert r.status_code == 201, r.text
            payload = r.json()
            cid = payload["id"]
            assert "source_credentials_enc" not in json.dumps(payload).lower()
            assert "password" not in json.dumps(payload).lower()
            r2 = await client.get("/api/rental/configs")
            assert r2.status_code == 200
            assert any(c["id"] == cid for c in r2.json())
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_assign_groups_sets_new(session: AsyncSession, user_id: uuid.UUID):
    from app.crypto import encrypt
    user = User(id=user_id, username=f"rental-{user_id.hex[:8]}", password_hash=None)
    session.add(user)
    cfg = RentalConfig(user_id=user_id, name="c", source_type="nhatrovn",
        source_credentials_enc=encrypt(json.dumps({"username": "x", "password": "y"})),
        province_code="79", province_name="HCM", district_code="764", district_name="Gò Vấp",
        caption_template="{title}", contact_phone="0900", poll_interval_seconds=300, post_spacing_seconds=1)
    session.add(cfg)
    await session.flush()
    room = RentalRoom(config_id=cfg.id, user_id=user_id, external_room_id="R1",
        title="R1", district="Gò Vấp", address="Gò Vấp", status="waiting_groups")
    session.add(room)
    session.add(FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=uuid.uuid4(),
        group_id="10",
        group_name="Thuê trọ Gò Vấp",
        group_url="https://facebook.example/groups/10",
        status="available",
    ))
    await session.commit()
    try:
        client = await _client_for(session, user)
        async with client:
            r = await client.post(f"/api/rental/rooms/{room.id}/assign-groups",
                                  json={"group_ids": ["10"]})
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "new"
        await session.refresh(room)
        assert room.status == "new"
        assert json.loads(room.matched_group_ids_json) == ["10"]
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_create_rejects_cross_user_sheet_and_invalid_values(
    session: AsyncSession, user_id: uuid.UUID,
):
    owner = User(id=user_id, username=f"owner-{user_id.hex[:8]}", password_hash=None)
    other_id = uuid.uuid4()
    other = User(id=other_id, username=f"other-{other_id.hex[:8]}", password_hash=None)
    session.add_all([owner, other])
    sheet = GoogleSheetConnection(
        user_id=other_id,
        name="other sheet",
        spreadsheet_id="abcdefghijk",
        sheet_name="RentalRooms",
        credentials_enc="encrypted",
        service_account_email="service@example.iam.gserviceaccount.com",
        status="connected",
    )
    session.add(sheet)
    await session.commit()

    body = {
        "name": "Trọ Gò Vấp",
        "credentials": {"username": "user", "password": "pass"},
        "province_code": "79",
        "province_name": "HCM",
        "district_code": "764",
        "district_name": "Gò Vấp",
        "google_sheet_connection_id": str(sheet.id),
    }
    try:
        client = await _client_for(session, owner)
        async with client:
            cross_user = await client.post("/api/rental/configs", json=body)
            assert cross_user.status_code == 400

            invalid = await client.post(
                "/api/rental/configs",
                json={
                    **body,
                    "google_sheet_connection_id": None,
                    "post_spacing_seconds": -1,
                    "auto_post": "false",
                    "timezone": "Not/A_Zone",
                },
            )
            assert invalid.status_code == 422
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_room_jobs_are_visible_and_retry_resets_failed_job(
    session: AsyncSession, user_id: uuid.UUID,
):
    from app.crypto import encrypt

    user = User(id=user_id, username=f"jobs-{user_id.hex[:8]}", password_hash=None)
    config = RentalConfig(
        user_id=user_id,
        name="job config",
        source_type="nhatrovn",
        source_credentials_enc=encrypt(json.dumps({"username": "x", "password": "y"})),
        province_code="79",
        province_name="HCM",
        district_code="764",
        district_name="Gò Vấp",
        caption_template="{title}",
        contact_phone="0900",
        poll_interval_seconds=300,
        post_spacing_seconds=60,
    )
    session.add_all([user, config])
    await session.flush()
    room = RentalRoom(
        config_id=config.id,
        user_id=user_id,
        external_room_id="R-JOBS",
        title="Room jobs",
        status="error",
    )
    session.add(room)
    await session.flush()
    job = PublicationJob(
        user_id=user_id,
        rental_room_id=room.id,
        target_type="group",
        target_id=uuid.uuid4(),
        target_external_id="123",
        status="failed",
        attempt_count=3,
        max_attempts=3,
        error="boom",
    )
    session.add(job)
    await session.commit()

    try:
        client = await _client_for(session, user)
        async with client:
            listed = await client.get(f"/api/rental/rooms/{room.id}/jobs")
            assert listed.status_code == 200, listed.text
            assert listed.json()[0]["status"] == "failed"
            assert listed.json()[0]["target_external_id"] == "123"

            retried = await client.post(f"/api/rental/rooms/{room.id}/retry")
            assert retried.status_code == 200, retried.text
            assert retried.json()["status"] == "new"

        await session.refresh(job)
        assert job.status == "pending"
        assert job.attempt_count == 0
        assert job.error is None
        assert job.task_item_id is None
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)
