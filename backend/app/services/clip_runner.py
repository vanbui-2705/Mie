"""Flow Studio clip pipeline runner.

Orchestration only — every algorithm lives in `app.services.ai_pipeline.*`.

Two structural rules the v0 runner broke:
1. A DB session is opened per phase boundary and closed immediately. The
   pipeline itself runs with NO session held, because a single job can occupy
   the CPU for many minutes and a pinned connection starves the pool.
2. A failure rendering clip 3 marks clip 3 ERROR; it does not fail the job.
   Only source resolution, ASR, and "zero clips selected" are fatal.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus
from app.services.ai_pipeline.asr_engine import transcribe_regions
from app.services.ai_pipeline.analysis_cache import (
    build_cache_key,
    get_analysis,
    put_analysis,
)
from app.services.ai_pipeline.audio import load_track
from app.services.ai_pipeline.crop import compute_crop_path
from app.services.ai_pipeline.cutter import (
    cut_video_stream,
    probe_keyframes,
    resegment,
    snap_cut_points,
)
from app.services.ai_pipeline.prefilter import detect_hot_regions, detect_silences
from app.services.ai_pipeline.procs import kill_live
from app.services.ai_pipeline.renderer import burn_vertical, resolve_font_name
from app.services.ai_pipeline.scheduling import cpu_slot
from app.services.ai_pipeline.scorer import select_clips
from app.services.ai_pipeline.source import (
    ResolvedSource,
    await_video,
    resolve_source_audio_first,
    sha256_file,
)
from app.services.ai_pipeline.subtitle_gen import build_ass, generate_clipspec, split_cues
from app.services.ai_pipeline.timing import StageTimer
from app.services.ai_pipeline.tts_engine import build_voice_track
from app.services.ai_pipeline.vad_filter import extract_audio
from app.services.clip_retention import is_cancelled

logger = logging.getLogger("flowmeta.clip_runner")


class JobCancelled(Exception):
    """The browser session went away and the sweeper marked the job CANCELLED."""


@dataclass(frozen=True)
class JobContext:
    job_id: str
    job_uuid: uuid.UUID
    user_id: str
    source_type: ClipSourceType
    source_ref: str
    top_n: int
    min_sec: float
    max_sec: float
    scoring_backend: str
    voiceover: bool
    voice: str
    edit_instructions: str


class ClipRunner:
    PIPELINE_VERSION = settings.CLIP_PIPELINE_VERSION

    def __init__(self, session_factory, publish) -> None:
        self._session_factory = session_factory
        self._publish = publish
        self._cancelled = False
        self._timer = StageTimer()

    # ------------------------------------------------------------------ DB

    async def _load_context(self, job_id: str) -> JobContext:
        job_uuid = uuid.UUID(job_id)
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))).scalar_one()
            params = job.params or {}
            return JobContext(
                job_id=job_id,
                job_uuid=job_uuid,
                user_id=str(job.user_id),
                source_type=job.source_type,
                source_ref=job.source_ref,
                top_n=int(params.get("top_n", 3)),
                min_sec=float(params.get("clip_min_sec", 30)),
                max_sec=float(params.get("clip_max_sec", 60)),
                scoring_backend=str(params.get("scoring_backend", settings.SCORING_BACKEND)),
                voiceover=bool(params.get("voiceover", False)),
                voice=str(params.get("voice", settings.TTS_DEFAULT_VOICE)),
                edit_instructions=str(params.get("edit_instructions") or ""),
            )

    async def _set_phase(self, ctx: JobContext, status: ClipJobStatus, phase: str) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.status = status
            await session.commit()
        await self._publish(
            "clip", "phase", {"user_id": ctx.user_id, "job_id": ctx.job_id, "phase": phase}
        )

    async def _publish_progress(self, ctx: JobContext, phase: str, progress: float) -> None:
        """Intra-phase tick. No DB write — the status has not changed."""
        await self._publish(
            "clip",
            "phase",
            {
                "user_id": ctx.user_id,
                "job_id": ctx.job_id,
                "phase": phase,
                "progress": round(max(0.0, min(1.0, progress)), 3),
            },
        )

    async def _record_source(self, ctx: JobContext, sha: str) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.source_sha256 = sha
            params = dict(job.params or {})
            params["pipeline_version"] = settings.CLIP_PIPELINE_VERSION
            job.params = params
            await session.commit()

    async def _save_timings(self, job_uuid: uuid.UUID) -> None:
        """Persist the stage breakdown on the job so a slow run is diagnosable."""
        async with self._session_factory() as session:
            job = (
                await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))
            ).scalar_one_or_none()
            if job is None:
                return
            params = dict(job.params or {})
            params["timings"] = self._timer.as_dict()
            job.params = params
            await session.commit()

    async def _save_clips(self, ctx: JobContext, rows: list[dict]) -> None:
        async with self._session_factory() as session:
            for row in rows:
                session.add(Clip(job_id=ctx.job_uuid, **row))
            await session.commit()

    async def _finish(self, ctx: JobContext) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.status = ClipJobStatus.DONE
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
        await self._publish("clip", "done", {"user_id": ctx.user_id, "job_id": ctx.job_id})

    async def _mark_error(self, job_id: str, message: str) -> None:
        job_uuid = uuid.UUID(job_id)
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))).scalar_one_or_none()
            if job is None:
                return
            job.status = ClipJobStatus.ERROR
            job.error = message[:2000]
            job.finished_at = datetime.now(timezone.utc)
            user_id = str(job.user_id)
            await session.commit()
        await self._publish(
            "clip", "error", {"user_id": user_id, "job_id": job_id, "error": message[:500]}
        )

    # -------------------------------------------------------- cancellation

    async def _watch_cancel(self, ctx: JobContext) -> None:
        """Notice a cancel *during* a long step, not only between them.

        Killing the live ffmpeg is the point: the phase checks alone would let a
        render keep a core busy for minutes after the tab that wanted it closed.
        """
        while True:
            if await is_cancelled(self._session_factory, ctx.job_uuid):
                self._cancelled = True
                killed = kill_live()
                logger.info("job %s cancelled; killed %d live process(es)", ctx.job_id, killed)
                return
            await asyncio.sleep(max(0.5, settings.CLIP_CANCEL_POLL_SECONDS))

    def _abort_point(self, ctx: JobContext) -> None:
        if self._cancelled:
            raise JobCancelled(ctx.job_id)

    # ------------------------------------------------------------- pipeline

    async def run(self, job_id: str) -> None:
        try:
            await self._process(job_id)
        except Exception as exc:
            if self._cancelled or isinstance(exc, JobCancelled):
                # The sweeper already wrote CANCELLED; a killed ffmpeg surfacing
                # as "render failed" must not overwrite that with ERROR.
                logger.info("clip job %s stopped: browser session gone", job_id)
                return
            logger.exception("clip pipeline failed for job %s", job_id)
            await self._mark_error(job_id, str(exc))
            raise

    async def _process(self, job_id: str) -> None:
        ctx = await self._load_context(job_id)
        work_dir = Path(settings.CLIP_UPLOAD_DIR) / ctx.user_id
        work_dir.mkdir(parents=True, exist_ok=True)
        audio_path = str(work_dir / f"{ctx.job_id}.wav")
        temp_paths: list[str] = [audio_path]
        watcher = asyncio.create_task(self._watch_cancel(ctx))
        resolved: ResolvedSource | None = None

        try:
            async def tick_download(fraction: float) -> None:
                await self._publish_progress(ctx, "queued", fraction)

            with self._timer.stage("resolve_source"):
                resolved = await resolve_source_audio_first(
                    ctx.source_type, ctx.source_ref, work_dir, ctx.job_id,
                    on_progress=tick_download,
                )
            if resolved.analysis_is_temp:
                temp_paths.append(resolved.analysis_media)

            self._abort_point(ctx)

            # ---- ANALYZING: audio, prefilter, ASR ----
            prefilter_params = {
                "min_region_sec": settings.CLIP_PREFILTER_MIN_REGION_SEC,
                "max_region_sec": settings.CLIP_PREFILTER_MAX_REGION_SEC,
                "max_regions": min(
                    settings.CLIP_PREFILTER_MAX_REGIONS, max(8, ctx.top_n * 4)
                ),
            }
            # Hashing the media the ANALYSIS reads, not the video: for a link the
            # video is still downloading, and the transcript depends on the audio
            # anyway.
            with self._timer.stage("hash_source"):
                cache_key = build_cache_key(
                    owner_id=ctx.user_id,
                    audio_sha256=sha256_file(resolved.analysis_media),
                    prefilter=prefilter_params,
                )

            await self._set_phase(ctx, ClipJobStatus.ANALYZING, "analyzing")
            cached = (
                await get_analysis(self._session_factory, cache_key)
                if settings.CLIP_ANALYSIS_CACHE_ENABLED
                else None
            )
            if cached is not None:
                transcript, silences = cached
            else:
                with self._timer.stage("extract_audio"):
                    if not await extract_audio(resolved.analysis_media, audio_path):
                        raise RuntimeError("failed to extract audio from the source video")
                with self._timer.stage("decode_audio"):
                    track = load_track(audio_path)
                with self._timer.stage("prefilter"):
                    regions = detect_hot_regions(track, **prefilter_params)
                with self._timer.stage("silences"):
                    silences = detect_silences(track)
                self._abort_point(ctx)
                async def tick_asr(done: int, total: int) -> None:
                    await self._publish_progress(ctx, "analyzing", done / max(1, total))

                with self._timer.stage("asr"):
                    transcript = await transcribe_regions(
                        track, regions, on_progress=tick_asr
                    )
                if not transcript.regions:
                    raise RuntimeError("ASR produced no usable speech regions")
                if settings.CLIP_ANALYSIS_CACHE_ENABLED:
                    await put_analysis(
                        self._session_factory,
                        cache_key=cache_key,
                        owner_id=ctx.user_id,
                        transcript=transcript,
                        silences=silences,
                    )

            if not transcript.regions:
                raise RuntimeError("ASR produced no usable speech regions")

            # ---- SCORING ----
            self._abort_point(ctx)
            await self._set_phase(ctx, ClipJobStatus.SCORING, "scoring")
            with self._timer.stage("scoring"):
                segments = await select_clips(
                    transcript,
                    top_n=ctx.top_n,
                    min_sec=ctx.min_sec,
                    max_sec=ctx.max_sec,
                    backend=ctx.scoring_backend,
                    edit_instructions=ctx.edit_instructions,
                )
            if not segments:
                raise RuntimeError("no clips were selected from this source")

            # The cut needs real video. By now ASR and scoring have run, so the
            # download has had the whole analysis to finish.
            with self._timer.stage("await_video"):
                local_source = await await_video(resolved)
            if resolved.video_is_temp and local_source not in temp_paths:
                temp_paths.append(local_source)
            self._abort_point(ctx)
            await self._record_source(ctx, sha256_file(local_source))

            # ---- RENDERING ----
            self._abort_point(ctx)
            await self._set_phase(ctx, ClipJobStatus.RENDERING, "rendering")
            font_name = resolve_font_name(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)
            with self._timer.stage("render"):
                # gather, not a loop: the clips are independent, and the loop
                # left every core but one idle while one clip encoded.
                # `gather` preserves order, so rows stay in rank order.
                done = 0

                async def render_and_tick(segment):
                    nonlocal done
                    row = await self._render_one(
                        ctx, segment, local_source, work_dir, silences, font_name, temp_paths
                    )
                    done += 1
                    await self._publish_progress(ctx, "rendering", done / len(segments))
                    return row

                rows = list(
                    await asyncio.gather(*(render_and_tick(s) for s in segments))
                )
            await self._save_clips(ctx, rows)
            await self._finish(ctx)
        finally:
            await self._save_timings(ctx.job_uuid)
            watcher.cancel()
            # A job that failed during analysis never awaited the video, and an
            # un-awaited task both keeps downloading and logs its exception as
            # "never retrieved".
            if resolved is not None and resolved.video_task is not None:
                resolved.video_task.cancel()
            for path in temp_paths:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    logger.warning("could not remove temp file %s", path)

    async def _render_one(
        self,
        ctx: JobContext,
        segment,
        local_source: str,
        work_dir: Path,
        silences: list[tuple[float, float]],
        font_name: str,
        temp_paths: list[str],
    ) -> dict:
        """Render one clip. Any failure returns an ERROR row instead of raising."""
        # Outside the try below, so a cancelled job propagates instead of being
        # recorded as a failed clip. The render loop used to check this between
        # clips; gathering removed that seam.
        self._abort_point(ctx)
        base = f"{ctx.job_id}_clip_{segment.rank}"
        raw_path = str(work_dir / f"{base}_raw.mp4")
        ass_path = str(work_dir / f"{base}.ass")
        final_path = str(work_dir / f"{base}.mp4")
        video_url = f"/uploads/clips/{ctx.user_id}/{base}.mp4"
        subtitle_url = f"/uploads/clips/{ctx.user_id}/{base}.ass"

        row = {
            "rank": segment.rank,
            # The column is Integer; ScoredSegment.score is a float, and asyncpg
            # rejects a float for int4.
            "score": int(round(segment.score)),
            "hook_text": segment.hook_text,
            "start_sec": segment.start_sec,
            "end_sec": segment.end_sec,
            "clipspec": {},
            "output_ref": None,
            "status": ClipStatus.ERROR,
        }

        try:
            keyframes = await probe_keyframes(local_source, segment.start_sec, segment.end_sec)
            start, end = snap_cut_points(
                segment.start_sec,
                segment.end_sec,
                keyframes,
                silences,
                min_sec=ctx.min_sec,
                max_sec=ctx.max_sec,
            )
            row["start_sec"] = start
            row["end_sec"] = end
            # Subtitles and the clipspec are rebased on the segment start, so they
            # must follow the snapped window, not the one the scorer asked for.
            segment = resegment(segment, start, end)

            if not await cut_video_stream(local_source, raw_path, start, end):
                raise RuntimeError("ffmpeg stream copy failed")
            temp_paths.append(raw_path)

            async with cpu_slot():
                crop = await compute_crop_path(raw_path, 0.0, end - start)
            Path(ass_path).write_text(
                build_ass(segment, font_name=font_name), encoding="utf-8"
            )

            # The voice reads the same cues the subtitle burns, so the two can
            # never drift. A backend outage returns None and the clip keeps its
            # original audio rather than failing.
            voice_path: str | None = None
            if ctx.voiceover:
                cues = split_cues(segment.subtitle_text, 0.0, end - start)
                voice_path = await build_voice_track(
                    cues,
                    str(work_dir / f"{base}_voice.m4a"),
                    voice_id=ctx.voice,
                    total_sec=end - start,
                    work_dir=work_dir,
                    base=base,
                )
                if voice_path:
                    temp_paths.append(voice_path)

            # The slot is taken only around the CPU-bound calls: holding one
            # across the TTS round trip above would idle a core on the network.
            async with cpu_slot():
                burned = await burn_vertical(
                    raw_path,
                    final_path,
                    crop=crop,
                    ass_path=ass_path,
                    font_dir=settings.CLIP_FONT_DIR,
                    audio_path=voice_path,
                )
            if not burned:
                raise RuntimeError("ffmpeg subtitle burn failed")

            row["clipspec"] = generate_clipspec(
                segment, video_url=video_url, crop=crop, ass_relative_path=subtitle_url
            )
            # The editor needs to know whether the track it hears is the source
            # or a synthesised read of the translation.
            row["clipspec"]["voiceover"] = bool(voice_path)
            row["output_ref"] = final_path
            row["status"] = ClipStatus.READY
            await self._publish(
                "clip",
                "clip_ready",
                {"user_id": ctx.user_id, "job_id": ctx.job_id, "rank": segment.rank},
            )
        except Exception as exc:
            logger.exception("clip %d failed for job %s", segment.rank, ctx.job_id)
            row["clipspec"] = {"version": 2, "error": str(exc)[:500]}
        return row
