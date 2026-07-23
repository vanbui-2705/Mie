import json, uuid, pytest
from datetime import datetime, timezone
from sqlalchemy import select
from app.crypto import encrypt
from app.models.sqlmodels import RentalConfig, RentalRoom
from app.services.nhatrovn_adapter import Room
from app.services.rental_sync import run_rental_sync
from app.services.rental_post import run_rental_posting


class FakeAdapter:
    def __init__(self, rooms): self._rooms = rooms
    async def login(self, u, p): return object()
    async def fetch_rooms(self, client, **kw): return self._rooms


def _make_config(user_id, **overrides):
    fields = dict(user_id=user_id, name="c", source_type="nhatrovn",
        source_credentials_enc=encrypt(json.dumps({"username": "x", "password": "y"})),
        province_code="79", province_name="HCM", district_code="764", district_name="Gò Vấp",
        caption_template="{title}", contact_phone="0900", poll_interval_seconds=300, post_spacing_seconds=1)
    fields.update(overrides)
    return RentalConfig(**fields)


async def _room_count(session, cfg):
    return len(list((await session.execute(
        select(RentalRoom).where(RentalRoom.config_id == cfg.id))).scalars()))


@pytest.mark.asyncio
async def test_runners_no_config_ok(session, session_factory):
    # empty tables -> both runners are no-ops and must not raise
    await run_rental_sync(session_factory)
    await run_rental_posting(session_factory)


@pytest.mark.asyncio
async def test_run_rental_sync_processes_due_config(session, user_id, _ensure_user, session_factory):
    cfg = RentalConfig(user_id=user_id, name="c", source_type="nhatrovn",
        source_credentials_enc=encrypt(json.dumps({"username": "x", "password": "y"})),
        province_code="79", province_name="HCM", district_code="764", district_name="Gò Vấp",
        caption_template="{title}", contact_phone="0900", poll_interval_seconds=300, post_spacing_seconds=1)
    session.add(cfg)
    await session.commit()
    rooms = [Room("R1", "R1", district="Gò Vấp", address="Gò Vấp", status="Trống")]
    await run_rental_sync(session_factory, adapter=FakeAdapter(rooms))
    # the due config was synced: last_synced_at set, one room inserted
    from app.models.sqlmodels import RentalRoom
    from sqlalchemy import select
    await session.refresh(cfg)
    assert cfg.last_synced_at is not None
    n = len(list((await session.execute(select(RentalRoom).where(RentalRoom.config_id == cfg.id))).scalars()))
    assert n == 1


@pytest.mark.asyncio
async def test_run_rental_sync_skips_not_due_config(session, user_id, _ensure_user, session_factory):
    # last_synced_at is recent and poll interval is long -> config is NOT due yet.
    recent = datetime.now(timezone.utc)
    cfg = _make_config(user_id, poll_interval_seconds=3600, last_synced_at=recent, status="active")
    session.add(cfg)
    await session.commit()
    rooms = [Room("R1", "R1", district="Gò Vấp", address="Gò Vấp", status="Trống")]
    await run_rental_sync(session_factory, adapter=FakeAdapter(rooms))
    # not due -> sync_config never ran: no rooms inserted, last_synced_at untouched
    await session.refresh(cfg)
    assert await _room_count(session, cfg) == 0
    # last_synced_at unchanged (SQLite returns it tz-naive; compare on the wall clock)
    assert cfg.last_synced_at.replace(tzinfo=timezone.utc) == recent


@pytest.mark.asyncio
async def test_run_rental_sync_excludes_paused_config(session, user_id, _ensure_user, session_factory):
    # a paused config is filtered out entirely, even though it is due (last_synced_at None).
    cfg = _make_config(user_id, status="paused", last_synced_at=None)
    session.add(cfg)
    await session.commit()
    rooms = [Room("R1", "R1", district="Gò Vấp", address="Gò Vấp", status="Trống")]
    await run_rental_sync(session_factory, adapter=FakeAdapter(rooms))
    await session.refresh(cfg)
    assert await _room_count(session, cfg) == 0
    assert cfg.last_synced_at is None  # never synced
