"""NhatroVN room sync, upsert, matching, media preparation and Sheet mirror."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.crypto import decrypt
from app.models.sqlmodels import (
    FacebookGroup,
    PublicationJob,
    RentalConfig,
    RentalRoom,
    TaskItem,
    TaskItemStatus,
)
from app.services.nhatrovn_adapter import NhatrovnAdapter, Room
from app.services.publication_jobs import (
    ACTIVE_JOB_STATUSES,
    aggregate_rental_room,
    ensure_rental_publication_jobs,
)
from app.services.rental_group_match import match_group_ids, normalize_vn
from app.services.rental_media import RentalMediaError, RentalMediaStore
from app.services.rental_sheet_mirror import enqueue_rental_mirror

logger = logging.getLogger("flowmeta.rental_sync")
RENTED_STATUSES = {"da thue", "da cho thue"}


class RentalSyncError(Exception):
    """Safe integration failure returned by manual sync endpoints."""


class RentalSyncBusy(RentalSyncError):
    pass


def render_caption(template: str, room: Room, contact_phone: str) -> str:
    slug = "".join(w.capitalize() for w in normalize_vn(room.district or "").split()) or "khuvuc"
    try:
        return template.format(
            title=room.title,
            price=room.price,
            area_text=room.area_text,
            address=room.address,
            description=room.description,
            contact_phone=contact_phone,
            district=room.district or "",
            district_slug=slug,
        )
    except (AttributeError, IndexError, KeyError, ValueError):
        return f"{room.title}\n{room.price} {room.area_text}\n{room.address}\n{contact_phone}"


def is_rented_status(value: str | None) -> bool:
    return normalize_vn(value or "") in RENTED_STATUSES


class RentalSyncService:
    def __init__(
        self,
        get_session,
        adapter=None,
        media_store=None,
    ):
        self._get_session = get_session
        self._adapter = adapter or NhatrovnAdapter()
        self._media_store = media_store

    async def sync_config(self, config_id: uuid.UUID) -> dict:
        async with self._get_session() as session:
            cfg = (await session.execute(
                select(RentalConfig)
                .where(RentalConfig.id == config_id)
                .with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if cfg is None:
                raise RentalSyncError("Rental config not found")
            attempt_at = cfg.last_sync_attempt_at
            if attempt_at is not None and attempt_at.tzinfo is None:
                attempt_at = attempt_at.replace(tzinfo=timezone.utc)
            claim_now = datetime.now(timezone.utc)
            if (
                cfg.status == "syncing"
                and attempt_at
                and (claim_now - attempt_at).total_seconds() < 900
            ):
                raise RentalSyncBusy("Rental sync is already running")
            try:
                credentials = json.loads(decrypt(cfg.source_credentials_enc) or "{}")
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RentalSyncError("Stored NhatroVN credentials are invalid") from exc
            snapshot = {
                "user_id": cfg.user_id,
                "province_code": cfg.province_code,
                "district_code": cfg.district_code,
                "district_name": cfg.district_name,
                "ward_code": cfg.ward_code,
                "ward_name": cfg.ward_name,
                "caption_template": cfg.caption_template,
                "contact_phone": cfg.contact_phone,
                "post_delay_seconds": cfg.post_delay_seconds,
            }
            cfg.status = "syncing"
            cfg.last_sync_attempt_at = claim_now
            await session.commit()

        try:
            client = await self._adapter.login(
                str(credentials.get("username") or ""),
                str(credentials.get("password") or ""),
            )
            try:
                rooms = await self._adapter.fetch_rooms(
                    client,
                    province_code=snapshot["province_code"],
                    district_codes=[snapshot["district_code"]] if snapshot["district_code"] else None,
                    ward_codes=[snapshot["ward_code"]] if snapshot["ward_code"] else None,
                )
                media_by_external_id: dict[str, list[str]] = {}
                media_errors: dict[str, str] = {}
                media_store = self._media_store or RentalMediaStore(http_client=client)
                for source_room in rooms:
                    external_id = str(source_room.external_room_id or "").strip()
                    if (
                        not external_id
                        or not source_room.images
                        or is_rented_status(source_room.status)
                    ):
                        continue
                    try:
                        media_by_external_id[external_id] = await media_store.download(
                            user_id=snapshot["user_id"],
                            config_id=config_id,
                            external_room_id=external_id,
                            urls=source_room.images,
                        )
                    except RentalMediaError as exc:
                        media_errors[external_id] = str(exc)
            finally:
                aclose = getattr(client, "aclose", None)
                if aclose:
                    await aclose()
        except Exception as exc:
            await self._save_sync_error(config_id, str(exc))
            logger.warning("rental sync %s failed: %s", config_id, exc)
            raise RentalSyncError(str(exc) or "NhatroVN sync failed") from exc

        now = datetime.now(timezone.utc)
        async with self._get_session() as session:
            cfg = await session.get(RentalConfig, config_id)
            if cfg is None:
                raise RentalSyncError("Rental config was deleted during sync")
            groups = list((await session.execute(
                select(FacebookGroup).where(FacebookGroup.user_id == cfg.user_id)
            )).scalars())
            existing = {
                row.external_room_id: row
                for row in (await session.execute(
                    select(RentalRoom).where(RentalRoom.config_id == cfg.id)
                )).scalars()
            }

            added = matched = waiting = updated = rented = invalid = media_failed = 0
            mirror_queued = 0

            for source_room in rooms:
                external_id = str(source_room.external_room_id or "").strip()
                if not external_id:
                    invalid += 1
                    continue
                room_district = source_room.district or cfg.district_name
                caption_room = replace(source_room, district=room_district)
                row = existing.get(external_id)
                was_new = row is None
                if row is None:
                    row = RentalRoom(
                        config_id=cfg.id,
                        user_id=cfg.user_id,
                        external_room_id=external_id,
                        title="",
                    )
                    session.add(row)
                    await session.flush()
                    existing[external_id] = row
                    added += 1
                else:
                    updated += 1

                row.title = source_room.title
                row.price = source_room.price
                row.area_text = source_room.area_text
                row.address = source_room.address
                row.district = room_district
                row.ward = source_room.ward or cfg.ward_name
                row.description = source_room.description
                row.images_json = json.dumps(source_room.images, ensure_ascii=False)
                row.media_paths_json = json.dumps(
                    media_by_external_id.get(external_id, []),
                    ensure_ascii=False,
                )
                row.caption = render_caption(
                    cfg.caption_template, caption_room, cfg.contact_phone,
                )
                row.source_status = source_room.status or ""
                row.last_seen_at = now

                if is_rented_status(source_room.status):
                    await _cancel_unfinished_jobs(session, row, "Room is rented at source", now)
                    row.status = "rented"
                    row.error = None
                    rented += 1
                    if await enqueue_rental_mirror(
                        session, row, cfg.google_sheet_connection_id,
                    ):
                        mirror_queued += 1
                    continue

                if external_id in media_errors:
                    await _cancel_unfinished_jobs(
                        session, row, media_errors[external_id], now,
                    )
                    row.status = "media_error"
                    row.error = media_errors[external_id]
                    media_failed += 1
                    if await enqueue_rental_mirror(
                        session, row, cfg.google_sheet_connection_id,
                    ):
                        mirror_queued += 1
                    continue

                if was_new or not row.matched_group_ids_json:
                    gids = match_group_ids(room_district or "", groups)
                    row.matched_group_ids_json = json.dumps(gids) if gids else None
                else:
                    gids = [
                        str(value)
                        for value in json.loads(row.matched_group_ids_json or "[]")
                        if str(value)
                    ]

                if not gids:
                    row.status = "waiting_groups"
                    row.error = None
                    waiting += 1
                else:
                    jobs = list((await session.execute(
                        select(PublicationJob).where(
                            PublicationJob.rental_room_id == row.id
                        )
                    )).scalars())
                    if not jobs:
                        await ensure_rental_publication_jobs(
                            session,
                            row,
                            scheduled_at=now + timedelta(seconds=cfg.post_delay_seconds),
                        )
                        row.status = "new"
                    else:
                        await aggregate_rental_room(session, row.id, now)
                    matched += 1

                if await enqueue_rental_mirror(
                    session, row, cfg.google_sheet_connection_id,
                ):
                    mirror_queued += 1

            cfg.last_synced_at = now
            cfg.last_sync_attempt_at = now
            cfg.status = "active"
            cfg.last_error = None
            await session.commit()

        return {
            "added": added,
            "updated": updated,
            "matched": matched,
            "waiting": waiting,
            "rented": rented,
            "invalid": invalid,
            "media_failed": media_failed,
            "mirror_queued": mirror_queued,
        }

    async def _save_sync_error(self, config_id: uuid.UUID, error: str) -> None:
        async with self._get_session() as session:
            cfg = await session.get(RentalConfig, config_id)
            if cfg:
                cfg.status = "error"
                cfg.last_error = error[:2000]
                cfg.last_sync_attempt_at = datetime.now(timezone.utc)
                await session.commit()


async def _cancel_unfinished_jobs(
    session,
    room: RentalRoom,
    reason: str,
    now: datetime,
) -> None:
    jobs = list((await session.execute(
        select(PublicationJob).where(
            PublicationJob.rental_room_id == room.id,
            PublicationJob.status.in_(list(ACTIVE_JOB_STATUSES)),
        )
    )).scalars())
    for job in jobs:
        job.status = "canceled"
        job.error = reason
        job.finished_at = now
        job.next_retry_at = None
        if job.task_item_id:
            item = await session.get(TaskItem, job.task_item_id)
            if item and item.status in {TaskItemStatus.PENDING, TaskItemStatus.RUNNING}:
                item.status = TaskItemStatus.CANCELED
                item.error = reason


async def run_rental_sync(get_session=None, adapter=None) -> None:
    """Sync every due config, applying per-config error backoff."""
    if get_session is None:
        from app.db.postgres import session_context
        get_session = session_context
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        configs = list((await session.execute(
            select(RentalConfig).where(RentalConfig.status != "paused")
        )).scalars())
    service = RentalSyncService(get_session, adapter=adapter)
    for cfg in configs:
        last = cfg.last_sync_attempt_at or cfg.last_synced_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        interval = cfg.poll_interval_seconds
        if cfg.status == "error":
            interval = max(interval, 900)
        due = last is None or (now - last).total_seconds() >= interval
        if not due:
            continue
        try:
            await service.sync_config(cfg.id)
        except RentalSyncBusy:
            continue
        except RentalSyncError:
            logger.exception("rental sync failed for config %s", cfg.id)
