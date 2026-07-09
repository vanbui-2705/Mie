"""Page post and share/repost task endpoints."""
from __future__ import annotations

import uuid
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.crypto import decrypt, encrypt
from app.db.postgres import get_session, session_context
from app.event_bus import event_bus
from app.models.sqlmodels import CommentAction, ExternalPage, FacebookAccount, FacebookGroup, FacebookPage, ShareCampaign, ShareMode, ShareTarget, SourcePost, TaskItem, TaskItemStatus, TaskLog, TaskRun, TaskRunStatus, User
from app.services.browser_profiles import profile_path
from app.services.extension_queue import enqueue_extension_job, is_extension_online
from app.services.facebook_graph import get_my_pages, post_page_feed, post_page_media
from app.services.personal_browser import check_target_access
from app.services.task_queue import enqueue_browser_job

router = APIRouter(tags=["page-tasks"])
UPLOAD_DIR = Path(os.environ.get("FLOWMETA_UPLOAD_DIR", "/app/uploads"))
EXTENSION_JOB_STALE_SECONDS = int(os.environ.get("FLOWMETA_EXTENSION_JOB_STALE_SECONDS", "180"))


@router.get("/api/post-targets", response_model=list[dict])
async def list_post_targets(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return all destinations from the old poster model: personal profile + fanpages."""
    account_result = await session.execute(
        select(FacebookAccount)
        .where(FacebookAccount.user_id == user.id)
        .order_by(FacebookAccount.created_at.desc())
    )
    page_result = await session.execute(
        select(FacebookPage)
        .where(FacebookPage.user_id == user.id)
        .order_by(FacebookPage.page_name)
    )
    group_result = await session.execute(
        select(FacebookGroup)
        .where(FacebookGroup.user_id == user.id)
        .order_by(FacebookGroup.group_name, FacebookGroup.group_url)
    )
    targets: list[dict] = []
    for account in account_result.scalars().all():
        extension_online = await is_extension_online(str(account.id))
        available = extension_online or account.browser_status == "logged_in"
        targets.append({
            "id": f"personal:{account.id}",
            "type": "personal",
            "account_id": str(account.id),
            "uid": account.uid,
            "name": f"Trang cá nhân ({account.name or account.uid})",
            "status": "extension_online" if extension_online else account.browser_status,
            "available": available,
            "reason": "" if available else (account.browser_last_error or "Đăng trang cá nhân cần browser profile Playwright đã đăng nhập. Graph token không đăng được lên profile cá nhân."),
        })
    for page in page_result.scalars().all():
        targets.append({
            "id": f"page:{page.id}",
            "type": "page",
            "page_id": page.page_id,
            "facebook_page_id": str(page.id),
            "facebook_account_id": str(page.facebook_account_id),
            "name": page.page_name,
            "category": page.category or "",
            "status": page.status,
            "available": True,
            "reason": "",
        })
    for group in group_result.scalars().all():
        extension_online = await is_extension_online(str(group.facebook_account_id))
        available = group.status == "available" and extension_online
        targets.append({
            "id": f"group:{group.id}",
            "type": "group",
            "group_id": group.group_id or "",
            "facebook_group_id": str(group.id),
            "facebook_account_id": str(group.facebook_account_id),
            "name": group.group_name or group.group_url,
            "url": group.group_url,
            "status": "extension_online" if available else group.status,
            "available": available,
            "reason": "" if available else (group.last_error or "Group chua duoc check bang browser profile."),
        })
    return targets


@router.get("/api/share-targets", response_model=list[dict])
async def list_share_targets(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    pages = (await session.execute(
        select(FacebookPage).where(FacebookPage.user_id == user.id).order_by(FacebookPage.page_name)
    )).scalars().all()
    groups = (await session.execute(
        select(FacebookGroup).where(FacebookGroup.user_id == user.id).order_by(FacebookGroup.group_name, FacebookGroup.group_url)
    )).scalars().all()
    external_pages = (await session.execute(
        select(ExternalPage).where(ExternalPage.user_id == user.id).order_by(ExternalPage.page_name, ExternalPage.page_url)
    )).scalars().all()
    targets: list[dict] = []
    for page in pages:
        targets.append({
            "id": f"page:{page.id}",
            "type": "page",
            "name": page.page_name,
            "url": f"https://www.facebook.com/{page.page_id}",
            "status": page.status,
            "available": True,
            "reason": "",
        })
    for group in groups:
        extension_online = await is_extension_online(str(group.facebook_account_id))
        available = group.status == "available" and extension_online
        targets.append({
            "id": f"group:{group.id}",
            "type": "group",
            "name": group.group_name or group.group_url,
            "url": group.group_url,
            "status": "extension_online" if available else group.status,
            "available": available,
            "reason": "" if available else (group.last_error or "Can check/login browser truoc khi share vao group."),
        })
    for page in external_pages:
        extension_online = await is_extension_online(str(page.facebook_account_id))
        available = page.status == "available" and extension_online
        targets.append({
            "id": f"external_page:{page.id}",
            "type": "external_page",
            "name": page.page_name or page.page_url,
            "url": page.page_url,
            "status": "extension_online" if available else page.status,
            "available": available,
            "reason": "" if available else (page.last_error or "Can check/login browser truoc khi share sang page nay."),
        })
    return targets


@router.post("/api/facebook-groups/import", response_model=dict)
async def import_facebook_groups(
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_user_account(session, user.id, str(body.get("facebook_account_id") or ""))
    urls = _parse_raw_lines(str(body.get("raw_text") or body.get("text") or ""))
    created = 0
    updated = 0
    for url in urls:
        normalized = _normalize_facebook_url(url)
        result = await session.execute(
            select(FacebookGroup).where(
                FacebookGroup.user_id == user.id,
                FacebookGroup.facebook_account_id == account.id,
                FacebookGroup.group_url == normalized,
            )
        )
        group = result.scalar_one_or_none()
        if group is None:
            session.add(FacebookGroup(user_id=user.id, facebook_account_id=account.id, group_url=normalized))
            created += 1
        else:
            group.status = "not_checked"
            group.last_error = None
            updated += 1
    await session.commit()
    return {"created": created, "updated": updated, "total": created + updated}


@router.get("/api/facebook-groups", response_model=list[dict])
async def list_facebook_groups(
    account_id: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(FacebookGroup).where(FacebookGroup.user_id == user.id)
    if account_id:
        stmt = stmt.where(FacebookGroup.facebook_account_id == _uuid(account_id))
    groups = (await session.execute(stmt.order_by(FacebookGroup.created_at.desc()))).scalars().all()
    return [_group_dict(group) for group in groups]


@router.post("/api/facebook-groups/{group_id}/check", response_model=dict)
async def check_facebook_group(
    group_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    group = await _get_user_group(session, user.id, group_id)
    account = await session.get(FacebookAccount, group.facebook_account_id)
    result = await _check_browser_target(str(user.id), str(group.facebook_account_id), group.group_url, "group")
    group.status = str(result.get("status") or ("available" if result.get("success") else "error"))
    group.last_error = "" if result.get("success") else str(result.get("message") or "")
    group.group_name = str(result.get("title") or group.group_name or "") or None
    if account and not result.get("success") and "login" in str(result.get("message", "")).lower():
        account.browser_status = "expired"
        account.browser_last_error = group.last_error
        account.browser_last_checked_at = datetime.now(timezone.utc)
    await session.commit()
    return _group_dict(group)


@router.delete("/api/facebook-groups/{group_id}", response_model=dict)
async def delete_facebook_group(
    group_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    group = await _get_user_group(session, user.id, group_id)
    await session.delete(group)
    await session.commit()
    return {"deleted": True}


@router.post("/api/external-pages/import", response_model=dict)
async def import_external_pages(
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    account = await _get_user_account(session, user.id, str(body.get("facebook_account_id") or ""))
    urls = _parse_raw_lines(str(body.get("raw_text") or body.get("text") or ""))
    created = 0
    updated = 0
    for url in urls:
        normalized = _normalize_facebook_url(url)
        result = await session.execute(
            select(ExternalPage).where(
                ExternalPage.user_id == user.id,
                ExternalPage.facebook_account_id == account.id,
                ExternalPage.page_url == normalized,
            )
        )
        page = result.scalar_one_or_none()
        if page is None:
            session.add(ExternalPage(user_id=user.id, facebook_account_id=account.id, page_url=normalized))
            created += 1
        else:
            page.status = "not_checked"
            page.last_error = None
            updated += 1
    await session.commit()
    return {"created": created, "updated": updated, "total": created + updated}


@router.get("/api/external-pages", response_model=list[dict])
async def list_external_pages(
    account_id: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(ExternalPage).where(ExternalPage.user_id == user.id)
    if account_id:
        stmt = stmt.where(ExternalPage.facebook_account_id == _uuid(account_id))
    pages = (await session.execute(stmt.order_by(ExternalPage.created_at.desc()))).scalars().all()
    return [_external_page_dict(page) for page in pages]


@router.post("/api/external-pages/{page_id}/check", response_model=dict)
async def check_external_page(
    page_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    page = await _get_user_external_page(session, user.id, page_id)
    account = await session.get(FacebookAccount, page.facebook_account_id)
    result = await _check_browser_target(str(user.id), str(page.facebook_account_id), page.page_url, "external_page")
    page.status = str(result.get("status") or ("available" if result.get("success") else "error"))
    page.last_error = "" if result.get("success") else str(result.get("message") or "")
    page.page_name = str(result.get("title") or page.page_name or "") or None
    if account and not result.get("success") and "login" in str(result.get("message", "")).lower():
        account.browser_status = "expired"
        account.browser_last_error = page.last_error
        account.browser_last_checked_at = datetime.now(timezone.utc)
    await session.commit()
    return _external_page_dict(page)


@router.delete("/api/external-pages/{page_id}", response_model=dict)
async def delete_external_page(
    page_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    page = await _get_user_external_page(session, user.id, page_id)
    await session.delete(page)
    await session.commit()
    return {"deleted": True}


@router.post("/api/page-post-tasks", response_model=dict)
async def create_page_post_task(
    request: Request,
    background: BackgroundTasks = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    body, uploads = await _read_page_post_request(request)
    await _fail_old_user_browser_runs(session, user.id)
    parsed_targets = _parse_post_targets(body)
    message = str(body.get("message") or "")
    link = str(body.get("link") or "") or None
    if not message.strip() and not (link or "").strip() and not uploads:
        raise HTTPException(status_code=400, detail="message, link, or media_files is required")
    pages = await _load_user_pages(session, user.id, parsed_targets["page_ids"])
    groups = await _load_user_groups(session, user.id, parsed_targets["group_ids"])
    personal_accounts = await _load_user_accounts(session, user.id, parsed_targets["personal_account_ids"])
    total = len(pages) + len(groups) + len(personal_accounts)
    if total == 0:
        raise HTTPException(status_code=400, detail="targets is required")
    run = TaskRun(
        user_id=user.id,
        status=TaskRunStatus.RUNNING,
        action=CommentAction.POST_PAGE,
        max_threads=max(1, int(body.get("max_threads") or 3)),
        text_input_enc=None,
        image_path=None,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    media_paths = await _save_uploads(str(run.id), uploads)
    if background is not None:
        background.add_task(
            _run_page_post_task,
            str(run.id),
            [str(p.id) for p in pages],
            [str(g.id) for g in groups],
            [str(a.id) for a in personal_accounts],
            message,
            link,
            media_paths,
        )
    return {"task_id": str(run.id), "total": total, "status": "queued"}


@router.get("/api/uploads/page-posts/{run_id}/{filename}", response_class=FileResponse)
async def get_page_post_upload(run_id: str, filename: str):
    if not _is_safe_upload_part(run_id) or not _is_safe_upload_part(filename):
        raise HTTPException(status_code=400, detail="Invalid upload path")
    path = (UPLOAD_DIR / "page-posts" / run_id / filename).resolve()
    root = (UPLOAD_DIR / "page-posts").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Upload not found")
    return FileResponse(path)


@router.get("/api/page-post-tasks/{task_id}", response_model=dict)
async def get_page_post_task(task_id: str, session: AsyncSession = Depends(get_session)):
    return await _task_summary(session, task_id)


@router.post("/api/share-campaigns", response_model=dict)
async def create_share_campaign(
    body: dict = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    mode = ShareMode(str(body.get("mode") or ShareMode.SHARE_LINK.value))
    source_url = str(body.get("source_post_url") or "")
    if not source_url:
        raise HTTPException(status_code=400, detail="source_post_url is required")
    parsed_targets = _parse_share_targets(body)
    pages = await _load_user_pages(session, user.id, parsed_targets["page_ids"])
    groups = await _load_user_groups(session, user.id, parsed_targets["group_ids"])
    external_pages = await _load_user_external_pages(session, user.id, parsed_targets["external_page_ids"])
    if not pages and not groups and not external_pages:
        raise HTTPException(status_code=400, detail="targets is required")
    source = SourcePost(
        user_id=user.id,
        source_type=str(body.get("source_type") or "public_url"),
        source_post_url=source_url,
        source_post_id=str(body.get("source_post_id") or "") or None,
        message_snapshot=str(body.get("message_snapshot") or "") or None,
    )
    session.add(source)
    await session.flush()
    campaign = ShareCampaign(
        user_id=user.id,
        source_post_id=source.id,
        name=str(body.get("name") or "Share campaign"),
        mode=mode,
        custom_message=str(body.get("custom_message") or "") or None,
    )
    session.add(campaign)
    await session.flush()
    for page in pages:
        session.add(ShareTarget(
            campaign_id=campaign.id,
            user_id=user.id,
            target_type="page",
            facebook_page_id=page.id,
            facebook_account_id=page.facebook_account_id,
        ))
    for group in groups:
        session.add(ShareTarget(
            campaign_id=campaign.id,
            user_id=user.id,
            target_type="group",
            facebook_group_id=group.id,
            facebook_account_id=group.facebook_account_id,
        ))
    for page in external_pages:
        session.add(ShareTarget(
            campaign_id=campaign.id,
            user_id=user.id,
            target_type="external_page",
            external_page_id=page.id,
            facebook_account_id=page.facebook_account_id,
        ))
    await session.commit()
    return {"id": str(campaign.id), "targets": len(pages) + len(groups) + len(external_pages), "status": campaign.status}


@router.post("/api/share-campaigns/{campaign_id}/start", response_model=dict)
async def start_share_campaign(
    campaign_id: str,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    campaign_uuid = _uuid(campaign_id)
    campaign = await session.get(ShareCampaign, campaign_uuid)
    if campaign is None or campaign.user_id != user.id:
        raise HTTPException(status_code=404, detail="Share campaign not found")
    source = await session.get(SourcePost, campaign.source_post_id) if campaign.source_post_id else None
    target_result = await session.execute(
        select(ShareTarget).where(ShareTarget.campaign_id == campaign.id)
    )
    targets = target_result.scalars().all()
    run = TaskRun(
        user_id=user.id,
        status=TaskRunStatus.RUNNING,
        action=CommentAction.SHARE_PAGE,
        max_threads=3,
        text_input_enc=None,
        image_path=None,
    )
    campaign.status = "running"
    session.add(run)
    await session.commit()
    await session.refresh(run)
    message = campaign.custom_message or (source.message_snapshot if source else "") or ""
    source_url = source.source_post_url if source else ""
    background.add_task(
        _run_share_task,
        str(run.id),
        [str(t.id) for t in targets],
        message or "",
        source_url,
    )
    return {"task_id": str(run.id), "campaign_id": campaign_id, "targets": len(targets), "status": "queued"}


@router.get("/api/share-campaigns/{campaign_id}", response_model=dict)
async def get_share_campaign(
    campaign_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    campaign = await session.get(ShareCampaign, _uuid(campaign_id))
    if campaign is None or campaign.user_id != user.id:
        raise HTTPException(status_code=404, detail="Share campaign not found")
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "mode": campaign.mode.value,
        "status": campaign.status,
        "created_at": campaign.created_at,
    }


async def _run_page_post_task(
    run_id: str,
    page_ids: list[str],
    group_ids: list[str],
    personal_account_ids: list[str],
    message: str,
    link: str | None,
    media_paths: list[str],
) -> None:
    try:
        failures = 0
        async with session_context() as session:
            index = 0
            queued_browser = 0
            pages = [await session.get(FacebookPage, _uuid(page_id)) for page_id in page_ids]
            for page in [p for p in pages if p is not None]:
                index += 1
                item = TaskItem(
                    run_id=_uuid(run_id),
                    user_id=page.user_id,
                    item_index=index,
                    uid=page.page_id,
                    target_link=page.page_id,
                    action="post_page",
                    status=TaskItemStatus.RUNNING,
                )
                session.add(item)
                await session.flush()
                token = decrypt(page.page_access_token_enc)
                result = await post_page_media(page.page_id, token, message, media_paths, link) if media_paths else await post_page_feed(page.page_id, token, message, link)
                if not result.get("success") and _is_token_expired_error(str(result.get("message") or "")):
                    refresh = await _refresh_page_token(session, page)
                    if refresh.get("success"):
                        token = decrypt(page.page_access_token_enc)
                        result = await post_page_media(page.page_id, token, message, media_paths, link) if media_paths else await post_page_feed(page.page_id, token, message, link)
                    else:
                        result["message"] = f"Page token expired; refresh page token failed: {refresh.get('message') or 'unknown error'}"
                if not result.get("success"):
                    failures += 1
                item.status = TaskItemStatus.SUCCESS if result.get("success") else TaskItemStatus.FAILED
                item.error = "" if result.get("success") else str(result.get("message") or "")
                item.output_link = str(result.get("post_url") or "") or None
                await _log(session, run_id, index, page.page_id, "post_page", result)

            groups = [await session.get(FacebookGroup, _uuid(group_id)) for group_id in group_ids]
            for group in [g for g in groups if g is not None]:
                index += 1
                item = TaskItem(
                    run_id=_uuid(run_id),
                    user_id=group.user_id,
                    item_index=index,
                    uid=str(group.facebook_account_id),
                    target_link=group.group_url,
                    action="post_group",
                    status=TaskItemStatus.PENDING,
                )
                session.add(item)
                await session.flush()
                if group.status != "available":
                    failures += 1
                    item.status = TaskItemStatus.FAILED
                    item.error = group.last_error or "Group chua available. Hay check target bang browser truoc."
                    await _log(session, run_id, index, group.group_url, "post_group", {"success": False, "message": item.error})
                    continue
                queued_browser += 1
                await session.commit()
                payload = {
                    "type": "group_post",
                    "run_id": run_id,
                    "task_item_id": item.id,
                    "log_index": index,
                    "browser_job_index": queued_browser,
                    "user_id": str(group.user_id),
                    "account_id": str(group.facebook_account_id),
                    "uid": str(group.facebook_account_id),
                    "target_url": group.group_url,
                    "message": message,
                    "link": link or "",
                    "media_paths": media_paths,
                    "media_urls": _media_urls(media_paths),
                    "action": "post_group",
                }
                if await is_extension_online(str(group.facebook_account_id)):
                    await enqueue_extension_job(str(group.facebook_account_id), payload)
                else:
                    await enqueue_browser_job(payload)

            accounts = [await session.get(FacebookAccount, _uuid(account_id)) for account_id in personal_account_ids]
            for account in [a for a in accounts if a is not None]:
                index += 1
                item = TaskItem(
                    run_id=_uuid(run_id),
                    user_id=account.user_id,
                    item_index=index,
                    uid=account.uid,
                    target_link=account.uid,
                    action="post_personal",
                    status=TaskItemStatus.PENDING,
                )
                session.add(item)
                await session.flush()
                extension_online = await is_extension_online(str(account.id))
                if not extension_online and account.browser_status != "logged_in":
                    failures += 1
                    item.status = TaskItemStatus.FAILED
                    item.error = account.browser_last_error or "Browser profile chua logged_in. Hay login browser truoc."
                    result = {
                        "success": False,
                        "message": item.error,
                    }
                    await _log(session, run_id, index, account.uid, "post_personal", result)
                    continue
                queued_browser += 1
                await session.commit()
                payload = {
                    "type": "personal_post",
                    "run_id": run_id,
                    "task_item_id": item.id,
                    "log_index": index,
                    "browser_job_index": queued_browser,
                    "user_id": str(account.user_id),
                    "account_id": str(account.id),
                    "uid": account.uid,
                    "message": message,
                    "link": link or "",
                    "media_paths": media_paths,
                    "media_urls": _media_urls(media_paths),
                    "target_url": "https://www.facebook.com/me",
                    "action": "post_personal",
                }
                if extension_online:
                    await enqueue_extension_job(str(account.id), payload)
                else:
                    await enqueue_browser_job(payload)
            if queued_browser == 0:
                await _finish(session, run_id, failed=failures > 0)
    except Exception as exc:
        await _fail(run_id, str(exc))


async def _run_share_task(run_id: str, share_target_ids: list[str], message: str, source_url: str) -> None:
    final_message = f"{message}\n\n{source_url}".strip()
    try:
        async with session_context() as session:
            failures = 0
            queued_browser = 0
            for idx, target_id in enumerate(share_target_ids, start=1):
                target = await session.get(ShareTarget, _uuid(target_id))
                if target is None:
                    continue
                if target.target_type == "page" and target.facebook_page_id:
                    page = await session.get(FacebookPage, target.facebook_page_id)
                    if page is None:
                        continue
                    item = TaskItem(
                        run_id=_uuid(run_id),
                        user_id=page.user_id,
                        item_index=idx,
                        uid=page.page_id,
                        target_link=page.page_id,
                        action="share_page",
                        status=TaskItemStatus.RUNNING,
                    )
                    session.add(item)
                    await session.flush()
                    token = decrypt(page.page_access_token_enc)
                    result = await post_page_feed(page.page_id, token, final_message, source_url)
                    if not result.get("success") and _is_token_expired_error(str(result.get("message") or "")):
                        refresh = await _refresh_page_token(session, page)
                        if refresh.get("success"):
                            token = decrypt(page.page_access_token_enc)
                            result = await post_page_feed(page.page_id, token, final_message, source_url)
                        else:
                            result["message"] = f"Page token expired; refresh page token failed: {refresh.get('message') or 'unknown error'}"
                    success = bool(result.get("success"))
                    failures += 0 if success else 1
                    item.status = TaskItemStatus.SUCCESS if success else TaskItemStatus.FAILED
                    item.error = "" if success else str(result.get("message") or "")
                    item.output_link = str(result.get("post_url") or "") or None
                    if not success and _is_token_expired_error(item.error):
                        page.status = "token_expired"
                    target.status = "success" if success else "failed"
                    target.output_post_id = item.output_link
                    target.error = item.error
                    await _log(session, run_id, idx, page.page_id, "share_page", result)
                    continue

                browser_target = await _resolve_browser_share_target(session, target)
                if browser_target is None:
                    failures += 1
                    continue
                item = TaskItem(
                    run_id=_uuid(run_id),
                    user_id=target.user_id,
                    item_index=idx,
                    uid=str(browser_target["account_id"]),
                    target_link=str(browser_target["target_url"]),
                    action=str(browser_target["action"]),
                    status=TaskItemStatus.PENDING,
                )
                session.add(item)
                await session.flush()
                if browser_target["status"] != "available":
                    failures += 1
                    item.status = TaskItemStatus.FAILED
                    item.error = str(browser_target["error"] or "Target chua available. Hay check target bang browser truoc.")
                    target.status = "failed"
                    target.error = item.error
                    await _log(session, run_id, idx, str(browser_target["target_url"]), str(browser_target["action"]), {"success": False, "message": item.error})
                    continue
                queued_browser += 1
                await session.commit()
                payload = {
                    "type": str(browser_target["job_type"]),
                    "run_id": run_id,
                    "task_item_id": item.id,
                    "share_target_id": str(target.id),
                    "log_index": idx,
                    "browser_job_index": queued_browser,
                    "user_id": str(target.user_id),
                    "account_id": str(browser_target["account_id"]),
                    "uid": str(browser_target["account_id"]),
                    "target_url": str(browser_target["target_url"]),
                    "source_url": source_url,
                    "message": message,
                    "action": str(browser_target["action"]),
                }
                if await is_extension_online(str(browser_target["account_id"])):
                    await enqueue_extension_job(str(browser_target["account_id"]), payload)
                else:
                    await enqueue_browser_job(payload)
            if queued_browser == 0:
                await _finish(session, run_id, failed=failures > 0)
    except Exception as exc:
        await _fail(run_id, str(exc))


async def _load_user_pages(session: AsyncSession, user_id: uuid.UUID, page_ids: list[str]) -> list[FacebookPage]:
    if not page_ids:
        return []
    ids = [_uuid(page_id) for page_id in page_ids]
    result = await session.execute(
        select(FacebookPage).where(FacebookPage.user_id == user_id, FacebookPage.id.in_(ids))
    )
    pages = result.scalars().all()
    if len(pages) != len(ids):
        raise HTTPException(status_code=400, detail="One or more pages are not available for this user")
    return pages


async def _load_user_groups(session: AsyncSession, user_id: uuid.UUID, group_ids: list[str]) -> list[FacebookGroup]:
    if not group_ids:
        return []
    ids = [_uuid(group_id) for group_id in group_ids]
    result = await session.execute(
        select(FacebookGroup).where(FacebookGroup.user_id == user_id, FacebookGroup.id.in_(ids))
    )
    groups = result.scalars().all()
    if len(groups) != len(ids):
        raise HTTPException(status_code=400, detail="One or more groups are not available for this user")
    return groups


async def _load_user_external_pages(session: AsyncSession, user_id: uuid.UUID, page_ids: list[str]) -> list[ExternalPage]:
    if not page_ids:
        return []
    ids = [_uuid(page_id) for page_id in page_ids]
    result = await session.execute(
        select(ExternalPage).where(ExternalPage.user_id == user_id, ExternalPage.id.in_(ids))
    )
    pages = result.scalars().all()
    if len(pages) != len(ids):
        raise HTTPException(status_code=400, detail="One or more external pages are not available for this user")
    return pages


async def _read_page_post_request(request: Request) -> tuple[dict, list[UploadFile]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        body: dict = {
            "message": str(form.get("message") or ""),
            "link": str(form.get("link") or ""),
            "max_threads": str(form.get("max_threads") or 3),
        }
        targets_raw = form.get("targets")
        if targets_raw:
            body["targets"] = _parse_json_list(str(targets_raw))
        page_ids_raw = form.get("page_ids")
        if page_ids_raw:
            body["page_ids"] = _parse_json_list(str(page_ids_raw))
        uploads = [
            value for value in form.getlist("media_files")
            if getattr(value, "filename", None) and hasattr(value, "read")
        ]
        return body, uploads  # type: ignore[return-value]

    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}, []


async def _save_uploads(run_id: str, uploads: list[UploadFile]) -> list[str]:
    if not uploads:
        return []
    run_dir = UPLOAD_DIR / "page-posts" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for upload in uploads:
        filename = _safe_filename(upload.filename or "upload.bin")
        path = run_dir / f"{uuid.uuid4().hex}_{filename}"
        with path.open("wb") as out_file:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                out_file.write(chunk)
        saved.append(str(path))
        await upload.close()
    return saved


def _media_urls(paths: list[str]) -> list[str]:
    urls: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        run_id = path.parent.name
        filename = path.name
        if _is_safe_upload_part(run_id) and _is_safe_upload_part(filename):
            urls.append(f"/api/uploads/page-posts/{run_id}/{filename}")
    return urls


def _is_safe_upload_part(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    return all(ch.isalnum() or ch in "._-" for ch in value)


def _parse_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in value.split(",")]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item)]
    return []


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.replace("\\", "_").replace("/", "_")
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:180] or "upload.bin"


async def _load_user_accounts(session: AsyncSession, user_id: uuid.UUID, account_ids: list[str]) -> list[FacebookAccount]:
    if not account_ids:
        return []
    ids = [_uuid(account_id) for account_id in account_ids]
    result = await session.execute(
        select(FacebookAccount).where(FacebookAccount.user_id == user_id, FacebookAccount.id.in_(ids))
    )
    accounts = result.scalars().all()
    if len(accounts) != len(ids):
        raise HTTPException(status_code=400, detail="One or more personal targets are not available for this user")
    return accounts


async def _get_user_account(session: AsyncSession, user_id: uuid.UUID, account_id: str) -> FacebookAccount:
    if not account_id:
        raise HTTPException(status_code=400, detail="facebook_account_id is required")
    account = await session.get(FacebookAccount, _uuid(account_id))
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=404, detail="Facebook account not found")
    return account


async def _get_user_group(session: AsyncSession, user_id: uuid.UUID, group_id: str) -> FacebookGroup:
    group = await session.get(FacebookGroup, _uuid(group_id))
    if group is None or group.user_id != user_id:
        raise HTTPException(status_code=404, detail="Facebook group not found")
    return group


async def _get_user_external_page(session: AsyncSession, user_id: uuid.UUID, page_id: str) -> ExternalPage:
    page = await session.get(ExternalPage, _uuid(page_id))
    if page is None or page.user_id != user_id:
        raise HTTPException(status_code=404, detail="External page not found")
    return page


def _parse_post_targets(body: dict) -> dict[str, list[str]]:
    page_ids = [str(v) for v in body.get("page_ids", []) if str(v)]
    group_ids = [str(v) for v in body.get("group_ids", []) if str(v)]
    personal_account_ids: list[str] = []
    for raw in body.get("targets", []) or []:
        target = str(raw)
        if target.startswith("page:"):
            page_ids.append(target.removeprefix("page:"))
        elif target.startswith("group:"):
            group_ids.append(target.removeprefix("group:"))
        elif target.startswith("personal:"):
            personal_account_ids.append(target.removeprefix("personal:"))
        elif target:
            page_ids.append(target)
    return {
        "page_ids": list(dict.fromkeys(page_ids)),
        "group_ids": list(dict.fromkeys(group_ids)),
        "personal_account_ids": list(dict.fromkeys(personal_account_ids)),
    }


def _parse_share_targets(body: dict) -> dict[str, list[str]]:
    page_ids = [str(v) for v in body.get("page_ids", []) if str(v)]
    group_ids = [str(v) for v in body.get("group_ids", []) if str(v)]
    external_page_ids = [str(v) for v in body.get("external_page_ids", []) if str(v)]
    for raw in body.get("targets", []) or []:
        target = str(raw)
        if target.startswith("page:"):
            page_ids.append(target.removeprefix("page:"))
        elif target.startswith("group:"):
            group_ids.append(target.removeprefix("group:"))
        elif target.startswith("external_page:"):
            external_page_ids.append(target.removeprefix("external_page:"))
        elif target:
            page_ids.append(target)
    return {
        "page_ids": list(dict.fromkeys(page_ids)),
        "group_ids": list(dict.fromkeys(group_ids)),
        "external_page_ids": list(dict.fromkeys(external_page_ids)),
    }


def _parse_raw_lines(raw_text: str) -> list[str]:
    return [line.strip() for line in raw_text.replace(",", "\n").splitlines() if line.strip()]


def _normalize_facebook_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise HTTPException(status_code=400, detail="URL is required")
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    if "facebook.com" not in value and "fb.com" not in value:
        raise HTTPException(status_code=400, detail=f"Invalid Facebook URL: {url}")
    return value.split("?")[0].rstrip("/")


async def _check_browser_target(user_id: str, account_id: str, target_url: str, target_type: str) -> dict:
    profile_dir = str(profile_path(user_id, account_id))
    return await asyncio.to_thread(check_target_access, profile_dir, target_url, target_type)


def _group_dict(group: FacebookGroup) -> dict:
    return {
        "id": str(group.id),
        "facebook_account_id": str(group.facebook_account_id),
        "group_url": group.group_url,
        "group_id": group.group_id or "",
        "group_name": group.group_name or "",
        "status": group.status,
        "last_error": group.last_error or "",
        "created_at": group.created_at,
    }


def _external_page_dict(page: ExternalPage) -> dict:
    return {
        "id": str(page.id),
        "facebook_account_id": str(page.facebook_account_id),
        "page_url": page.page_url,
        "page_id": page.page_id or "",
        "page_name": page.page_name or "",
        "status": page.status,
        "last_error": page.last_error or "",
        "created_at": page.created_at,
    }


async def _resolve_browser_share_target(session: AsyncSession, target: ShareTarget) -> dict | None:
    if target.target_type == "group" and target.facebook_group_id:
        group = await session.get(FacebookGroup, target.facebook_group_id)
        if group is None:
            return None
        return {
            "job_type": "share_to_group",
            "action": "share_group",
            "account_id": group.facebook_account_id,
            "target_url": group.group_url,
            "status": group.status,
            "error": group.last_error,
        }
    if target.target_type == "external_page" and target.external_page_id:
        page = await session.get(ExternalPage, target.external_page_id)
        if page is None:
            return None
        return {
            "job_type": "share_to_external_page",
            "action": "share_external_page",
            "account_id": page.facebook_account_id,
            "target_url": page.page_url,
            "status": page.status,
            "error": page.last_error,
        }
    return None


async def _task_summary(session: AsyncSession, task_id: str) -> dict:
    run = await session.get(TaskRun, _uuid(task_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await _fail_stale_browser_items(session, run)
    logs_result = await session.execute(select(TaskLog).where(TaskLog.run_id == run.id))
    logs = logs_result.scalars().all()
    items_result = await session.execute(select(TaskItem).where(TaskItem.run_id == run.id))
    items = items_result.scalars().all()
    if items:
        return {
            "id": str(run.id),
            "status": run.status.value if hasattr(run.status, "value") else run.status,
            "action": run.action.value if hasattr(run.action, "value") else run.action,
            "total": len(items),
            "success": sum(1 for item in items if item.status == TaskItemStatus.SUCCESS),
            "pending_review": sum(1 for item in items if item.status == TaskItemStatus.PENDING_REVIEW),
            "failed": sum(1 for item in items if item.status == TaskItemStatus.FAILED),
            "items": [_task_item_dict(item) for item in sorted(items, key=lambda row: row.item_index)],
            "errors": [
                _task_item_dict(item)
                for item in sorted(items, key=lambda row: row.item_index)
                if _status_value(item.status) == "failed"
            ],
        }
    return {
        "id": str(run.id),
        "status": run.status.value if hasattr(run.status, "value") else run.status,
        "action": run.action.value if hasattr(run.action, "value") else run.action,
        "total": len(logs),
        "success": sum(1 for log in logs if log.status == "Thanh cong"),
        "failed": sum(1 for log in logs if log.status != "Thanh cong"),
        "items": [],
        "errors": [
            {
                "index": log.log_index,
                "uid": log.uid or "",
                "target_link": log.comment_link,
                "action": log.action,
                "status": log.status,
                "error": log.error or "",
                "output_link": log.output_link or "",
            }
            for log in sorted(logs, key=lambda row: row.log_index)
            if log.status != "Thanh cong"
        ],
    }


async def _fail_stale_browser_items(session: AsyncSession, run: TaskRun) -> None:
    if _status_value(run.status) not in {"pending", "running"}:
        return
    now = datetime.now(timezone.utc)
    stale_items_result = await session.execute(
        select(TaskItem).where(TaskItem.run_id == run.id)
    )
    items = stale_items_result.scalars().all()
    stale_items = []
    for item in items:
        if _status_value(item.status) not in {"pending", "running"}:
            continue
        if item.action not in {"post_personal", "post_group", "share_group", "share_external_page", "share_page_browser"}:
            continue
        age_base = item.updated_at or item.created_at or run.created_at
        if age_base and age_base.tzinfo is None:
            age_base = age_base.replace(tzinfo=timezone.utc)
        if age_base and (now - age_base).total_seconds() >= EXTENSION_JOB_STALE_SECONDS:
            stale_items.append(item)

    if not stale_items:
        return

    for item in stale_items:
        item.status = TaskItemStatus.FAILED
        item.error = (
            "Extension/browser job timed out before returning a completion callback. "
            "Reload FlowMeta Connector and run the task again."
        )
        item.updated_at = now
        session.add(TaskLog(
            run_id=run.id,
            log_index=item.item_index,
            uid=item.uid,
            comment_link=item.target_link,
            action=item.action,
            proxy="Extension",
            status="That bai",
            error=item.error,
            output_link=None,
        ))

    if all(_status_value(item.status) in {"success", "failed", "pending_review", "canceled"} for item in items):
        run.status = TaskRunStatus.FAILED if any(_status_value(item.status) == "failed" for item in items) else TaskRunStatus.SUCCESS
        run.finished_at = now
    await session.commit()


async def _fail_old_user_browser_runs(session: AsyncSession, user_id) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=10)
    runs_result = await session.execute(
        select(TaskRun).where(
            TaskRun.user_id == user_id,
            TaskRun.status.in_([TaskRunStatus.PENDING, TaskRunStatus.RUNNING]),
            TaskRun.created_at < cutoff,
        )
    )
    runs = runs_result.scalars().all()
    if not runs:
        return

    for run in runs:
        items_result = await session.execute(select(TaskItem).where(TaskItem.run_id == run.id))
        items = items_result.scalars().all()
        touched = False
        for item in items:
            if _status_value(item.status) not in {"pending", "running"}:
                continue
            if item.action not in {"post_personal", "post_group", "share_group", "share_external_page", "share_page_browser"}:
                continue
            item.status = TaskItemStatus.FAILED
            item.error = "Canceled stale browser task before starting a newer task."
            item.updated_at = now
            touched = True
        if touched and all(_status_value(item.status) in {"success", "failed", "pending_review", "canceled"} for item in items):
            run.status = TaskRunStatus.FAILED
            run.finished_at = now
    await session.commit()


def _status_value(value) -> str:
    raw = value.value if hasattr(value, "value") else str(value)
    return raw.lower()


def _task_item_dict(item: TaskItem) -> dict:
    return {
        "id": item.id,
        "index": item.item_index,
        "uid": item.uid or "",
        "target_link": item.target_link,
        "action": item.action,
        "status": item.status.value if hasattr(item.status, "value") else item.status,
        "error": item.error or "",
        "output_link": item.output_link or "",
    }


def _is_token_expired_error(message: str) -> bool:
    lower = (message or "").lower()
    return (
        "access token" in lower
        and (
            "expired" in lower
            or "code 190" in lower
            or "subcode 463" in lower
            or "session has expired" in lower
        )
    )


async def _refresh_page_token(session: AsyncSession, page: FacebookPage) -> dict:
    account = await session.get(FacebookAccount, page.facebook_account_id)
    if account is None:
        return {"success": False, "message": "Facebook account for this page was not found."}

    result = await get_my_pages(decrypt(account.user_token_enc))
    if not result.get("success"):
        account.token_status = TokenStatus.DIE
        account.last_error = str(result.get("message") or result.get("error") or "Cannot refresh page token")
        account.last_checked_at = datetime.now(timezone.utc)
        page.status = "token_expired"
        await session.flush()
        return {"success": False, "message": account.last_error}

    for item in result.get("pages", []):
        if str(item.get("page_id") or "") != page.page_id:
            continue
        page_token = str(item.get("page_access_token") or "")
        if not page_token:
            break
        page.page_access_token_enc = encrypt(page_token)
        page.page_name = str(item.get("page_name") or page.page_name)
        page.category = str(item.get("category") or page.category or "")
        page.permissions = item.get("permissions") or page.permissions or []
        page.status = "active"
        page.updated_at = datetime.now(timezone.utc)
        account.token_status = TokenStatus.LIVE
        account.last_error = ""
        account.last_checked_at = datetime.now(timezone.utc)
        await session.flush()
        return {"success": True}

    page.status = "token_expired"
    await session.flush()
    return {"success": False, "message": "Current account token cannot see this page in /me/accounts. Sync pages again or import a token with page permission."}


async def _log(session: AsyncSession, run_id: str, index: int, page_id: str, action: str, result: dict) -> None:
    success = bool(result.get("success"))
    log = TaskLog(
        run_id=_uuid(run_id),
        log_index=index,
        uid=page_id,
        comment_link=result.get("post_url") or page_id,
        action=action,
        proxy="Direct",
        status="Thanh cong" if success else "That bai",
        error="" if success else result.get("message", ""),
        output_link=result.get("post_url") or None,
    )
    session.add(log)
    await session.commit()
    await event_bus.publish("log", "log", {
        "run_id": run_id,
        "log_index": index,
        "uid": page_id,
        "comment_link": log.comment_link,
        "action": action,
        "proxy": "Direct",
        "status": log.status,
        "error": log.error,
        "output_link": log.output_link,
    })


async def _finish(session: AsyncSession, run_id: str, failed: bool = False) -> None:
    run = await session.get(TaskRun, _uuid(run_id))
    if run:
        run.status = TaskRunStatus.FAILED if failed else TaskRunStatus.SUCCESS
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()


async def _fail(run_id: str, error: str) -> None:
    async with session_context() as session:
        run = await session.get(TaskRun, _uuid(run_id))
        if run:
            run.status = TaskRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
        session.add(TaskLog(
            run_id=_uuid(run_id),
            log_index=999999,
            uid=None,
            comment_link="",
            action="system",
            proxy="Direct",
            status="That bai",
            error=error,
        ))
        await session.commit()


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id") from None
