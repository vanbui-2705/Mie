from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.clip_models import (
    Clip, ClipEdit, ClipEditSource, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus,
)


def test_clip_job_defaults_to_queued() -> None:
    job = ClipJob(
        user_id=uuid.uuid4(),
        source_type=ClipSourceType.LINK,
        source_ref="https://youtu.be/abc123",
        params={"top_n": 10},
    )
    assert job.status == ClipJobStatus.QUEUED
    assert job.params["top_n"] == 10


def test_clip_and_edit_link_to_job() -> None:
    clip = Clip(
        job_id=uuid.uuid4(),
        rank=1,
        score=87,
        hook_text="Bi mat la...",
        start_sec=12.5,
        end_sec=190.0,
        clipspec={"bounds": [12.5, 190.0]},
        status=ClipStatus.PENDING,
    )
    edit = ClipEdit(
        clip_id=uuid.uuid4(),
        version=1,
        clipspec={"bounds": [12.5, 190.0]},
        source=ClipEditSource.AUTO,
    )
    assert clip.rank == 1
    assert clip.status == ClipStatus.PENDING
    assert edit.source == ClipEditSource.AUTO


async def test_clip_analysis_round_trips(session, user_id, _ensure_user):
    from app.models.clip_models import ClipAnalysis

    row = ClipAnalysis(
        cache_key="abc123",
        owner_id=user_id,
        payload={"version": 1, "language": "vi", "regions": [], "words": [], "silences": []},
    )
    session.add(row)
    await session.commit()

    found = (
        await session.execute(select(ClipAnalysis).where(ClipAnalysis.cache_key == "abc123"))
    ).scalar_one()
    assert found.payload["language"] == "vi"
    assert found.hit_count == 0
    assert found.created_at is not None
    assert found.last_used_at is not None


async def test_clip_analysis_cache_key_is_unique(session, user_id, _ensure_user):
    from sqlalchemy.exc import IntegrityError

    from app.models.clip_models import ClipAnalysis

    session.add(ClipAnalysis(cache_key="dup", owner_id=user_id, payload={"version": 1}))
    await session.commit()
    session.add(ClipAnalysis(cache_key="dup", owner_id=user_id, payload={"version": 1}))
    with pytest.raises(IntegrityError):
        await session.commit()
    # The fixture commits on teardown; a session left mid-failure would raise
    # PendingRollbackError there and report it as an error in this test.
    await session.rollback()
