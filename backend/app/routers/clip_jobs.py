"""Flow Studio clip job endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.postgres import get_session
from app.models.sqlmodels import User
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType
from app.rbac import require_permission
from app.schemas import ClipJobOut, ClipOut
from app.services.clip_queue import build_clip_job, enqueue_clip_job
from app.services.clip_storage import sanitize_link, save_upload
from app.services.peer_client import peer_available

router = APIRouter(tags=["clip-jobs"])


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
        ) for c in clips],
    )


@router.get("/api/clips/{clip_id}/download")
async def download_clip(
    clip_id: uuid.UUID,
    user: User = Depends(require_permission("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    clip = (await session.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = (await session.execute(select(ClipJob).where(ClipJob.id == clip.job_id))).scalar_one_or_none()
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Clip not found")
    if not clip.output_ref:
        raise HTTPException(status_code=409, detail="Clip has no rendered output yet")
    return FileResponse(clip.output_ref, media_type="video/mp4", filename=f"clip-{clip.rank}.mp4")


@router.get("/api/flow/peers/face", response_model=dict)
async def face_peer_status(
    user: User = Depends(require_permission("clip:read")),
):
    return {"face_available": await peer_available(settings.FACE_BASE_URL)}
