"""A write-back must not disappear because the process died mid-call.

`_write_one` flips the job to "syncing" and commits before it talks to Google,
so a crash or a container restart in that window leaves a row no query ever
looks at again: the sheet keeps showing READY for a post that already went out.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.crypto import encrypt
from app.models.sqlmodels import (
    GoogleSheetConnection,
    SheetCampaign,
    SheetSourceItem,
    SheetWritebackJob,
)
from app.services.sheet_writeback import recover_stale_writebacks, run_sheet_writebacks


class FakeSheets:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    async def update_cells(self, **kwargs):
        self.updates.append(kwargs)
        return {"updatedRows": 1}


async def _connection(session, user_id, status: str = "connected") -> GoogleSheetConnection:
    connection = GoogleSheetConnection(
        id=uuid.uuid4(),
        user_id=user_id,
        name="Posts",
        spreadsheet_id="abcdefghijk",
        sheet_name="Posts",
        credentials_enc=encrypt(json.dumps({"client_email": "fake"})),
        service_account_email="fake",
        status=status,
    )
    session.add(connection)
    await session.flush()
    return connection


async def _source(session, user_id, connection) -> SheetSourceItem:
    campaign = SheetCampaign(
        id=uuid.uuid4(),
        user_id=user_id,
        connection_id=connection.id,
        name="Campaign",
        default_schedule_mode="NOW",
    )
    session.add(campaign)
    await session.flush()
    source = SheetSourceItem(
        id=uuid.uuid4(),
        user_id=user_id,
        connection_id=connection.id,
        campaign_id=campaign.id,
        external_id=f"POST-{uuid.uuid4().hex[:6]}",
        sheet_row_number=2,
        content="Nội dung",
        content_hash="hash",
        status="posted",
    )
    session.add(source)
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_a_writeback_stuck_in_syncing_is_returned_to_pending(
    session, session_factory, user_id, _ensure_user,
) -> None:
    connection = await _connection(session, user_id)
    source = await _source(session, user_id, connection)
    stale_since = datetime.now(timezone.utc) - timedelta(hours=1)
    job = SheetWritebackJob(
        id=uuid.uuid4(),
        user_id=user_id,
        source_item_id=source.id,
        source_version=source.source_version,
        status="syncing",
        attempt_count=1,
        updated_at=stale_since,
    )
    session.add(job)
    await session.commit()

    recovered = await recover_stale_writebacks(session_factory, stale_after_seconds=300)
    assert recovered == 1

    refreshed = (
        await session.execute(select(SheetWritebackJob).where(SheetWritebackJob.id == job.id))
    ).scalar_one()
    await session.refresh(refreshed)
    assert refreshed.status == "pending"


@pytest.mark.asyncio
async def test_a_read_only_connection_still_receives_the_writeback(
    session, session_factory, user_id, _ensure_user,
) -> None:
    """Sync accepts read_only, so refusing it here only burns the retry budget."""
    connection = await _connection(session, user_id, status="read_only")
    source = await _source(session, user_id, connection)
    session.add(SheetWritebackJob(
        id=uuid.uuid4(),
        user_id=user_id,
        source_item_id=source.id,
        source_version=source.source_version,
        status="pending",
    ))
    await session.commit()

    sheets = FakeSheets()
    counts = await run_sheet_writebacks(session_factory, sheets_client=sheets)

    assert counts["succeeded"] == 1
    assert len(sheets.updates) == 1
