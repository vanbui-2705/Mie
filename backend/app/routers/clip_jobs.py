"""Flow Studio clip job endpoints."""
from __future__ import annotations

import os
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.postgres import get_session
from app.models.sqlmodels import User
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType
from app.rbac import require_permission, require_permission_media
from app.schemas import ClipJobOut, ClipJobSummary, ClipOut
from app.services.clip_queue import build_clip_job, enqueue_clip_job
from app.services.clip_storage import sanitize_link, save_upload
from app.services.peer_client import peer_available

router = APIRouter(tags=["clip-jobs"])

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_STREAM_CHUNK = 1024 * 1024


@router.post("/api/clip-jobs", response_model=dict)
async def create_clip_job(
    source_link: str | None = Form(default=None),
    top_n: int = Form(default=10),
    clip_min_sec: int = Form(default=120),
    clip_max_sec: int = Form(default=300),
    scoring_backend: str = Form(default=settings.SCORING_BACKEND),
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_permission("clip:create")),
    session: AsyncSession = Depends(get_session),
):
    params = {
        "top_n": top_n, "clip_min_sec": clip_min_sec,
        "clip_max_sec": clip_max_sec, "scoring_backend": scoring_backend,
    }
    if file is not None:
        content = await file.read(settings.CLIP_MAX_UPLOAD_BYTES + 1)
        await file.close()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if len(content) > settings.CLIP_MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds the upload limit")
        source_ref = save_upload(str(user.id), file.filename or "video.mp4", content)
        source_type = ClipSourceType.UPLOAD
    elif source_link:
        try:
            source_ref = sanitize_link(source_link)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source_type = ClipSourceType.LINK
    else:
        raise HTTPException(status_code=400, detail="Provide either a file or source_link")

    job = ClipJob(user_id=user.id, source_type=source_type, source_ref=source_ref, params=params)
    session.add(job)
    await session.commit()
    await session.refresh(job)

    try:
        await enqueue_clip_job(build_clip_job(str(job.id)))
    except Exception as exc:
        job.status = ClipJobStatus.ERROR
        job.error = "Could not enqueue job"
        await session.commit()
        raise HTTPException(status_code=503, detail=f"Could not enqueue job: {exc}") from exc

    return {"job_id": str(job.id), "status": job.status.value}


@router.get("/api/clip-jobs", response_model=list[ClipJobSummary])
async def list_clip_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_permission("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    counts = (
        select(Clip.job_id, func.count(Clip.id).label("clip_count"))
        .group_by(Clip.job_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(ClipJob, func.coalesce(counts.c.clip_count, 0))
            .outerjoin(counts, counts.c.job_id == ClipJob.id)
            .where(ClipJob.user_id == user.id)
            .order_by(ClipJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        ClipJobSummary(
            id=str(job.id),
            source_type=job.source_type.value,
            # The stored ref is an absolute upload path or a full URL; neither is
            # useful in a list, and the path leaks the server layout.
            source_name=os.path.basename(job.source_ref) or job.source_ref,
            status=job.status.value,
            error=job.error,
            clip_count=clip_count,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )
        for job, clip_count in rows
    ]


@router.get("/api/clip-jobs/{job_id}", response_model=ClipJobOut)
async def get_clip_job(
    job_id: uuid.UUID,
    user: User = Depends(require_permission("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    job = (await session.execute(select(ClipJob).where(ClipJob.id == job_id))).scalar_one_or_none()
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    clips = (await session.execute(select(Clip).where(Clip.job_id == job_id).order_by(Clip.rank))).scalars().all()
    return ClipJobOut(
        id=str(job.id), source_type=job.source_type.value, status=job.status.value, error=job.error,
        clips=[ClipOut(
            id=str(c.id), rank=c.rank, score=c.score, hook_text=c.hook_text,
            start_sec=c.start_sec, end_sec=c.end_sec, status=c.status.value, output_ref=c.output_ref,
            clipspec=c.clipspec,
        ) for c in clips],
    )


async def _owned_playable_clip(clip_id: uuid.UUID, user: User, session: AsyncSession) -> Clip:
    """A clip the caller owns and that has a rendered file, or the right HTTP error.

    Another user's clip answers 404, not 403: whether a clip id exists is itself
    not the caller's business.
    """
    clip = (await session.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = (await session.execute(select(ClipJob).where(ClipJob.id == clip.job_id))).scalar_one_or_none()
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Clip not found")
    if not clip.output_ref:
        raise HTTPException(status_code=409, detail="Clip has no rendered output yet")
    return clip


@router.get("/api/clips/{clip_id}/download")
async def download_clip(
    clip_id: uuid.UUID,
    user: User = Depends(require_permission("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    clip = await _owned_playable_clip(clip_id, user, session)
    return FileResponse(clip.output_ref, media_type="video/mp4", filename=f"clip-{clip.rank}.mp4")


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """`bytes=start-end` to inclusive offsets, or None when the whole file applies.

    Only single ranges are honoured. Multi-range requests are answered in full,
    which is legal and is what every browser fallback expects.
    """
    if not header:
        return None
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None
    raw_start, raw_end = match.group(1), match.group(2)
    if raw_start == "":
        if raw_end == "":
            return None
        length = min(int(raw_end), size)
        if length <= 0:
            return None
        return size - length, size - 1
    start = int(raw_start)
    end = int(raw_end) if raw_end else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        raise HTTPException(status_code=416, detail="Requested range not satisfiable")
    return start, end


@router.get("/api/clips/{clip_id}/stream")
async def stream_clip(
    request: Request,
    clip_id: uuid.UUID,
    user: User = Depends(require_permission_media("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    """Play a rendered clip in a <video> tag.

    Separate from /download because a media element cannot send an Authorization
    header (hence the ?token= form) and needs byte ranges to seek — which
    Starlette 0.37's FileResponse does not implement.
    """
    clip = await _owned_playable_clip(clip_id, user, session)
    path = clip.output_ref
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Rendered file is missing")
    size = os.path.getsize(path)
    span = _parse_range(request.headers.get("range"), size)
    start, end = span if span else (0, size - 1)
    length = end - start + 1

    def iter_file():
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(_STREAM_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "private, max-age=3600",
    }
    if span:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        iter_file(),
        status_code=206 if span else 200,
        media_type="video/mp4",
        headers=headers,
    )


@router.get("/api/flow/peers/face", response_model=dict)
async def face_peer_status(
    user: User = Depends(require_permission("clip:read")),
):
    return {"face_available": await peer_available(settings.FACE_BASE_URL)}
