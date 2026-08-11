import json
import uuid

import pytest
from sqlalchemy import select

from app.crypto import encrypt
from app.models.sqlmodels import (
    FacebookGroup,
    GoogleSheetConnection,
    PublicationJob,
    SheetCampaign,
    SheetSourceItem,
    TaskItem,
    TaskItemStatus,
)
from app.services.publication_jobs import reconcile_publication_jobs
from app.services.sheet_post import SheetPostService
from app.services.sheet_sync import SHEET_HEADERS, sync_sheet_campaign
from app.services.sheet_writeback import run_sheet_writebacks


class FakeSheets:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    async def read_values(self, **kwargs):
        return self.rows

    async def update_cells(self, **kwargs):
        self.updates.append(kwargs)
        return {"updatedRows": 1}


@pytest.mark.asyncio
async def test_ready_row_dispatches_and_posts_only_after_task_success(
    session, session_factory, user_id, _ensure_user,
):
    group = FacebookGroup(
        id=uuid.uuid4(),
        user_id=user_id,
        facebook_account_id=uuid.uuid4(),
        group_id="100",
        group_name="Thuê trọ Gò Vấp",
        group_url="https://facebook.example/groups/100",
        status="available",
    )
    connection = GoogleSheetConnection(
        user_id=user_id,
        name="Posts",
        spreadsheet_id="abcdefghijk",
        sheet_name="Posts",
        credentials_enc=encrypt(json.dumps({"client_email": "fake"})),
        service_account_email="fake",
        status="connected",
    )
    session.add_all([group, connection])
    await session.flush()
    campaign = SheetCampaign(
        user_id=user_id,
        connection_id=connection.id,
        name="Campaign",
        default_targets_json=json.dumps([f"group:{group.id}"]),
        default_schedule_mode="NOW",
    )
    session.add(campaign)
    await session.commit()

    row = [
        "POST-1", "Nội dung đăng", "", "", "", "NOW", "", "5",
        "READY", "", "", "", "", "",
    ]
    sheets = FakeSheets([SHEET_HEADERS, row])
    first = await sync_sheet_campaign(
        session_factory, campaign.id, sheets_client=sheets,
    )
    assert first == {"queued": 1, "invalid": 0, "duplicate": 0}

    source = (await session.execute(select(SheetSourceItem))).scalar_one()
    job = (await session.execute(select(PublicationJob))).scalar_one()
    assert source.status == "queued"
    assert job.status == "pending"

    duplicate = await sync_sheet_campaign(
        session_factory, campaign.id, sheets_client=sheets,
    )
    assert duplicate["duplicate"] == 1
    assert len(list((await session.execute(select(PublicationJob))).scalars())) == 1

    calls = []

    async def fake_runner(**kwargs):
        item = TaskItem(
            run_id=uuid.UUID(kwargs["run_id"]),
            user_id=user_id,
            item_index=1,
            uid="account",
            target_link="group",
            action="post_group",
            status=TaskItemStatus.PENDING,
        )
        session.add(item)
        await session.flush()
        calls.append(kwargs)
        return {
            "accepted": True,
            "task_item_ids": [item.id],
            "status": "queued",
        }

    dispatched = await SheetPostService(
        session_factory, run_post=fake_runner,
    ).post_due()
    assert len(dispatched) == 1
    assert dispatched[0]["status"] == "queued"
    await session.refresh(source)
    assert source.status == "posting"
    assert source.completed_at is None

    await session.refresh(job)
    item = await session.get(TaskItem, job.task_item_id)
    item.status = TaskItemStatus.SUCCESS
    item.output_link = "https://facebook.example/posts/1"
    await session.commit()
    await reconcile_publication_jobs(session_factory)

    await session.refresh(source)
    assert source.status == "posted"
    assert source.completed_at is not None

    writeback = await run_sheet_writebacks(
        session_factory, sheets_client=sheets,
    )
    assert writeback["succeeded"] >= 1
    final_values = sheets.updates[-1]["values"][0]
    assert final_values[0] == "POSTED"
    assert final_values[1] == "https://facebook.example/posts/1"


@pytest.mark.asyncio
async def test_invalid_ready_row_is_recorded_without_publication_job(
    session, session_factory, user_id, _ensure_user,
):
    connection = GoogleSheetConnection(
        user_id=user_id,
        name="Posts",
        spreadsheet_id="abcdefghijk",
        sheet_name="Posts",
        credentials_enc=encrypt(json.dumps({"client_email": "fake"})),
        service_account_email="fake",
        status="connected",
    )
    session.add(connection)
    await session.flush()
    campaign = SheetCampaign(
        user_id=user_id,
        connection_id=connection.id,
        name="Campaign",
        default_targets_json="[]",
    )
    session.add(campaign)
    await session.commit()
    sheets = FakeSheets([
        SHEET_HEADERS,
        ["", "", "", "", "", "NOW", "", "", "READY"],
    ])

    result = await sync_sheet_campaign(
        session_factory, campaign.id, sheets_client=sheets,
    )
    assert result["invalid"] == 1
    source = (await session.execute(select(SheetSourceItem))).scalar_one()
    assert source.status == "invalid"
    assert source.validation_error
    assert (await session.execute(select(PublicationJob))).scalar_one_or_none() is None


def test_media_cell_keeps_commas_that_belong_to_the_url() -> None:
    """A comma only separates URLs when the next one starts right after it.

    Cloudinary and Drive both emit commas inside a path, and splitting on every
    comma turned one valid URL into two broken ones.
    """
    from app.services.sheet_sync import _split_lines

    assert _split_lines(
        "https://res.cloudinary.test/upload/w_100,h_200/a.jpg"
    ) == ["https://res.cloudinary.test/upload/w_100,h_200/a.jpg"]
    assert _split_lines(
        "https://a.test/1.jpg, https://b.test/2.jpg"
    ) == ["https://a.test/1.jpg", "https://b.test/2.jpg"]
    assert _split_lines("https://a.test/1.jpg\nhttps://b.test/2.jpg") == [
        "https://a.test/1.jpg", "https://b.test/2.jpg",
    ]
    assert _split_lines("") == []
