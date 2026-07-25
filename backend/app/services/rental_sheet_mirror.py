"""Durable, idempotent RentalRoom -> Google Sheet mirroring."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.crypto import decrypt
from app.models.sqlmodels import (
    GoogleSheetConnection,
    RentalRoom,
    RentalSheetMirrorJob,
)
from app.services.google_sheets import GoogleSheetsClient
from app.services.publication_jobs import retry_delay


RENTAL_HEADERS = [
    "external_room_id",
    "title",
    "price",
    "area",
    "address",
    "district",
    "ward",
    "source_status",
    "post_status",
    "facebook_urls",
    "error",
    "last_seen_at",
    "posted_at",
    "updated_at",
]
UPDATED_RANGE_ROW_RE = re.compile(r"![A-Z]+([1-9][0-9]*):")


async def enqueue_rental_mirror(
    session,
    room: RentalRoom,
    connection_id: uuid.UUID | None,
) -> RentalSheetMirrorJob | None:
    if connection_id is None:
        room.mirror_status = None
        room.mirror_error = None
        return None
    payload_hash = _payload_hash(_room_values(room))
    job = (await session.execute(
        select(RentalSheetMirrorJob).where(
            RentalSheetMirrorJob.rental_room_id == room.id,
            RentalSheetMirrorJob.connection_id == connection_id,
        )
    )).scalar_one_or_none()
    if job is None:
        job = RentalSheetMirrorJob(
            user_id=room.user_id,
            rental_room_id=room.id,
            connection_id=connection_id,
            status="pending",
            payload_hash=payload_hash,
        )
        session.add(job)
    elif job.payload_hash != payload_hash or job.status != "succeeded":
        job.status = "pending"
        job.payload_hash = payload_hash
        job.next_retry_at = None
        job.error = None
    room.mirror_status = job.status
    room.mirror_error = job.error
    await session.flush()
    return job


async def run_rental_sheet_mirror(
    get_session,
    *,
    sheets_client=None,
    now: datetime | None = None,
    limit: int = 20,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    client = sheets_client or GoogleSheetsClient()
    async with get_session() as session:
        job_ids = list((await session.execute(
            select(RentalSheetMirrorJob.id).where(
                RentalSheetMirrorJob.status == "pending",
                or_(
                    RentalSheetMirrorJob.next_retry_at.is_(None),
                    RentalSheetMirrorJob.next_retry_at <= now,
                ),
            ).order_by(RentalSheetMirrorJob.created_at).limit(limit)
        )).scalars())

    counts = {"succeeded": 0, "retried": 0, "failed": 0}
    for job_id in job_ids:
        result = await _mirror_one(get_session, client, job_id, now)
        counts[result] += 1
    return counts


async def _mirror_one(get_session, client, job_id: uuid.UUID, now: datetime) -> str:
    async with get_session() as session:
        job = (await session.execute(
            select(RentalSheetMirrorJob)
            .where(
                RentalSheetMirrorJob.id == job_id,
                RentalSheetMirrorJob.status == "pending",
            )
            .with_for_update(skip_locked=True)
        )).scalar_one_or_none()
        if job is None:
            return "succeeded"
        room = await session.get(RentalRoom, job.rental_room_id)
        connection = await session.get(GoogleSheetConnection, job.connection_id)
        if (
            room is None
            or connection is None
            or room.user_id != job.user_id
            or connection.user_id != job.user_id
            or connection.status != "connected"
        ):
            return await _fail_claimed(
                session, job, room, "Rental mirror ownership or connection is invalid", now,
            )
        job.status = "syncing"
        job.attempt_count += 1
        room.mirror_status = "syncing"
        room.mirror_error = None
        snapshot = {
            "credentials": json.loads(decrypt(connection.credentials_enc) or "{}"),
            "spreadsheet_id": connection.spreadsheet_id,
            "sheet_name": connection.sheet_name,
            "external_room_id": room.external_room_id,
            "values": _room_values(room),
            "row_number": job.sheet_row_number,
        }
        await session.commit()

    try:
        headers = await client.read_values(
            credentials=snapshot["credentials"],
            spreadsheet_id=snapshot["spreadsheet_id"],
            sheet_name=snapshot["sheet_name"],
            a1_range="A1:N1",
        )
        if not headers:
            await client.update_cells(
                credentials=snapshot["credentials"],
                spreadsheet_id=snapshot["spreadsheet_id"],
                sheet_name=snapshot["sheet_name"],
                a1_range="A1:N1",
                values=[RENTAL_HEADERS],
            )
        elif headers[0][:len(RENTAL_HEADERS)] != RENTAL_HEADERS:
            raise ValueError(
                "Rental mirror sheet headers do not match the RentalRooms schema"
            )

        row_number = snapshot["row_number"] or await client.find_row_by_value(
            credentials=snapshot["credentials"],
            spreadsheet_id=snapshot["spreadsheet_id"],
            sheet_name=snapshot["sheet_name"],
            value=snapshot["external_room_id"],
        )
        if row_number:
            await client.update_cells(
                credentials=snapshot["credentials"],
                spreadsheet_id=snapshot["spreadsheet_id"],
                sheet_name=snapshot["sheet_name"],
                a1_range=f"A{row_number}:N{row_number}",
                values=[snapshot["values"]],
            )
        else:
            response = await client.append_rows(
                credentials=snapshot["credentials"],
                spreadsheet_id=snapshot["spreadsheet_id"],
                sheet_name=snapshot["sheet_name"],
                rows=[snapshot["values"]],
            )
            updated_range = str(
                ((response or {}).get("updates") or {}).get("updatedRange") or ""
            )
            match = UPDATED_RANGE_ROW_RE.search(updated_range)
            row_number = int(match.group(1)) if match else None
    except Exception as exc:  # noqa: BLE001 - persist integration failure
        async with get_session() as session:
            job = await session.get(RentalSheetMirrorJob, job_id)
            room = await session.get(RentalRoom, job.rental_room_id) if job else None
            if job is None:
                return "failed"
            return await _fail_claimed(session, job, room, str(exc), now)

    async with get_session() as session:
        job = await session.get(RentalSheetMirrorJob, job_id)
        if job is None:
            return "succeeded"
        room = await session.get(RentalRoom, job.rental_room_id)
        job.status = "succeeded"
        job.sheet_row_number = row_number
        job.error = None
        job.next_retry_at = None
        job.synced_at = now
        if room:
            job.payload_hash = _payload_hash(_room_values(room))
            room.mirror_status = "succeeded"
            room.mirror_error = None
        await session.commit()
    return "succeeded"


async def _fail_claimed(session, job, room, error: str, now: datetime) -> str:
    job.error = error[:2000]
    if job.attempt_count >= job.max_attempts:
        job.status = "failed"
        job.next_retry_at = None
        result = "failed"
    else:
        job.status = "pending"
        job.next_retry_at = now + retry_delay(job.attempt_count)
        result = "retried"
    if room:
        room.mirror_status = job.status
        room.mirror_error = job.error
    await session.commit()
    return result


def _room_values(room: RentalRoom) -> list[str]:
    updated_at = room.__dict__.get("updated_at")
    return [
        room.external_room_id,
        room.title,
        room.price,
        room.area_text,
        room.address,
        room.district or "",
        room.ward or "",
        room.source_status,
        room.status,
        json.dumps(json.loads(room.post_urls_json or "{}"), ensure_ascii=False),
        room.error or "",
        room.last_seen_at.isoformat() if room.last_seen_at else "",
        room.posted_at.isoformat() if room.posted_at else "",
        updated_at.isoformat() if updated_at else "",
    ]


def _payload_hash(values: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
