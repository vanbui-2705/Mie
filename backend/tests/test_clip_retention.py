from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.clip_models import (
    Clip,
    ClipEdit,
    ClipEditSource,
    ClipJob,
    ClipJobStatus,
    ClipSourceType,
    ClipStatus,
)
from app.services import clip_retention


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(clip_retention.settings, "CLIP_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(clip_retention.settings, "CLIP_SESSION_GRACE_SECONDS", 86_400)
    return tmp_path


async def _job_with_files(
    session, user_id, upload_dir: Path, *, status=ClipJobStatus.DONE, last_seen_minutes_ago=1_500,
) -> tuple[ClipJob, list[Path]]:
    work_dir = upload_dir / str(user_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "abcdef_source.mp4"
    source.write_bytes(b"source-bytes")

    job = ClipJob(
        user_id=user_id,
        source_type=ClipSourceType.UPLOAD,
        source_ref=str(source),
        params={},
        status=status,
    )
    session.add(job)
    await session.flush()

    clip_file = work_dir / f"{job.id}_clip_1.mp4"
    clip_file.write_bytes(b"rendered-bytes")
    ass_file = work_dir / f"{job.id}_clip_1.ass"
    ass_file.write_text("subs", encoding="utf-8")
    leftover = work_dir / f"{job.id}_clip_1_raw.mp4"
    leftover.write_bytes(b"raw")

    clip = Clip(
        job_id=job.id, rank=1, start_sec=0.0, end_sec=30.0,
        clipspec={"version": 2}, output_ref=str(clip_file), status=ClipStatus.READY,
    )
    session.add(clip)
    await session.flush()
    session.add(ClipEdit(
        clip_id=clip.id, version=1, clipspec={"version": 2}, source=ClipEditSource.AUTO,
    ))
    job.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=last_seen_minutes_ago)
    await session.commit()
    return job, [source, clip_file, ass_file, leftover]


async def test_sweep_purges_files_of_a_dead_session(session, session_factory, user_id, upload_dir):
    job, files = await _job_with_files(session, user_id, upload_dir)

    summary = await clip_retention.sweep_once(session_factory)

    assert summary["purged"] == 1
    assert summary["files"] == len(files)
    assert summary["bytes"] > 0
    assert [f for f in files if f.exists()] == []

    job_id = job.id
    assert await session.get(ClipJob, job_id) is None
    clips = (await session.execute(select(Clip).where(Clip.job_id == job_id))).scalars().all()
    assert clips == []
    assert (await session.execute(select(ClipEdit))).scalars().all() == []


async def test_sweep_keeps_a_job_inside_the_grace_window(session, session_factory, user_id, upload_dir):
    job, files = await _job_with_files(session, user_id, upload_dir, last_seen_minutes_ago=0)

    summary = await clip_retention.sweep_once(session_factory)

    assert summary == {"cancelled": 0, "purged": 0, "files": 0, "bytes": 0}
    assert all(f.exists() for f in files)
    assert await session.get(ClipJob, job.id) is not None


async def test_sweep_cancels_a_running_job_before_deleting_anything(
    session, session_factory, user_id, upload_dir,
):
    job, files = await _job_with_files(session, user_id, upload_dir, status=ClipJobStatus.RENDERING)

    first = await clip_retention.sweep_once(session_factory)
    assert first["cancelled"] == 1 and first["purged"] == 0
    # Pass one must not touch files the worker may still be writing.
    assert all(f.exists() for f in files)
    await session.refresh(job)
    assert job.status == ClipJobStatus.CANCELLED

    second = await clip_retention.sweep_once(session_factory)
    assert second["purged"] == 1
    assert [f for f in files if f.exists()] == []
    assert await session.get(ClipJob, job.id) is None


async def test_sweep_does_not_purge_twice(session, session_factory, user_id, upload_dir):
    await _job_with_files(session, user_id, upload_dir)
    await clip_retention.sweep_once(session_factory)
    again = await clip_retention.sweep_once(session_factory)
    assert again["purged"] == 0


async def test_sweep_keeps_a_link_job_source(session, session_factory, user_id, upload_dir):
    """A LINK job's source_ref is a URL, not a path — nothing to delete there."""
    job = ClipJob(
        user_id=user_id, source_type=ClipSourceType.LINK,
        source_ref="https://youtu.be/x", params={},
        status=ClipJobStatus.ERROR,
    )
    session.add(job)
    job.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=1_500)
    await session.commit()

    summary = await clip_retention.sweep_once(session_factory)
    assert summary["purged"] == 1
    assert summary["files"] == 0
    assert await session.get(ClipJob, job.id) is None


async def test_sweep_deletes_uploaded_gen_images(
    session, session_factory, user_id, upload_dir,
):
    product = upload_dir / str(user_id) / "product.png"
    product.parent.mkdir(parents=True, exist_ok=True)
    product.write_bytes(b"\x89PNG\r\n\x1a\nproduct")
    job = ClipJob(
        user_id=user_id,
        source_type=ClipSourceType.PROMPT,
        source_ref="Kịch bản bán hàng đủ dài",
        params={"image_paths": [str(product)]},
        status=ClipJobStatus.DONE,
    )
    session.add(job)
    job.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=1_500)
    await session.commit()

    summary = await clip_retention.sweep_once(session_factory)

    assert summary["purged"] == 1
    assert not product.exists()
    assert await session.get(ClipJob, job.id) is None


async def test_touch_jobs_refreshes_only_the_callers_jobs(session, user_id, upload_dir):
    import uuid as _uuid

    job, _ = await _job_with_files(session, user_id, upload_dir)
    stale = job.last_seen_at

    touched = await clip_retention.touch_jobs(session, user_id, [job.id])
    assert touched == 1
    await session.refresh(job)
    assert clip_retention._as_utc(job.last_seen_at) > clip_retention._as_utc(stale)

    assert await clip_retention.touch_jobs(session, _uuid.uuid4(), [job.id]) == 0
    assert await clip_retention.touch_jobs(session, user_id, []) == 0


async def test_touch_jobs_ignores_an_already_purged_job(session, user_id, upload_dir):
    job, _ = await _job_with_files(session, user_id, upload_dir)
    job.purged_at = datetime.now(timezone.utc)
    await session.commit()

    assert await clip_retention.touch_jobs(session, user_id, [job.id]) == 0


async def test_is_cancelled(session, session_factory, user_id, upload_dir):
    import uuid as _uuid

    job, _ = await _job_with_files(session, user_id, upload_dir, status=ClipJobStatus.RENDERING)
    assert await clip_retention.is_cancelled(session_factory, job.id) is False

    job.status = ClipJobStatus.CANCELLED
    await session.commit()
    assert await clip_retention.is_cancelled(session_factory, job.id) is True
    # A job that no longer exists counts as cancelled: nothing to produce for.
    assert await clip_retention.is_cancelled(session_factory, _uuid.uuid4()) is True
