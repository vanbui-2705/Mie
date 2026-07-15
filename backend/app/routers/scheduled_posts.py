"""Scheduled auto-post endpoints."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status

from app.auth import current_user
from app.rbac import require_permission
from app.db.postgres import session_context
from app.models.sqlmodels import ScheduledPost, User
from app.services.scheduled_post_service import ScheduledPostNotFound, ScheduledPostService

router = APIRouter(tags=["scheduled-posts"])
UPLOAD_DIR = Path(os.environ.get("FLOWMETA_UPLOAD_DIR", "/app/uploads"))


@router.get("/api/scheduled-posts", response_model=list[dict])
async def list_scheduled_posts(user: User = Depends(require_permission("scheduled_post:read"))):
    service = ScheduledPostService(get_session=session_context)
    rows = await service.list_for_user(user.id)
    return [_scheduled_post_dict(row) for row in rows]


@router.post("/api/scheduled-posts", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_scheduled_post(request: Request, user: User = Depends(require_permission("scheduled_post:create"))):
    body, uploads, uploads_by_item = await _read_schedule_request(request)
    _validate_schedule_body(body, has_uploads=bool(uploads or uploads_by_item))
    service = ScheduledPostService(get_session=session_context)
    initial_items = _body_post_items(body)
    first = initial_items[0] if initial_items else {"message": str(body.get("message") or ""), "link": str(body.get("link") or ""), "media_paths": []}
    item = await service.create(
        user_id=user.id,
        name=str(body.get("name") or "Lịch đăng"),
        action="post_page",
        targets=_as_str_list(body.get("targets")),
        message=str(first.get("message") or ""),
        link=str(first.get("link") or "") or None,
        media_paths=[],
        max_threads=int(body.get("max_threads") or 3),
        start_at=_parse_dt(body.get("start_at")),
        interval_seconds=_parse_optional_int(body.get("interval_seconds")),
        stop_at=_parse_dt(body.get("stop_at")),
        post_items=initial_items,
    )
    if uploads or uploads_by_item:
        if uploads:
            uploads_by_item.setdefault(0, []).extend(uploads)
        post_items = initial_items or [{"message": str(body.get("message") or ""), "link": str(body.get("link") or ""), "media_paths": []}]
        for index, item_uploads in uploads_by_item.items():
            while len(post_items) <= index:
                post_items.append({"message": "", "link": "", "media_paths": []})
            saved = await _save_uploads(f"scheduled-{item.id}", item_uploads, prefix=f"item{index}_")
            post_items[index]["media_paths"] = [*post_items[index].get("media_paths", []), *saved]
        item = await service.set_post_items(item.id, user.id, post_items)
    return _scheduled_post_dict(item)


@router.put("/api/scheduled-posts/{sp_id}", response_model=dict)
async def update_scheduled_post(sp_id: str, request: Request, user: User = Depends(require_permission("scheduled_post:update"))):
    body, uploads, uploads_by_item = await _read_schedule_request(request)
    _validate_schedule_body(body, has_uploads=bool(uploads or uploads_by_item))
    service = ScheduledPostService(get_session=session_context)
    try:
        post_items = _body_post_items(body)
        if uploads:
            uploads_by_item.setdefault(0, []).extend(uploads)
        first = post_items[0] if post_items else {"message": str(body.get("message") or ""), "link": str(body.get("link") or ""), "media_paths": []}
        item = await service.update(
            sp_id=_uuid(sp_id),
            user_id=user.id,
        name=str(body.get("name") or "Lịch đăng"),
            targets=_as_str_list(body.get("targets")),
            message=str(first.get("message") or ""),
            link=str(first.get("link") or "") or None,
            max_threads=int(body.get("max_threads") or 3),
            start_at=_parse_dt(body.get("start_at")),
            interval_seconds=_parse_optional_int(body.get("interval_seconds")),
            stop_at=_parse_dt(body.get("stop_at")),
            post_items=post_items,
        )
        if uploads_by_item:
            if not post_items:
                post_items = [{"message": str(body.get("message") or ""), "link": str(body.get("link") or ""), "media_paths": []}]
            for index, item_uploads in uploads_by_item.items():
                while len(post_items) <= index:
                    post_items.append({"message": "", "link": "", "media_paths": []})
                saved = await _save_uploads(f"scheduled-{item.id}", item_uploads, prefix=f"item{index}_")
                post_items[index]["media_paths"] = [*post_items[index].get("media_paths", []), *saved]
            item = await service.set_post_items(item.id, user.id, post_items)
        return _scheduled_post_dict(item)
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found") from None


@router.post("/api/scheduled-posts/{sp_id}/pause", response_model=dict)
async def pause_scheduled_post(sp_id: str, user: User = Depends(require_permission("scheduled_post:update"))):
    return await _set_status(sp_id, user, "paused")


@router.post("/api/scheduled-posts/{sp_id}/resume", response_model=dict)
async def resume_scheduled_post(sp_id: str, user: User = Depends(require_permission("scheduled_post:update"))):
    return await _set_status(sp_id, user, "scheduled")


@router.post("/api/scheduled-posts/{sp_id}/fire-now", response_model=dict)
async def fire_scheduled_post_now(sp_id: str, user: User = Depends(require_permission("scheduled_post:update"))):
    service = ScheduledPostService(get_session=session_context)
    try:
        return await service.fire_now(_uuid(sp_id), user.id)
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found") from None


@router.delete("/api/scheduled-posts/{sp_id}", response_model=dict)
async def delete_scheduled_post(sp_id: str, user: User = Depends(require_permission("scheduled_post:delete"))):
    service = ScheduledPostService(get_session=session_context)
    try:
        await service.delete(_uuid(sp_id), user.id)
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found") from None
    return {"deleted": True}


async def _set_status(sp_id: str, user: User, value: str) -> dict:
    service = ScheduledPostService(get_session=session_context)
    try:
        item = await service.set_status(_uuid(sp_id), user.id, value)
        return _scheduled_post_dict(item)
    except ScheduledPostNotFound:
        raise HTTPException(status_code=404, detail="Scheduled post not found") from None


async def _read_schedule_request(request: Request) -> tuple[dict, list[UploadFile], dict[int, list[UploadFile]]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        body: dict = {
            "name": str(form.get("name") or ""),
            "message": str(form.get("message") or ""),
            "link": str(form.get("link") or ""),
            "max_threads": str(form.get("max_threads") or 3),
            "start_at": str(form.get("start_at") or ""),
            "interval_seconds": str(form.get("interval_seconds") or ""),
            "stop_at": str(form.get("stop_at") or ""),
        }
        targets_raw = form.get("targets")
        body["targets"] = _parse_json_list(str(targets_raw or "[]"))
        post_items_raw = form.get("post_items")
        body["post_items"] = _parse_json_items(str(post_items_raw or "[]"))
        uploads = [
            value for value in form.getlist("media_files")
            if getattr(value, "filename", None) and hasattr(value, "read")
        ]
        uploads_by_item: dict[int, list[UploadFile]] = {}
        for key, value in form.multi_items():
            if not key.startswith("media_files_"):
                continue
            if not getattr(value, "filename", None) or not hasattr(value, "read"):
                continue
            try:
                index = int(key.removeprefix("media_files_"))
            except ValueError:
                continue
            uploads_by_item.setdefault(index, []).append(value)
        return body, uploads, uploads_by_item  # type: ignore[return-value]
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}, [], {}


def _validate_schedule_body(body: dict, *, has_uploads: bool = False) -> None:
    targets = _as_str_list(body.get("targets"))
    message = str(body.get("message") or "")
    link = str(body.get("link") or "")
    post_items = _body_post_items(body)
    has_item_content = any(
        str(item.get("message") or "").strip() or str(item.get("link") or "").strip()
        for item in post_items
    )
    if not targets:
        raise HTTPException(status_code=400, detail="targets is required")
    if not message.strip() and not link.strip() and not has_item_content and not has_uploads:
        raise HTTPException(status_code=400, detail="message, link, or media is required")
    interval = _parse_optional_int(body.get("interval_seconds"))
    if interval is not None and interval < 60:
        raise HTTPException(status_code=400, detail="interval_seconds must be at least 60")


def _scheduled_post_dict(item: ScheduledPost) -> dict:
    targets = json.loads(item.targets_json or "[]")
    media_paths = json.loads(item.media_paths_json or "[]")
    post_items = _parse_post_items_for_response(item.post_items_json, item.message, item.link, media_paths)
    total_media = sum(len(post_item.get("media_paths", [])) for post_item in post_items)
    return {
        "id": str(item.id),
        "name": item.name,
        "action": item.action.value if hasattr(item.action, "value") else str(item.action),
        "targets": targets,
        "target_count": len(targets),
        "message": item.message or "",
        "link": item.link or "",
        "media_count": total_media,
        "post_count": len(post_items),
        "next_item_index": item.next_item_index,
        "post_items": [
            {
                "message": str(post_item.get("message") or ""),
                "link": str(post_item.get("link") or ""),
                "media_count": len(post_item.get("media_paths", [])),
            }
            for post_item in post_items
        ],
        "max_threads": item.max_threads,
        "start_at": item.start_at.isoformat() if item.start_at else None,
        "interval_seconds": item.interval_seconds,
        "next_fire_at": item.next_fire_at.isoformat() if item.next_fire_at else None,
        "last_fired_at": item.last_fired_at.isoformat() if item.last_fired_at else None,
        "stop_at": item.stop_at.isoformat() if item.stop_at else None,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


async def _save_uploads(run_id: str, uploads: list[UploadFile], *, prefix: str = "") -> list[str]:
    run_dir = UPLOAD_DIR / "page-posts" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for upload in uploads:
        filename = _safe_filename(upload.filename or "upload.bin")
        path = run_dir / f"{prefix}{uuid.uuid4().hex}_{filename}"
        with path.open("wb") as out_file:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                out_file.write(chunk)
        saved.append(str(path))
        await upload.close()
    return saved


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.replace("\\", "_").replace("/", "_")
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:180] or "upload.bin"


def _parse_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in value.split(",")]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item)]
    return []


def _parse_json_items(value: str) -> list[dict]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    items: list[dict] = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        media = raw.get("media_paths") or []
        if not isinstance(media, list):
            media = []
        item = {
            "message": str(raw.get("message") or ""),
            "link": str(raw.get("link") or ""),
            "media_paths": [str(path) for path in media if str(path)],
        }
        if item["message"].strip() or item["link"].strip() or item["media_paths"]:
            items.append(item)
    return items


def _body_post_items(body: dict) -> list[dict]:
    raw = body.get("post_items")
    if isinstance(raw, str):
        return _parse_json_items(raw)
    if isinstance(raw, list):
        return _parse_json_items(json.dumps(raw))
    return []


def _parse_post_items_for_response(
    raw_json: str | None,
    message: str | None,
    link: str | None,
    media_paths: list[str],
) -> list[dict]:
    if raw_json:
        parsed = _parse_json_items(raw_json)
        if parsed:
            return parsed
    fallback = {
        "message": message or "",
        "link": link or "",
        "media_paths": media_paths,
    }
    return [fallback] if fallback["message"].strip() or fallback["link"].strip() or fallback["media_paths"] else []


def _as_str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return _parse_json_list(value)
    return []


def _parse_dt(value) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {raw}") from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_optional_int(value) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid integer: {raw}") from None


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id") from None
