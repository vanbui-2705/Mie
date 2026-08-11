from __future__ import annotations

import asyncio
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
    state: dict[str, list] = {
        "cuts": [],
        "renders": [],
        "published": [],
        "edit_instructions": [],
        "prefilter_max_regions": [],
    }

    async def fake_resolve(source_type, source_ref, work_dir, job_id, on_progress=None):
        path = tmp_path / "source.mp4"
        path.write_bytes(b"video-bytes")
        return runner_mod.ResolvedSource(
            analysis_media=str(path), analysis_is_temp=False,
            video_path=str(path), video_task=None, video_is_temp=False,
        )

    async def fake_extract_audio(video_path, audio_path):
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(b"wav")
        return True

    def fake_load_track(wav_path):
        return object()  # the fakes below never look inside it

    def fake_detect_hot_regions(track, **kwargs):
        state["prefilter_max_regions"].append(kwargs["max_regions"])
        return [HotRegion(index=0, start_sec=0.0, end_sec=120.0, energy=-12.0)]

    def fake_detect_silences(track, **kwargs):
        return [(39.0, 40.5)]

    async def fake_transcribe_regions(track, regions, **kwargs):
        region = regions[0]
        words = tuple(Word(i * 1.0, i * 1.0 + 0.5, f"w{i}") for i in range(10))
        return Transcript(
            language="en",
            regions=(RegionTranscript(region=region, text="hello world", words=words),),
        )

    async def fake_select_clips(
        transcript,
        *,
        top_n,
        min_sec,
        max_sec,
        backend,
        edit_instructions="",
    ):
        state["edit_instructions"].append(edit_instructions)
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

    monkeypatch.setattr(runner_mod, "resolve_source_audio_first", fake_resolve)
    monkeypatch.setattr(runner_mod, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(runner_mod, "load_track", fake_load_track)
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
        params={
            "top_n": 2,
            "clip_min_sec": 30,
            "clip_max_sec": 60,
            "scoring_backend": "gemini",
            "edit_instructions": "Ưu tiên đoạn tự đủ ý.",
        },
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
    assert fake_pipeline["edit_instructions"] == ["Ưu tiên đoạn tự đủ ý."]
    assert fake_pipeline["prefilter_max_regions"] == [8]

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

    # Intra-phase ticks share the "phase" event type; only the transitions
    # (the ones with no progress fraction) are the phase sequence.
    phases = [d["phase"] for ch, et, d in published if et == "phase" and "progress" not in d]
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

    async def failing_resolve(source_type, source_ref, work_dir, job_id, on_progress=None):
        raise SourceUnavailable("download failed: private video")

    monkeypatch.setattr(runner_mod, "resolve_source_audio_first", failing_resolve)

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
    async def empty_select(
        transcript,
        *,
        top_n,
        min_sec,
        max_sec,
        backend,
        edit_instructions="",
    ):
        return []

    monkeypatch.setattr(runner_mod, "select_clips", empty_select)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    with pytest.raises(RuntimeError):
        await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.ERROR


async def test_runner_stops_and_keeps_cancelled_status(session, session_factory, user_id, fake_pipeline):
    """A cancelled job must not finish DONE and must not leave clips behind."""
    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    job.status = ClipJobStatus.CANCELLED
    await session.commit()

    runner = runner_mod.ClipRunner(session_factory=session_factory, publish=publish)
    runner._cancelled = True
    await runner.run(str(job.id))  # swallowed, not raised

    await session.refresh(job)
    assert job.status == ClipJobStatus.CANCELLED
    assert job.error is None
    clips = (await session.execute(select(Clip).where(Clip.job_id == job.id))).scalars().all()
    assert clips == []


async def test_cancel_watcher_flags_and_kills(session, session_factory, user_id, fake_pipeline, monkeypatch):
    killed = {"n": 0}

    def fake_kill():
        killed["n"] += 1
        return 2

    monkeypatch.setattr(runner_mod, "kill_live", fake_kill)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    job.status = ClipJobStatus.CANCELLED
    await session.commit()

    runner = runner_mod.ClipRunner(session_factory=session_factory, publish=publish)
    ctx = await runner._load_context(str(job.id))
    await runner._watch_cancel(ctx)

    assert runner._cancelled is True
    assert killed["n"] == 1


async def test_runner_deletes_the_temp_audio(session, session_factory, user_id, fake_pipeline, tmp_path):
    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    leftovers = list((tmp_path / "clips").rglob("*.wav"))
    assert leftovers == []


async def test_clips_render_concurrently(session, session_factory, user_id, fake_pipeline, monkeypatch):
    from app.services.ai_pipeline import scheduling

    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 4)
    scheduling.reset_slots()

    live = {"now": 0, "peak": 0}

    async def slow_burn(input_path, output_path, **kwargs):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.03)
        Path(output_path).write_bytes(b"rendered")
        live["now"] -= 1
        return True

    monkeypatch.setattr(runner_mod, "burn_vertical", slow_burn)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    assert live["peak"] == 2  # the fixture's fake_select_clips returns 2 segments


async def test_clip_rows_keep_rank_order(session, session_factory, user_id, fake_pipeline):
    # Concurrency must not shuffle the gallery: rank 1 is the top clip.
    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    clips = (await session.execute(select(Clip).order_by(Clip.rank))).scalars().all()
    assert [clip.rank for clip in clips] == [1, 2]


async def test_one_failing_clip_does_not_fail_the_job(session, session_factory, user_id, fake_pipeline, monkeypatch):
    async def burn_one_bad(input_path, output_path, **kwargs):
        if output_path.endswith("_clip_2.mp4"):
            return False
        Path(output_path).write_bytes(b"rendered")
        return True

    monkeypatch.setattr(runner_mod, "burn_vertical", burn_one_bad)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.DONE
    statuses = {c.rank: c.status for c in (await session.execute(select(Clip))).scalars()}
    assert statuses[1] == ClipStatus.READY
    assert statuses[2] == ClipStatus.ERROR


async def _run_two_jobs_on_one_source(session, session_factory, user_id) -> None:
    async def publish(channel, event_type, data):
        return None

    for _ in range(2):
        job = await _make_job(session, user_id)
        await runner_mod.ClipRunner(
            session_factory=session_factory, publish=publish
        ).run(str(job.id))


async def test_a_cache_hit_skips_extract_prefilter_and_asr(
    session, session_factory, user_id, fake_pipeline, monkeypatch
):
    """The payoff: re-running a source with new instructions costs no ASR."""
    calls = {"extract": 0, "asr": 0}

    async def counting_extract(video_path, audio_path):
        calls["extract"] += 1
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(b"wav")
        return True

    async def counting_asr(track, regions, **kwargs):
        calls["asr"] += 1
        return Transcript(language="en", regions=(
            RegionTranscript(region=regions[0], text="hello", words=(Word(0.0, 0.5, "hello"),)),
        ))

    monkeypatch.setattr(runner_mod, "extract_audio", counting_extract)
    monkeypatch.setattr(runner_mod, "transcribe_regions", counting_asr)

    await _run_two_jobs_on_one_source(session, session_factory, user_id)

    assert calls["extract"] == 1
    assert calls["asr"] == 1


async def test_the_cache_is_bypassed_when_disabled(
    session, session_factory, user_id, fake_pipeline, monkeypatch
):
    calls = {"asr": 0}

    async def counting_asr(track, regions, **kwargs):
        calls["asr"] += 1
        return Transcript(language="en", regions=(
            RegionTranscript(region=regions[0], text="hello", words=(Word(0.0, 0.5, "hello"),)),
        ))

    monkeypatch.setattr(runner_mod.settings, "CLIP_ANALYSIS_CACHE_ENABLED", False)
    monkeypatch.setattr(runner_mod, "transcribe_regions", counting_asr)

    await _run_two_jobs_on_one_source(session, session_factory, user_id)

    assert calls["asr"] == 2


async def test_phase_events_carry_progress(session, session_factory, user_id, fake_pipeline):
    # A 15-minute job with a bar that never moves reads as a hung job.
    published = []

    async def publish(channel, event_type, data):
        published.append((channel, event_type, data))

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    phase_events = [e for e in published if e[1] == "phase"]
    assert any("progress" in e[2] for e in phase_events)
    for _channel, _kind, body in phase_events:
        if "progress" in body:
            assert 0.0 <= body["progress"] <= 1.0


async def test_a_cancelled_render_does_not_block_the_next_job(
    session, session_factory, user_id, fake_pipeline, monkeypatch
):
    """The one check that catches a leaked CPU permit.

    The sweeper cancels the job while a render holds the slot, exactly as it
    does when the browser tab goes away mid-encode. If the permit is not
    returned, the next job waits on it forever - and that failure is silent, so
    it surfaces days later as "Flow is hung". One slot makes the leak fatal
    instead of merely slow, and the timeout turns the hang into an assertion.
    """
    from app.services.ai_pipeline import scheduling

    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 1)
    scheduling.reset_slots()

    async def publish(channel, event_type, data):
        return None

    first = await _make_job(session, user_id)
    runner = runner_mod.ClipRunner(session_factory=session_factory, publish=publish)

    async def cancelled_burn(input_path, output_path, **kwargs):
        # Holding the slot when the cancel lands: the sweeper writes CANCELLED
        # and kills ffmpeg, which surfaces here as a failed encode.
        async with session_factory() as s:
            job = (await s.execute(select(ClipJob).where(ClipJob.id == first.id))).scalar_one()
            job.status = ClipJobStatus.CANCELLED
            await s.commit()
        runner._cancelled = True
        raise RuntimeError("ffmpeg killed")

    monkeypatch.setattr(runner_mod, "burn_vertical", cancelled_burn)
    await runner.run(str(first.id))

    await session.refresh(first)
    assert first.status == ClipJobStatus.CANCELLED  # not overwritten with DONE
    clips = (await session.execute(select(Clip).where(Clip.job_id == first.id))).scalars().all()
    assert clips == []

    # Only the burn goes back to normal: monkeypatch.undo() would also unwind
    # the fake_pipeline fixture and send the second job at real yt-dlp.
    async def working_burn(input_path, output_path, **kwargs):
        Path(output_path).write_bytes(b"rendered")
        return True

    monkeypatch.setattr(runner_mod, "burn_vertical", working_burn)

    second = await _make_job(session, user_id)
    await asyncio.wait_for(
        runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(second.id)),
        timeout=15,
    )
    await session.refresh(second)
    assert second.status == ClipJobStatus.DONE
