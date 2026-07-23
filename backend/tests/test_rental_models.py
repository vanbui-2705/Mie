"""Tests for RentalConfig and RentalRoom models."""
from __future__ import annotations

import pytest

from app.models.sqlmodels import RentalConfig, RentalRoom


@pytest.mark.asyncio
async def test_create_rental_config_and_room(session, user_id, _ensure_user):
    cfg = RentalConfig(
        user_id=user_id,
        name="Trọ Gò Vấp", source_type="nhatrovn",
        source_credentials_enc="enc", province_code="79", province_name="TP HCM",
        district_code="764", district_name="Gò Vấp",
        caption_template="{title}", contact_phone="0900",
        poll_interval_seconds=300, post_spacing_seconds=480,
    )
    session.add(cfg)
    await session.flush()

    room = RentalRoom(
        config_id=cfg.id, user_id=user_id,
        external_room_id="P.004", title="P.004", price="3,000,000",
        area_text="30m2", address="496 Đào Sư Tích", district="Gò Vấp",
        description="mô tả", images_json="[]", caption="cap", status="new",
    )
    session.add(room)
    await session.flush()

    assert room.id is not None
    assert room.status == "new"
    assert cfg.status == "active"
    assert cfg.auto_post is True


@pytest.mark.asyncio
async def test_rental_room_unique_constraint_on_config_and_external_id(session, user_id, _ensure_user):
    cfg = RentalConfig(
        user_id=user_id,
        name="Trọ Gò Vấp 2", source_type="nhatrovn",
        source_credentials_enc="enc", province_code="79", province_name="TP HCM",
        district_code="764", district_name="Gò Vấp",
        caption_template="{title}", contact_phone="0900",
        poll_interval_seconds=300, post_spacing_seconds=480,
    )
    session.add(cfg)
    await session.flush()

    room1 = RentalRoom(
        config_id=cfg.id, user_id=user_id,
        external_room_id="P.005", title="P.005",
    )
    session.add(room1)
    await session.flush()

    room2 = RentalRoom(
        config_id=cfg.id, user_id=user_id,
        external_room_id="P.005", title="P.005 dup",
    )
    session.add(room2)

    with pytest.raises(Exception):
        await session.flush()
    await session.rollback()
