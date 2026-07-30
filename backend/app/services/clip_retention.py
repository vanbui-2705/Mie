"""Auto-purge for Flow Studio artefacts.

A clip job owns real disk: the uploaded source (up to 4 GB), one rendered mp4
per clip and its .ass sidecar. The only party that wants them is the browser tab
that produced them — once the user has downloaded what they came for and the tab
is gone, nothing will ever read those bytes again.

So liveness is driven by the page: it heartbeats `last_seen_at` while it is
open, and this module deletes anything unseen for longer than the grace window.
A refresh is back within a second and keeps its files; a closed tab, a crashed
browser or a killed session all decay the same way.

The sweep is two-pass on purpose. A job that is still running is only marked
CANCELLED — the runner notices between phases, kills its ffmpeg and stops. The
files are deleted on the next pass, when nothing can be writing to them.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus

logger = logging.getLogger("flowmeta.clip_retention")

# Statuses that mean "the worker may still be writing files for this job".
ACTIVE_STATUSES = (
    ClipJobStatus.QUEUED,
    ClipJobStatus.ANALYZING,
    ClipJobStatus.SCORING,
    ClipJobStatus.RENDERING,
)

# One sweep never looks at more than this many jobs, so a backlog cannot hold a
# transaction open for minutes.
SWEEP_BATCH = 200


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes for a timezone=True column; treat those
    as UTC so the comparison works on both backends."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _unlink(path: str | os.PathLike[str] | None) -> tuple[bool, int]:
    """Delete one file. Returns (deleted, bytes freed)."""
    if not path:
        return False, 0
    try:
        size = os.path.getsize(path)
        os.remove(path)
        return True, size
    except FileNotFoundError:
        return False, 0
    except OSError as exc:
        logger.warning("could not delete %s: %s", path, exc)
        return False, 0


def job_artifact_paths(job: ClipJob, clips: list[Clip]) -> list[str]:
    """Every file this job put on disk.

    The explicit refs cover the normal case; the glob catches what a crashed or
    cancelled run left behind (`*_raw.mp4`, the `.wav`, a half-written clip),
    which is exactly the debris that would otherwise never be collected.
    """
    paths: list[str] = []
    if job.source_type == ClipSourceType.UPLOAD:
        paths.append(job.source_ref)
    for clip in clips:
        if clip.output_ref:
            paths.append(clip.output_ref)
            paths.append(str(Path(clip.output_ref).with_suffix(".ass")))

    work_dir = Path(settings.CLIP_UPLOAD_DIR) / str(job.user_id)
    try:
        paths.extend(str(p) for p in work_dir.glob(f"{job.id}*") if p.is_file())
    except OSError as exc:
        logger.warning("could not scan %s: %s", work_dir, exc)

    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def purge_job_files(job: ClipJob, clips: list[Clip]) -> tuple[int, int]:
    """Delete the job's files. Returns (files removed, bytes freed)."""
    files = 0
    freed = 0
    for path in job_artifact_paths(job, clips):
        deleted, size = _unlink(path)
        if deleted:
            files += 1
            freed += size
    return files, freed


async def touch_jobs(session, user_id: uuid.UUID, job_ids: list[uuid.UUID]) -> int:
    """Heartbeat: the caller still has these jobs on screen."""
    if not job_ids:
        return 0
    jobs = (
        await session.execute(
            select(ClipJob).where(
                ClipJob.id.in_(job_ids),
                ClipJob.user_id == user_id,
                ClipJob.purged_at.is_(None),
            )
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.last_seen_at = now
    await session.commit()
    return len(jobs)


async def sweep_once(session_factory, *, now: datetime | None = None) -> dict:
    """One retention pass. Safe to call on an idle system."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.CLIP_SESSION_GRACE_SECONDS)
    summary = {"cancelled": 0, "purged": 0, "files": 0, "bytes": 0}

    async with session_factory() as session:
        candidates = (
            await session.execute(
                select(ClipJob)
                .where(ClipJob.purged_at.is_(None))
                .order_by(ClipJob.last_seen_at.asc())
                .limit(SWEEP_BATCH)
            )
        ).scalars().all()

        for job in candidates:
            last_seen = _as_utc(job.last_seen_at) or _as_utc(job.created_at)
            if last_seen is not None and last_seen > cutoff:
                # Ordered by last_seen_at, so everything after this is younger.
                break

            if job.status in ACTIVE_STATUSES:
                # Pass one: stop the work, delete nothing yet.
                job.status = ClipJobStatus.CANCELLED
                job.finished_at = now
                summary["cancelled"] += 1
                logger.info("cancelling job %s: no heartbeat since %s", job.id, last_seen)
                continue

            clips = (
                await session.execute(select(Clip).where(Clip.job_id == job.id))
            ).scalars().all()
            files, freed = purge_job_files(job, clips)
            for clip in clips:
                if clip.status == ClipStatus.READY:
                    clip.status = ClipStatus.PURGED
                clip.output_ref = None
            job.purged_at = now
            summary["purged"] += 1
            summary["files"] += files
            summary["bytes"] += freed
            logger.info("purged job %s: %d files, %d bytes", job.id, files, freed)

        await session.commit()

    return summary


async def is_cancelled(session_factory, job_id: uuid.UUID) -> bool:
    """Whether the sweeper (or anything else) told this job to stop."""
    async with session_factory() as session:
        status = (
            await session.execute(select(ClipJob.status).where(ClipJob.id == job_id))
        ).scalar_one_or_none()
    return status is None or status == ClipJobStatus.CANCELLED
