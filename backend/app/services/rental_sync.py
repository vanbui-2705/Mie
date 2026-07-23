"""Sync service: pull rooms from a rental source (nhatrovn), dedup against
already-known RentalRoom rows, match Facebook groups by district, render the
post caption, and best-effort mirror new rows to a linked Google Sheet."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.crypto import decrypt
from app.models.sqlmodels import RentalConfig, RentalRoom, FacebookGroup, GoogleSheetConnection
from app.services.nhatrovn_adapter import NhatrovnAdapter, Room
from app.services.rental_group_match import match_group_ids, normalize_vn

logger = logging.getLogger("flowmeta.rental_sync")

RENTED_STATUS = "Đã thuê"


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
    except (KeyError, IndexError, ValueError):
        # Bad/unknown placeholder in a user-supplied template: fall back, never crash sync.
        return f"{room.title}\n{room.price} {room.area_text}\n{room.address}\n{contact_phone}"


class RentalSyncService:
    def __init__(self, get_session, adapter=None, sheets_client=None):
        self._get_session = get_session
        self._adapter = adapter or NhatrovnAdapter()
        self._sheets_client = sheets_client

    def _sheets(self):
        if self._sheets_client is not None:
            return self._sheets_client
        from app.services.google_sheets import GoogleSheetsClient
        return GoogleSheetsClient()

    async def sync_config(self, config_id: uuid.UUID) -> dict:
        async with self._get_session() as session:
            cfg = await session.get(RentalConfig, config_id)
            if cfg is None:
                return {"added": 0, "matched": 0, "waiting": 0}
            creds = json.loads(decrypt(cfg.source_credentials_enc) or "{}")
            groups = list(
                (await session.execute(
                    select(FacebookGroup).where(FacebookGroup.user_id == cfg.user_id)
                )).scalars()
            )
            existing = set(
                (await session.execute(
                    select(RentalRoom.external_room_id).where(RentalRoom.config_id == cfg.id)
                )).scalars()
            )
            user_id = cfg.user_id
            province_code = cfg.province_code
            district_code = cfg.district_code
            district_name = cfg.district_name
            ward_code = cfg.ward_code
            ward_name = cfg.ward_name
            caption_template = cfg.caption_template
            contact_phone = cfg.contact_phone
            sheet_conn_id = cfg.google_sheet_connection_id

        try:
            client = await self._adapter.login(creds.get("username", ""), creds.get("password", ""))
            try:
                rooms = await self._adapter.fetch_rooms(
                    client,
                    province_code=province_code,
                    district_codes=[district_code] if district_code else None,
                    ward_codes=[ward_code] if ward_code else None,
                )
            finally:
                aclose = getattr(client, "aclose", None)
                if aclose:
                    await aclose()
        except Exception as exc:
            async with self._get_session() as session:
                c = await session.get(RentalConfig, config_id)
                if c:
                    c.status = "error"
                    c.last_error = str(exc)
                    await session.commit()
            logger.warning("rental sync %s failed: %s", config_id, exc)
            return {"added": 0, "matched": 0, "waiting": 0}

        async with self._get_session() as session:
            cfg = await session.get(RentalConfig, config_id)
            added = matched = waiting = 0
            mirror_rows: list[list[str]] = []

            for room in rooms:
                if (room.status or "").strip() == RENTED_STATUS:
                    continue
                if room.external_room_id in existing:
                    continue

                room_district = room.district or district_name
                gids = match_group_ids(room_district or "", groups)
                status = "new" if gids else "waiting_groups"

                session.add(RentalRoom(
                    config_id=cfg.id,
                    user_id=cfg.user_id,
                    external_room_id=room.external_room_id,
                    title=room.title,
                    price=room.price,
                    area_text=room.area_text,
                    address=room.address,
                    district=room_district,
                    ward=room.ward or ward_name,
                    description=room.description,
                    images_json=json.dumps(room.images),
                    caption=render_caption(caption_template, room, contact_phone),
                    matched_group_ids_json=json.dumps(gids) if gids else None,
                    status=status,
                ))
                existing.add(room.external_room_id)

                added += 1
                if gids:
                    matched += 1
                else:
                    waiting += 1
                mirror_rows.append([
                    room.external_room_id, room.title, room.price, room.area_text,
                    room.address, status,
                ])

            cfg.last_synced_at = datetime.now(timezone.utc)
            cfg.status = "active"
            cfg.last_error = None
            await session.commit()

            if sheet_conn_id and mirror_rows:
                try:
                    conn = await session.get(GoogleSheetConnection, sheet_conn_id)
                    if conn:
                        creds2 = json.loads(decrypt(conn.credentials_enc) or "{}")
                        await self._sheets().append_rows(
                            credentials=creds2,
                            spreadsheet_id=conn.spreadsheet_id,
                            sheet_name=conn.sheet_name,
                            rows=mirror_rows,
                        )
                except Exception as exc:
                    logger.warning("rental sheet mirror %s failed: %s", config_id, exc)

        return {"added": added, "matched": matched, "waiting": waiting}
