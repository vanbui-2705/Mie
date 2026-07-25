"""Google Sheet READY-row ingestion with validation and idempotent job creation."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.crypto import decrypt
from app.models.sqlmodels import (
    FacebookAccount,
    FacebookGroup,
    FacebookPage,
    GoogleSheetConnection,
    PublicationJob,
    SheetCampaign,
    SheetSourceItem,
    SheetWritebackJob,
    TaskItem,
    TaskItemStatus,
)
from app.services.google_sheets import GoogleSheetsClient
from app.services.rental_media import RentalMediaError, RentalMediaStore


SHEET_HEADERS = [
    "external_id", "content", "media_urls", "link", "targets",
    "schedule_mode", "publish_at", "priority", "status",
    "facebook_urls", "result", "error", "queued_at", "posted_at",
]


class SheetSyncError(Exception):
    pass


class SheetSyncBusy(SheetSyncError):
    pass


async def sync_sheet_campaign(
    get_session,
    campaign_id: uuid.UUID,
    *,
    sheets_client=None,
    media_store=None,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    async with get_session() as session:
        campaign = (await session.execute(
            select(SheetCampaign)
            .where(SheetCampaign.id == campaign_id)
            .with_for_update(skip_locked=True)
        )).scalar_one_or_none()
        if campaign is None:
            raise SheetSyncError("Sheet campaign not found")
        attempt_at = campaign.last_sync_attempt_at
        if attempt_at is not None and attempt_at.tzinfo is None:
            attempt_at = attempt_at.replace(tzinfo=timezone.utc)
        if (
            campaign.status == "syncing"
            and attempt_at
            and (now - attempt_at).total_seconds() < 900
        ):
            raise SheetSyncBusy("Sheet campaign sync is already running")
        connection = await session.get(GoogleSheetConnection, campaign.connection_id)
        if (
            connection is None
            or connection.user_id != campaign.user_id
            or connection.status not in {"connected", "read_only"}
        ):
            raise SheetSyncError("Google Sheets connection is unavailable")
        snapshot = {
            "user_id": campaign.user_id,
            "connection_id": connection.id,
            "spreadsheet_id": connection.spreadsheet_id,
            "sheet_name": connection.sheet_name,
            "credentials": json.loads(decrypt(connection.credentials_enc) or "{}"),
            "timezone": campaign.timezone,
            "default_targets": json.loads(campaign.default_targets_json or "[]"),
            "default_mode": campaign.default_schedule_mode,
            "slots": json.loads(campaign.schedule_slots_json or "[]"),
            "weekdays": json.loads(campaign.active_weekdays_json or "[]"),
            "max_per_day": campaign.max_posts_per_day,
            "min_gap": campaign.min_post_gap_seconds,
            "late_policy": campaign.late_policy,
            "max_retries": campaign.max_retries,
        }
        campaign.status = "syncing"
        campaign.last_sync_attempt_at = now
        await session.commit()

    client = sheets_client or GoogleSheetsClient()
    try:
        rows = await client.read_values(
            credentials=snapshot["credentials"],
            spreadsheet_id=snapshot["spreadsheet_id"],
            sheet_name=snapshot["sheet_name"],
            a1_range="A1:N5000",
        )
    except Exception as exc:
        await _save_campaign_error(get_session, campaign_id, str(exc), now)
        raise SheetSyncError(str(exc)) from exc
    if not rows:
        await _save_campaign_error(get_session, campaign_id, "Google Sheet is empty", now)
        raise SheetSyncError("Google Sheet is empty")

    header = [str(value).strip().lower() for value in rows[0]]
    missing = [name for name in SHEET_HEADERS if name not in header]
    if missing:
        message = f"Missing Google Sheet headers: {', '.join(missing)}"
        await _save_campaign_error(get_session, campaign_id, message, now)
        raise SheetSyncError(message)
    indexes = {name: header.index(name) for name in SHEET_HEADERS}

    candidates: list[dict] = []
    for row_number, row in enumerate(rows[1:], start=2):
        status = _cell(row, indexes["status"]).strip().upper()
        if status != "READY":
            continue
        candidate = {
            "row_number": row_number,
            "external_id": _cell(row, indexes["external_id"]).strip(),
            "content": _cell(row, indexes["content"]).strip(),
            "media_urls": _split_lines(_cell(row, indexes["media_urls"])),
            "link": _cell(row, indexes["link"]).strip() or None,
            "targets": _split_targets(_cell(row, indexes["targets"]))
                or list(snapshot["default_targets"]),
            "mode": (_cell(row, indexes["schedule_mode"]).strip().upper()
                     or snapshot["default_mode"]),
            "publish_at": _cell(row, indexes["publish_at"]).strip(),
            "priority": _parse_int(_cell(row, indexes["priority"]), 0),
        }
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["priority"], item["row_number"]))

    media = media_store or RentalMediaStore(
        root=Path(settings.UPLOAD_DIR) / "sheet-media",
    )
    for item in candidates:
        item["error"] = _validate_candidate_shape(item)
        item["media_paths"] = []
        if item["error"] or not item["media_urls"]:
            continue
        if any(urlsplit(url).scheme not in {"http", "https"} for url in item["media_urls"]):
            item["error"] = "media_urls must contain absolute http/https URLs"
            continue
        try:
            item["media_paths"] = await media.download(
                user_id=snapshot["user_id"],
                config_id=campaign_id,
                external_room_id=item["external_id"] or f"row-{item['row_number']}",
                urls=item["media_urls"],
            )
        except RentalMediaError as exc:
            item["error"] = str(exc)

    counts = {"queued": 0, "invalid": 0, "duplicate": 0}
    async with get_session() as session:
        campaign = await session.get(SheetCampaign, campaign_id)
        if campaign is None:
            raise SheetSyncError("Sheet campaign was deleted during sync")
        occupied = [
            value for value in (await session.execute(
                select(SheetSourceItem.scheduled_at).where(
                    SheetSourceItem.campaign_id == campaign.id,
                    SheetSourceItem.scheduled_at.is_not(None),
                )
            )).scalars() if value is not None
        ]

        for item in candidates:
            existing = (await session.execute(
                select(SheetSourceItem).where(
                    SheetSourceItem.campaign_id == campaign.id,
                    SheetSourceItem.external_id == (
                        item["external_id"] or f"__invalid_row_{item['row_number']}"
                    ),
                )
            )).scalar_one_or_none()
            content_hash = _content_hash(item)
            if existing and existing.content_hash == content_hash and existing.status != "invalid":
                counts["duplicate"] += 1
                continue

            source = existing or SheetSourceItem(
                user_id=campaign.user_id,
                connection_id=campaign.connection_id,
                campaign_id=campaign.id,
                external_id=item["external_id"] or f"__invalid_row_{item['row_number']}",
                sheet_row_number=item["row_number"],
                content_hash=content_hash,
            )
            if existing:
                old_jobs = list((await session.execute(
                    select(PublicationJob).where(
                        PublicationJob.sheet_source_item_id == existing.id,
                        PublicationJob.source_version == existing.source_version,
                        PublicationJob.status.in_(
                            ["pending", "dispatching", "queued", "running"]
                        ),
                    )
                )).scalars())
                for old_job in old_jobs:
                    old_job.status = "canceled"
                    old_job.error = "Superseded by a newer Sheet source version"
                    old_job.finished_at = now
                    if old_job.task_item_id:
                        task_item = await session.get(TaskItem, old_job.task_item_id)
                        if task_item and task_item.status in {
                            TaskItemStatus.PENDING,
                            TaskItemStatus.RUNNING,
                        }:
                            task_item.status = TaskItemStatus.CANCELED
                            task_item.error = old_job.error
                source.source_version += 1
            else:
                session.add(source)
            source.sheet_row_number = item["row_number"]
            source.content = item["content"]
            source.link = item["link"]
            source.media_urls_json = json.dumps(item["media_urls"], ensure_ascii=False)
            source.media_paths_json = json.dumps(item["media_paths"], ensure_ascii=False)
            source.targets_json = json.dumps(item["targets"])
            source.schedule_mode = item["mode"]
            source.priority = item["priority"]
            source.content_hash = content_hash
            source.validation_error = item["error"]
            await session.flush()

            scheduled_at = None
            if not item["error"]:
                try:
                    scheduled_at = _schedule_item(item, snapshot, now, occupied)
                except ValueError as exc:
                    item["error"] = str(exc)
            if not item["error"]:
                target_rows, target_error = await _resolve_targets(
                    session, campaign.user_id, item["targets"],
                )
                if target_error:
                    item["error"] = target_error
            else:
                target_rows = []

            if item["error"]:
                source.status = "invalid"
                source.validation_error = item["error"]
                counts["invalid"] += 1
            else:
                source.status = "queued"
                source.validation_error = None
                source.requested_publish_at = (
                    scheduled_at if item["mode"] == "EXACT" else None
                )
                source.scheduled_at = scheduled_at
                source.queued_at = now
                occupied.append(scheduled_at)
                for target_type, target_id, external_id in target_rows:
                    session.add(PublicationJob(
                        user_id=campaign.user_id,
                        sheet_source_item_id=source.id,
                        source_version=source.source_version,
                        target_type=target_type,
                        target_id=target_id,
                        target_external_id=external_id,
                        scheduled_at=scheduled_at,
                        status="pending",
                        max_attempts=campaign.max_retries,
                    ))
                counts["queued"] += 1
            await enqueue_sheet_writeback(session, source)

        campaign.last_synced_at = now
        campaign.last_sync_attempt_at = now
        campaign.status = "active"
        campaign.last_error = None
        await session.commit()
    return counts


def _schedule_item(item: dict, campaign: dict, now: datetime, occupied: list[datetime]) -> datetime:
    mode = item["mode"]
    if mode == "NOW":
        return now
    tz = ZoneInfo(campaign["timezone"])
    if mode == "EXACT":
        if not item["publish_at"]:
            raise ValueError("publish_at is required for EXACT")
        try:
            parsed = datetime.fromisoformat(item["publish_at"])
        except ValueError as exc:
            raise ValueError("publish_at is invalid") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        parsed = parsed.astimezone(timezone.utc)
        if parsed < now:
            if campaign["late_policy"] == "miss":
                raise ValueError("publish_at is in the past")
            return now
        return parsed
    if mode != "AUTO":
        raise ValueError("schedule_mode must be NOW, EXACT or AUTO")
    slots = campaign["slots"]
    if not slots:
        raise ValueError("AUTO schedule requires at least one time slot")
    local_now = now.astimezone(tz)
    occupied_local = [value.astimezone(tz) for value in occupied]
    for day_offset in range(61):
        day = local_now.date() + timedelta(days=day_offset)
        if day.weekday() not in campaign["weekdays"]:
            continue
        day_values = [value for value in occupied_local if value.date() == day]
        if len(day_values) >= campaign["max_per_day"]:
            continue
        for slot in slots:
            hour, minute = [int(value) for value in slot.split(":", 1)]
            candidate = datetime.combine(day, time(hour, minute), tzinfo=tz)
            if candidate <= local_now:
                continue
            if any(
                abs((candidate - value).total_seconds()) < campaign["min_gap"]
                for value in day_values
            ):
                continue
            return candidate.astimezone(timezone.utc)
    raise ValueError("No AUTO schedule slot is available in the next 60 days")


async def _resolve_targets(session, user_id, values: list[str]):
    resolved = []
    for value in values:
        try:
            target_type, raw_id = value.split(":", 1)
            target_id = uuid.UUID(raw_id)
        except (ValueError, AttributeError):
            return [], f"Invalid target: {value}"
        model = {
            "page": FacebookPage,
            "group": FacebookGroup,
            "personal": FacebookAccount,
        }.get(target_type)
        if model is None:
            return [], f"Invalid target type: {target_type}"
        target = await session.get(model, target_id)
        if target is None or target.user_id != user_id:
            return [], f"Target not found: {value}"
        if target_type == "group" and target.status != "available":
            return [], f"Facebook group is unavailable: {value}"
        external = getattr(target, "group_id", None) or getattr(
            target, "page_id", None,
        ) or getattr(target, "uid", None) or str(target.id)
        resolved.append((target_type, target.id, str(external)))
    return resolved, None


async def enqueue_sheet_writeback(session, source: SheetSourceItem) -> None:
    existing = (await session.execute(
        select(SheetWritebackJob).where(
            SheetWritebackJob.source_item_id == source.id,
            SheetWritebackJob.source_version == source.source_version,
        )
    )).scalar_one_or_none()
    if existing:
        existing.status = "pending"
        existing.next_retry_at = None
        existing.error = None
    else:
        session.add(SheetWritebackJob(
            user_id=source.user_id,
            source_item_id=source.id,
            source_version=source.source_version,
            status="pending",
        ))


async def _save_campaign_error(get_session, campaign_id, error: str, now: datetime) -> None:
    async with get_session() as session:
        campaign = await session.get(SheetCampaign, campaign_id)
        if campaign:
            campaign.status = "error"
            campaign.last_error = error[:2000]
            campaign.last_sync_attempt_at = now
            await session.commit()


def _validate_candidate_shape(item: dict) -> str | None:
    if not item["external_id"]:
        return "external_id is required"
    if not item["content"] and not item["media_urls"]:
        return "content or media_urls is required"
    if not item["targets"]:
        return "at least one target is required"
    return None


def _content_hash(item: dict) -> str:
    return hashlib.sha256(json.dumps({
        key: item[key] for key in (
            "external_id", "content", "media_urls", "link", "targets",
            "mode", "publish_at", "priority",
        )
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _cell(row: list, index: int) -> str:
    return str(row[index]) if index < len(row) else ""


def _split_lines(value: str) -> list[str]:
    return [part.strip() for part in value.replace(",", "\n").splitlines() if part.strip()]


def _split_targets(value: str) -> list[str]:
    return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value or default)
    except ValueError:
        return default


async def run_sheet_sync(get_session, *, sheets_client=None) -> None:
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        campaigns = list((await session.execute(
            select(SheetCampaign).where(
                SheetCampaign.enabled == True,  # noqa: E712
                SheetCampaign.status != "paused",
            )
        )).scalars())
        intervals = {
            campaign.id: (
                (await session.get(GoogleSheetConnection, campaign.connection_id))
                .poll_interval_seconds
            )
            for campaign in campaigns
        }
    for campaign in campaigns:
        last = campaign.last_sync_attempt_at or campaign.last_synced_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        interval = intervals[campaign.id]
        if campaign.status == "error":
            interval = max(interval, 900)
        if last and (now - last).total_seconds() < interval:
            continue
        try:
            await sync_sheet_campaign(
                get_session,
                campaign.id,
                sheets_client=sheets_client,
                now=now,
            )
        except SheetSyncBusy:
            continue
        except SheetSyncError:
            continue
