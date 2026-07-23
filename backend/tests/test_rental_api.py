from __future__ import annotations
import json, uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import current_user
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import RentalConfig, RentalRoom, User


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
