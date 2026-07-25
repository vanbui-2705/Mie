import json
import uuid

import pytest
from sqlalchemy import select

from app.crypto import encrypt
from app.models.sqlmodels import (
    FacebookGroup,
    GoogleSheetConnection,
    PublicationJob,
    RentalConfig,
    RentalRoom,
    RentalSheetMirrorJob,
)
from app.services.nhatrovn_adapter import Room
from app.services.rental_sync import RentalSyncService, render_caption
from app.services.rental_sheet_mirror import (
    RENTAL_HEADERS,
    run_rental_sheet_mirror,
)


class FakeAdapter:
    def __init__(self, rooms):
        self._rooms = rooms

    async def login(self, u, p):
        return object()

    async def fetch_rooms(self, client, **kw):
        return self._rooms


class FakeSheets:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    async def append_rows(self, *, credentials, spreadsheet_id, sheet_name, rows):
        if self._fail:
            raise RuntimeError("sheet boom")
        self.calls.append(rows)
        return {"updates": {"updatedRange": f"'{sheet_name}'!A2:N2"}}

    async def read_values(self, **kwargs):
        return [RENTAL_HEADERS]

    async def find_row_by_value(self, **kwargs):
        return None

    async def update_cells(self, **kwargs):
        self.calls.append(kwargs["values"])
        return {}


def _make_config(user_id, **overrides):
    defaults = dict(
        user_id=user_id,
        name="c",
        source_type="nhatrovn",
        source_credentials_enc=encrypt(json.dumps({"username": "x", "password": "y"})),
        province_code="79",
        province_name="HCM",
        district_code="764",
        district_name="Gò Vấp",
        caption_template="{title}",
        contact_phone="0900",
        poll_interval_seconds=300,
        post_spacing_seconds=1,
    )
    defaults.update(overrides)
    return RentalConfig(**defaults)


def test_render_caption_has_hashtag():
    room = Room(external_room_id="P1", title="P1", price="3tr", area_text="30m2",
                address="Gò Vấp", district="Gò Vấp", status="Trống", description="đẹp", images=[])
    cap = render_caption(
        "🏠 {title}\n💰 {price} 📐 {area_text}\n📍 {address}\n{description}\n📞 {contact_phone}\n#thuetro #{district_slug}",
        room, "0900",
    )
    assert "#GoVap" in cap and "0900" in cap


def test_render_caption_falls_back_on_bad_template():
    room = Room(external_room_id="P1", title="P1", price="3tr", area_text="30m2",
                address="Gò Vấp", district="Gò Vấp", status="Trống", description="đẹp", images=[])
    cap = render_caption("{unknown_field}", room, "0900")
    assert "P1" in cap and "0900" in cap


def test_render_caption_bad_placeholder_does_not_crash():
    room = Room(external_room_id="P2", title="Phòng đẹp quận 1", price="3tr", area_text="30m2",
                address="Gò Vấp", district="Gò Vấp", status="Trống", description="đẹp", images=[])
    cap = render_caption("{title.nonexistent}", room, "0900")
    assert cap
    assert "Phòng đẹp quận 1" in cap


@pytest.mark.asyncio
async def test_sync_dedups_and_matches(session, user_id, _ensure_user, session_factory):
    cfg = _make_config(user_id)
    session.add(cfg)
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
                               group_id="10", group_name="Thuê trọ Gò Vấp", group_url="u"))
    await session.commit()
    rooms = [Room("P.004", "P.004", district="Gò Vấp", address="Gò Vấp", status="Trống"),
             Room("P.005", "P.005", district="Quận 1", address="Quận 1", status="Trống")]
    svc = RentalSyncService(session_factory, adapter=FakeAdapter(rooms))
    r1 = await svc.sync_config(cfg.id)
    assert r1["added"] == 2
    assert r1["matched"] == 1
    assert r1["waiting"] == 1
    r2 = await svc.sync_config(cfg.id)  # re-run: no duplicates
    assert r2["added"] == 0


@pytest.mark.asyncio
async def test_sync_skips_rented(session, user_id, _ensure_user, session_factory):
    cfg = _make_config(user_id)
    session.add(cfg)
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
                               group_id="10", group_name="Thuê trọ Gò Vấp", group_url="u"))
    await session.commit()
    rooms = [Room("V1", "V1", district="Gò Vấp", address="Gò Vấp", status="Trống"),
             Room("R1", "R1", district="Gò Vấp", address="Gò Vấp", status="Đã thuê")]
    svc = RentalSyncService(session_factory, adapter=FakeAdapter(rooms))
    result = await svc.sync_config(cfg.id)
    assert result["added"] == 2
    assert result["rented"] == 1

    rented = (await session.execute(
        select(RentalRoom).where(RentalRoom.external_room_id == "R1")
    )).scalar_one()
    assert rented.status == "rented"


@pytest.mark.asyncio
async def test_sync_caption_uses_config_district_when_room_missing(session, user_id, _ensure_user, session_factory):
    cfg = _make_config(user_id, district_name="Gò Vấp", caption_template="{district_slug}")
    session.add(cfg)
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
                               group_id="10", group_name="Thuê trọ Gò Vấp", group_url="u"))
    await session.commit()
    rooms = [Room("D1", "D1", district=None, address="somewhere", status="Trống")]
    svc = RentalSyncService(session_factory, adapter=FakeAdapter(rooms))
    result = await svc.sync_config(cfg.id)
    assert result["added"] == 1

    room_row = (await session.execute(
        select(RentalRoom).where(RentalRoom.external_room_id == "D1")
    )).scalar_one()
    assert room_row.district == "Gò Vấp"
    assert room_row.caption == "GoVap"


@pytest.mark.asyncio
async def test_sync_mirrors_to_sheet(session, user_id, _ensure_user, session_factory):
    conn = GoogleSheetConnection(
        user_id=user_id, name="sheet", spreadsheet_id="sid", sheet_name="Posts",
        credentials_enc=encrypt(json.dumps({"client_email": "x@y.z"})),
        service_account_email="x@y.z",
    )
    session.add(conn)
    await session.flush()
    cfg = _make_config(user_id, google_sheet_connection_id=conn.id)
    session.add(cfg)
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
                               group_id="10", group_name="Thuê trọ Gò Vấp", group_url="u"))
    await session.commit()
    rooms = [Room("S1", "S1", district="Gò Vấp", address="Gò Vấp", status="Trống")]
    fake_sheets = FakeSheets()
    svc = RentalSyncService(session_factory, adapter=FakeAdapter(rooms))
    result = await svc.sync_config(cfg.id)
    assert result["added"] == 1
    assert result["mirror_queued"] == 1
    mirror_result = await run_rental_sheet_mirror(
        session_factory, sheets_client=fake_sheets,
    )
    assert mirror_result["succeeded"] == 1
    assert len(fake_sheets.calls) == 1
    assert fake_sheets.calls[0][0][0] == "S1"

    updated = Room(
        "S1", "S1 updated", price="5tr",
        district="Gò Vấp", address="Gò Vấp", status="Trống",
    )
    await RentalSyncService(
        session_factory, adapter=FakeAdapter([updated]),
    ).sync_config(cfg.id)
    second_mirror = await run_rental_sheet_mirror(
        session_factory, sheets_client=fake_sheets,
    )
    assert second_mirror["succeeded"] == 1
    assert len(fake_sheets.calls) == 2
    assert fake_sheets.calls[1][0][0] == "S1"
    assert fake_sheets.calls[1][0][1] == "S1 updated"
    assert len(list((await session.execute(select(RentalSheetMirrorJob))).scalars())) == 1


@pytest.mark.asyncio
async def test_sync_sheet_failure_does_not_break(session, user_id, _ensure_user, session_factory):
    conn = GoogleSheetConnection(
        user_id=user_id, name="sheet", spreadsheet_id="sid", sheet_name="Posts",
        credentials_enc=encrypt(json.dumps({"client_email": "x@y.z"})),
        service_account_email="x@y.z",
    )
    session.add(conn)
    await session.flush()
    cfg = _make_config(user_id, google_sheet_connection_id=conn.id)
    session.add(cfg)
    session.add(FacebookGroup(id=uuid.uuid4(), user_id=user_id, facebook_account_id=uuid.uuid4(),
                               group_id="10", group_name="Thuê trọ Gò Vấp", group_url="u"))
    await session.commit()
    rooms = [Room("F1", "F1", district="Gò Vấp", address="Gò Vấp", status="Trống")]
    fake_sheets = FakeSheets(fail=True)
    svc = RentalSyncService(session_factory, adapter=FakeAdapter(rooms))
    result = await svc.sync_config(cfg.id)
    assert result["added"] == 1
    assert result["matched"] == 1
    assert result["waiting"] == 0
    mirror_result = await run_rental_sheet_mirror(
        session_factory, sheets_client=fake_sheets,
    )
    assert mirror_result["retried"] == 1
    job = (await session.execute(select(RentalSheetMirrorJob))).scalar_one()
    assert job.status == "pending"
    assert job.next_retry_at is not None
    assert job.error == "sheet boom"


@pytest.mark.asyncio
async def test_sync_upserts_room_and_cancels_pending_job_when_rented(
    session, user_id, _ensure_user, session_factory,
):
    cfg = _make_config(user_id)
    session.add(cfg)
    session.add(FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=uuid.uuid4(),
        group_id="10",
        group_name="Thuê trọ Gò Vấp",
        group_url="u",
        status="available",
    ))
    await session.commit()

    await RentalSyncService(
        session_factory,
        adapter=FakeAdapter([
            Room("U1", "Phòng cũ", price="3tr", district="Gò Vấp", status="Trống"),
        ]),
    ).sync_config(cfg.id)
    row = (await session.execute(
        select(RentalRoom).where(RentalRoom.external_room_id == "U1")
    )).scalar_one()
    job = (await session.execute(
        select(PublicationJob).where(PublicationJob.rental_room_id == row.id)
    )).scalar_one()
    assert job.status == "pending"

    result = await RentalSyncService(
        session_factory,
        adapter=FakeAdapter([
            Room("U1", "Phòng đã cập nhật", price="4tr", district="Gò Vấp", status="Đã thuê"),
        ]),
    ).sync_config(cfg.id)
    assert result["added"] == 0
    assert result["updated"] == 1
    assert result["rented"] == 1

    await session.refresh(row)
    await session.refresh(job)
    assert row.title == "Phòng đã cập nhật"
    assert row.price == "4tr"
    assert row.status == "rented"
    assert job.status == "canceled"
