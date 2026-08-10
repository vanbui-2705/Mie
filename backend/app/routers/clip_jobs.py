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
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus
from app.rbac import require_permission, require_permission_media
from app.schemas import ClipHeartbeat, ClipJobOut, ClipJobSummary, ClipOut, GenJobIn
from app.services.ai_pipeline.tts_engine import VOICES
from app.services.ai_pipeline.llm_clients import SUPPORTED_BACKENDS
from app.services.clip_queue import build_clip_job, build_gen_job, enqueue_clip_job
from app.services.clip_retention import touch_jobs
from app.services.clip_storage import (
    EmptyUpload,
    UnsupportedImage,
    UploadTooLarge,
    sanitize_link,
    save_gen_image_stream,
    save_upload_stream,
)
from app.services.peer_client import peer_available

router = APIRouter(tags=["clip-jobs"])

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_STREAM_CHUNK = 1024 * 1024
_REUP_BACKENDS = SUPPORTED_BACKENDS | {"heuristic"}


def _validate_reup_params(
    *,
    top_n: int,
    clip_min_sec: int,
    clip_max_sec: int,
    scoring_backend: str,
    edit_instructions: str,
) -> tuple[str, str]:
    backend = (scoring_backend or "").strip().lower()
    if not 1 <= top_n <= 10:
        raise HTTPException(status_code=400, detail="top_n must be between 1 and 10")
    if not 5 <= clip_min_sec <= 600 or not 5 <= clip_max_sec <= 600:
        raise HTTPException(status_code=400, detail="Clip duration must be between 5 and 600 seconds")
    if clip_min_sec >= clip_max_sec:
        raise HTTPException(status_code=400, detail="clip_min_sec must be less than clip_max_sec")
    if backend not in _REUP_BACKENDS:
        raise HTTPException(status_code=400, detail=f"Unsupported scoring backend: {scoring_backend}")
    instructions = (edit_instructions or "").strip()
    if len(instructions) > 2000:
        raise HTTPException(status_code=400, detail="AI edit instructions cannot exceed 2000 characters")
    return backend, instructions


@router.post("/api/clip-jobs", response_model=dict)
async def create_clip_job(
    source_link: str | None = Form(default=None),
    top_n: int = Form(default=10),
    clip_min_sec: int = Form(default=120),
    clip_max_sec: int = Form(default=300),
    scoring_backend: str = Form(default=settings.SCORING_BACKEND),
    voiceover: bool = Form(default=False),
    voice: str = Form(default=settings.TTS_DEFAULT_VOICE),
    edit_instructions: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_permission("clip:create")),
    session: AsyncSession = Depends(get_session),
):
    scoring_backend, edit_instructions = _validate_reup_params(
        top_n=top_n,
        clip_min_sec=clip_min_sec,
        clip_max_sec=clip_max_sec,
        scoring_backend=scoring_backend,
        edit_instructions=edit_instructions,
    )
    if voice not in VOICES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice}")
    params = {
        "top_n": top_n, "clip_min_sec": clip_min_sec,
        "clip_max_sec": clip_max_sec, "scoring_backend": scoring_backend,
        "voiceover": voiceover, "voice": voice,
        "edit_instructions": edit_instructions,
    }
    if file is not None:
        # Streamed to disk in chunks: a 4 GB source must never become a 4 GB
        # bytes object in this process.
        try:
            source_ref = await save_upload_stream(
                str(user.id),
                file.filename or "video.mp4",
                file,
                max_bytes=settings.CLIP_MAX_UPLOAD_BYTES,
            )
        except EmptyUpload as exc:
            raise HTTPException(status_code=400, detail="Uploaded file is empty") from exc
        except UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail="File exceeds the upload limit") from exc
        finally:
            await file.close()
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


@router.post("/api/gen-jobs", response_model=dict)
async def create_gen_job(
    payload: GenJobIn,
    user: User = Depends(require_permission("clip:create")),
    session: AsyncSession = Depends(get_session),
):
    """Prompt -> vertical video. Stored as a ClipJob so history, streaming and
    the retention sweeper treat it exactly like a reup job."""
    if payload.voice not in VOICES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {payload.voice}")
    backend = (payload.scoring_backend or settings.SCORING_BACKEND).strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        raise HTTPException(
            status_code=400,
            detail="Gen video requires one of these AI backends: gemini, ollama, claude",
        )

    job = ClipJob(
        user_id=user.id,
        source_type=ClipSourceType.PROMPT,
        source_ref=payload.prompt.strip(),
        params={
            "duration_sec": payload.duration_sec,
            "negative_prompt": payload.negative_prompt or "",
            "voice": payload.voice,
            "scoring_backend": backend,
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    try:
        await enqueue_clip_job(build_gen_job(str(job.id)))
    except Exception as exc:
        job.status = ClipJobStatus.ERROR
        job.error = "Could not enqueue job"
        await session.commit()
        raise HTTPException(status_code=503, detail=f"Could not enqueue job: {exc}") from exc

    return {"job_id": str(job.id), "status": job.status.value}


@router.post("/api/gen-jobs/from-images", response_model=dict)
async def create_gen_job_from_images(
    prompt: str = Form(...),
    duration_sec: int = Form(default=30),
    negative_prompt: str = Form(default=""),
    voice: str = Form(default=settings.TTS_DEFAULT_VOICE),
    scoring_backend: str = Form(default=settings.SCORING_BACKEND),
    images: list[UploadFile] = File(...),
    user: User = Depends(require_permission("clip:create")),
    session: AsyncSession = Depends(get_session),
):
    """User product images -> AI sales script -> animated vertical video."""
    clean_prompt = prompt.strip()
    if len(clean_prompt) < 10 or len(clean_prompt) > 2000:
        raise HTTPException(status_code=400, detail="Prompt must contain 10 to 2000 characters")
    if len(negative_prompt) > 1000:
        raise HTTPException(status_code=400, detail="Negative prompt cannot exceed 1000 characters")
    if not 5 <= duration_sec <= settings.GEN_MAX_DURATION_SEC:
        raise HTTPException(
            status_code=400,
            detail=f"Duration must be between 5 and {settings.GEN_MAX_DURATION_SEC} seconds",
        )
    if voice not in VOICES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice}")
    backend = (scoring_backend or settings.SCORING_BACKEND).strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        raise HTTPException(
            status_code=400,
            detail="Gen video requires one of these AI backends: gemini, ollama, claude",
        )
    if not 1 <= len(images) <= settings.GEN_MAX_UPLOAD_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Upload between 1 and {settings.GEN_MAX_UPLOAD_IMAGES} images",
        )

    saved_paths: list[str] = []
    try:
        for image in images:
            try:
                path = await save_gen_image_stream(
                    str(user.id),
                    image.filename or "product",
                    image.content_type or "",
                    image,
                    max_bytes=settings.GEN_MAX_IMAGE_BYTES,
                )
                saved_paths.append(path)
            except EmptyUpload as exc:
                raise HTTPException(status_code=400, detail="Uploaded image is empty") from exc
            except UnsupportedImage as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except UploadTooLarge as exc:
                raise HTTPException(
                    status_code=413,
                    detail=f"Each image must be at most {settings.GEN_MAX_IMAGE_BYTES} bytes",
                ) from exc
            finally:
                await image.close()

        job = ClipJob(
            user_id=user.id,
            source_type=ClipSourceType.PROMPT,
            source_ref=clean_prompt,
            params={
                "duration_sec": duration_sec,
                "negative_prompt": negative_prompt.strip(),
                "voice": voice,
                "scoring_backend": backend,
                "image_paths": saved_paths,
                "image_count": len(saved_paths),
            },
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        try:
            await enqueue_clip_job(build_gen_job(str(job.id)))
        except Exception as exc:
            job.status = ClipJobStatus.ERROR
            job.error = "Could not enqueue job"
            await session.commit()
            raise HTTPException(status_code=503, detail=f"Could not enqueue job: {exc}") from exc
    except BaseException:
        for path in saved_paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        raise

    return {"job_id": str(job.id), "status": job.status.value}


@router.post("/api/clip-jobs/heartbeat", response_model=dict)
async def heartbeat_clip_jobs(
    payload: ClipHeartbeat,
    user: User = Depends(require_permission("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    """Keep the named jobs' files alive.

    An open tab beats every 30s; the sweeper deletes anything unseen for
    CLIP_SESSION_GRACE_SECONDS. A refresh is back inside the window, a closed
    tab is not. Jobs of another user are silently ignored, not rejected — the
    body is a hint, not a command.
    """
    touched = await touch_jobs(session, user.id, payload.job_ids[:50])
    return {"touched": touched}


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
            purged_at=job.purged_at,
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
        purged_at=job.purged_at,
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
    if clip.status == ClipStatus.PURGED or job.purged_at is not None:
        # 410, not 404: the clip existed and the caller is not wrong to ask.
        raise HTTPException(status_code=410, detail="Clip files were cleaned up")
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
