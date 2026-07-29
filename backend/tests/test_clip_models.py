from __future__ import annotations

import uuid

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
