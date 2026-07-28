from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus
from app.services import clip_runner as runner_mod
from app.services.ai_pipeline.types import (
    HotRegion,
    RegionTranscript,
    ScoredSegment,
    Transcript,
    Word,
)


def _segment(rank: int, start: float) -> ScoredSegment:
    words = tuple(Word(start + i, start + i + 0.5, f"w{i}") for i in range(4))
    return ScoredSegment(
        rank=rank,
        score=90.0 - rank,
        region_index=0,
        start_sec=start,
        end_sec=start + 40.0,
        hook_text=f"hook {rank}",
        subtitle_text=f"Nội dung {rank}",
        words=words,
    )


@pytest.fixture()
def fake_pipeline(monkeypatch, tmp_path: Path):
    """Stub every external process so the runner can be exercised without
    ffmpeg, whisper, yt-dlp or network."""
    state: dict[str, list] = {"cuts": [], "renders": [], "published": []}

    async def fake_resolve_source(source_type, source_ref, work_dir, job_id):
        path = tmp_path / "source.mp4"
        path.write_bytes(b"video-bytes")
        return str(path), False

    async def fake_extract_audio(video_path, audio_path):
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(b"wav")
        return True

    def fake_detect_hot_regions(wav_path, **kwargs):
        return [HotRegion(index=0, start_sec=0.0, end_sec=120.0, energy=-12.0)]

    def fake_detect_silences(wav_path, **kwargs):
        return [(39.0, 40.5)]

    async def fake_transcribe_regions(audio_path, regions, **kwargs):
        region = regions[0]
        words = tuple(Word(i * 1.0, i * 1.0 + 0.5, f"w{i}") for i in range(10))
        return Transcript(
            language="en",
            regions=(RegionTranscript(region=region, text="hello world", words=words),),
        )

    async def fake_select_clips(transcript, *, top_n, min_sec, max_sec, backend):
        return [_segment(1, 10.0), _segment(2, 60.0)]

    async def fake_probe_keyframes(video_path, start, end, **kwargs):
        return [0.0, 10.0, 60.0]

    async def fake_cut(input_path, output_path, start, end):
        state["cuts"].append((output_path, start, end))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"cut")
        return True

    async def fake_crop_path(video_path, start, end, **kwargs):
        return {"source_w": 1920, "source_h": 1080, "crop_w": 608, "crop_h": 1080,
                "x": 656, "y": 0, "path": [], "tracker": "center"}

    async def fake_burn(input_path, output_path, **kwargs):
        state["renders"].append(output_path)
        Path(output_path).write_bytes(b"rendered")
        return True

    monkeypatch.setattr(runner_mod, "resolve_source", fake_resolve_source)
    monkeypatch.setattr(runner_mod, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(runner_mod, "detect_hot_regions", fake_detect_hot_regions)
    monkeypatch.setattr(runner_mod, "detect_silences", fake_detect_silences)
    monkeypatch.setattr(runner_mod, "transcribe_regions", fake_transcribe_regions)
    monkeypatch.setattr(runner_mod, "select_clips", fake_select_clips)
    monkeypatch.setattr(runner_mod, "probe_keyframes", fake_probe_keyframes)
    monkeypatch.setattr(runner_mod, "cut_video_stream", fake_cut)
    monkeypatch.setattr(runner_mod, "compute_crop_path", fake_crop_path)
    monkeypatch.setattr(runner_mod, "burn_vertical", fake_burn)
    monkeypatch.setattr(runner_mod.settings, "CLIP_UPLOAD_DIR", str(tmp_path / "clips"))
    return state


async def _make_job(session, user_id) -> ClipJob:
    job = ClipJob(
        user_id=user_id,
        source_type=ClipSourceType.LINK,
        source_ref="https://youtu.be/x",
        params={"top_n": 2, "clip_min_sec": 30, "clip_max_sec": 60, "scoring_backend": "gemini"},
    )
    session.add(job)
    await session.commit()
    return job


async def test_runner_completes_and_persists_clips(session, session_factory, user_id, fake_pipeline):
    published = []

    async def publish(channel, event_type, data):
        published.append((channel, event_type, data))

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.DONE
    assert job.finished_at is not None
    assert job.error is None

    clips = (await session.execute(select(Clip).where(Clip.job_id == job.id))).scalars().all()
    assert len(clips) == 2
    assert {c.rank for c in clips} == {1, 2}
    assert all(c.status == ClipStatus.READY for c in clips)
    assert all(c.clipspec["version"] == 2 for c in clips)
    assert all(Path(c.output_ref).exists() for c in clips)

    phases = [d["phase"] for ch, et, d in published if et == "phase"]
    assert phases == ["analyzing", "scoring", "rendering"]
    assert any(et == "done" for _, et, _ in published)


async def test_runner_records_source_sha_and_pipeline_version(session, session_factory, user_id, fake_pipeline):
    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.source_sha256 and len(job.source_sha256) == 64
    assert job.params["pipeline_version"] == runner_mod.settings.CLIP_PIPELINE_VERSION


async def test_runner_isolates_a_single_failing_clip(session, session_factory, user_id, fake_pipeline, monkeypatch):
    async def flaky_cut(input_path, output_path, start, end):
        if "clip_1" in output_path:
            return False
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"cut")
        return True

    monkeypatch.setattr(runner_mod, "cut_video_stream", flaky_cut)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.DONE  # the job still finishes
    clips = (await session.execute(select(Clip).where(Clip.job_id == job.id))).scalars().all()
    statuses = sorted((c.status for c in clips), key=lambda s: s.value)
    assert ClipStatus.ERROR in statuses
    assert ClipStatus.READY in statuses


async def test_runner_marks_error_when_source_cannot_be_resolved(session, session_factory, user_id, fake_pipeline, monkeypatch):
    from app.services.ai_pipeline.source import SourceUnavailable

    async def failing_resolve(source_type, source_ref, work_dir, job_id):
        raise SourceUnavailable("download failed: private video")

    monkeypatch.setattr(runner_mod, "resolve_source", failing_resolve)

    published = []

    async def publish(channel, event_type, data):
        published.append((channel, event_type, data))

    job = await _make_job(session, user_id)
    with pytest.raises(SourceUnavailable):
        await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.ERROR
    assert "private video" in job.error
    assert any(et == "error" for _, et, _ in published)


async def test_runner_marks_error_when_no_clips_selected(session, session_factory, user_id, fake_pipeline, monkeypatch):
    async def empty_select(transcript, *, top_n, min_sec, max_sec, backend):
        return []

    monkeypatch.setattr(runner_mod, "select_clips", empty_select)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    with pytest.raises(RuntimeError):
        await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.ERROR


async def test_runner_deletes_the_temp_audio(session, session_factory, user_id, fake_pipeline, tmp_path):
    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    leftovers = list((tmp_path / "clips").rglob("*.wav"))
    assert leftovers == []
