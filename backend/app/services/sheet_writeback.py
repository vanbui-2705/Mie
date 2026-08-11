"""Durable status/result write-back for Google Sheet source rows."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.crypto import decrypt
from app.models.sqlmodels import (
    GoogleSheetConnection,
    PublicationJob,
    SheetSourceItem,
    SheetWritebackJob,
)
from app.services.google_sheets import GoogleSheetsClient
from app.services.publication_jobs import retry_delay


async def recover_stale_writebacks(
    get_session,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 900,
) -> int:
    """Return write-backs abandoned mid-call to the queue.

    `_write_one` marks a job "syncing" and commits before it calls Google, so a
    restart in that window strands the row: nothing selects "syncing", and the
    sheet keeps advertising a post that already went out. Re-running a
    write-back is safe — it overwrites the same cells with the current state.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=max(60, stale_after_seconds))
    recovered = 0
    async with get_session() as session:
        jobs = list((await session.execute(
            select(SheetWritebackJob).where(
                SheetWritebackJob.status == "syncing",
                SheetWritebackJob.updated_at <= cutoff,
            )
        )).scalars())
        for job in jobs:
            if job.attempt_count >= job.max_attempts:
                job.status = "failed"
                job.error = "Write-back was interrupted and ran out of attempts"
                job.next_retry_at = None
            else:
                job.status = "pending"
                job.error = "Write-back was interrupted; requeued"
                job.next_retry_at = None
            recovered += 1
        if recovered:
            await session.commit()
    return recovered


async def run_sheet_writebacks(
    get_session,
    *,
    sheets_client=None,
    now: datetime | None = None,
    limit: int = 50,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    client = sheets_client or GoogleSheetsClient()
    async with get_session() as session:
        ids = list((await session.execute(
            select(SheetWritebackJob.id).where(
                SheetWritebackJob.status == "pending",
                or_(
                    SheetWritebackJob.next_retry_at.is_(None),
                    SheetWritebackJob.next_retry_at <= now,
                ),
            ).order_by(SheetWritebackJob.created_at).limit(limit)
        )).scalars())
    counts = {"succeeded": 0, "retried": 0, "failed": 0, "stale": 0}
    for job_id in ids:
        result = await _write_one(get_session, client, job_id, now)
        counts[result] += 1
    return counts


async def _write_one(get_session, client, job_id: uuid.UUID, now: datetime) -> str:
    async with get_session() as session:
        job = (await session.execute(
            select(SheetWritebackJob)
            .where(
                SheetWritebackJob.id == job_id,
                SheetWritebackJob.status == "pending",
            )
            .with_for_update(skip_locked=True)
        )).scalar_one_or_none()
        if job is None:
            return "stale"
        source = await session.get(SheetSourceItem, job.source_item_id)
        if source is None or source.source_version != job.source_version:
            job.status = "stale"
            job.error = "A newer source version superseded this write-back"
            await session.commit()
            return "stale"
        connection = await session.get(GoogleSheetConnection, source.connection_id)
        if (
            connection is None
            or connection.user_id != job.user_id
            # Same set sync accepts. Refusing read_only here only burned the
            # retry budget on connections the ingest side was happy to use.
            or connection.status not in {"connected", "read_only"}
        ):
            return await _fail(session, job, "Writable Google Sheet connection is unavailable", now)
        publication_jobs = list((await session.execute(
            select(PublicationJob).where(
                PublicationJob.sheet_source_item_id == source.id,
                PublicationJob.source_version == source.source_version,
            )
        )).scalars())
        success_jobs = [item for item in publication_jobs if item.status == "succeeded"]
        urls = [item.facebook_url for item in success_jobs if item.facebook_url]
        errors = list(dict.fromkeys(
            str(item.error).strip()
            for item in publication_jobs
            if str(item.error or "").strip()
        ))
        values = [[
            source.status.upper(),
            "\n".join(urls),
            f"{len(success_jobs)}/{len(publication_jobs)} targets succeeded",
            "; ".join(errors)[:2000],
            source.queued_at.isoformat() if source.queued_at else "",
            source.completed_at.isoformat() if source.completed_at else "",
        ]]
        snapshot = {
            "credentials": json.loads(decrypt(connection.credentials_enc) or "{}"),
            "spreadsheet_id": connection.spreadsheet_id,
            "sheet_name": connection.sheet_name,
            "range": f"I{source.sheet_row_number}:N{source.sheet_row_number}",
            "values": values,
        }
        job.status = "syncing"
        job.attempt_count += 1
        await session.commit()

    try:
        await client.update_cells(
            credentials=snapshot["credentials"],
            spreadsheet_id=snapshot["spreadsheet_id"],
            sheet_name=snapshot["sheet_name"],
            a1_range=snapshot["range"],
            values=snapshot["values"],
        )
    except Exception as exc:  # noqa: BLE001
        async with get_session() as session:
            job = await session.get(SheetWritebackJob, job_id)
            if job is None:
                return "failed"
            return await _fail(session, job, str(exc), now)

    async with get_session() as session:
        job = await session.get(SheetWritebackJob, job_id)
        if job:
            job.status = "succeeded"
            job.error = None
            job.next_retry_at = None
            job.synced_at = now
            await session.commit()
    return "succeeded"


async def _fail(session, job, error: str, now: datetime) -> str:
    job.error = error[:2000]
    if job.attempt_count >= job.max_attempts:
        job.status = "failed"
        job.next_retry_at = None
        result = "failed"
    else:
        job.status = "pending"
        job.next_retry_at = now + retry_delay(job.attempt_count)
        result = "retried"
    await session.commit()
    return result
