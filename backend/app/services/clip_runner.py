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
from app.services.ai_pipeline.crop import compute_crop_path
from app.services.ai_pipeline.cutter import cut_video_stream, probe_keyframes, snap_cut_points
from app.services.ai_pipeline.prefilter import detect_hot_regions, detect_silences
from app.services.ai_pipeline.renderer import burn_vertical, resolve_font_name
from app.services.ai_pipeline.scorer import select_clips
from app.services.ai_pipeline.source import resolve_source, sha256_file
from app.services.ai_pipeline.subtitle_gen import build_ass, generate_clipspec
from app.services.ai_pipeline.vad_filter import extract_audio

logger = logging.getLogger("flowmeta.clip_runner")


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


class ClipRunner:
    PIPELINE_VERSION = settings.CLIP_PIPELINE_VERSION

    def __init__(self, session_factory, publish) -> None:
        self._session_factory = session_factory
        self._publish = publish

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
            )

    async def _set_phase(self, ctx: JobContext, status: ClipJobStatus, phase: str) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.status = status
            await session.commit()
        await self._publish(
            "clip", "phase", {"user_id": ctx.user_id, "job_id": ctx.job_id, "phase": phase}
        )

    async def _record_source(self, ctx: JobContext, sha: str) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.source_sha256 = sha
            params = dict(job.params or {})
            params["pipeline_version"] = settings.CLIP_PIPELINE_VERSION
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

    # ------------------------------------------------------------- pipeline

    async def run(self, job_id: str) -> None:
        try:
            await self._process(job_id)
        except Exception as exc:
            logger.exception("clip pipeline failed for job %s", job_id)
            await self._mark_error(job_id, str(exc))
            raise

    async def _process(self, job_id: str) -> None:
        ctx = await self._load_context(job_id)
        work_dir = Path(settings.CLIP_UPLOAD_DIR) / ctx.user_id
        work_dir.mkdir(parents=True, exist_ok=True)
        audio_path = str(work_dir / f"{ctx.job_id}.wav")
        temp_paths: list[str] = [audio_path]

        local_source, source_is_temp = await resolve_source(
            ctx.source_type, ctx.source_ref, work_dir, ctx.job_id
        )
        if source_is_temp:
            temp_paths.append(local_source)

        try:
            await self._record_source(ctx, sha256_file(local_source))

            # ---- ANALYZING: audio, prefilter, ASR ----
            await self._set_phase(ctx, ClipJobStatus.ANALYZING, "analyzing")
            if not await extract_audio(local_source, audio_path):
                raise RuntimeError("failed to extract audio from the source video")

            regions = detect_hot_regions(
                audio_path,
                min_region_sec=settings.CLIP_PREFILTER_MIN_REGION_SEC,
                max_region_sec=settings.CLIP_PREFILTER_MAX_REGION_SEC,
                max_regions=settings.CLIP_PREFILTER_MAX_REGIONS,
            )
            silences = detect_silences(audio_path)
            transcript = await transcribe_regions(audio_path, regions)
            if not transcript.regions:
                raise RuntimeError("ASR produced no usable speech regions")

            # ---- SCORING ----
            await self._set_phase(ctx, ClipJobStatus.SCORING, "scoring")
            segments = await select_clips(
                transcript,
                top_n=ctx.top_n,
                min_sec=ctx.min_sec,
                max_sec=ctx.max_sec,
                backend=ctx.scoring_backend,
            )
            if not segments:
                raise RuntimeError("no clips were selected from this source")

            # ---- RENDERING ----
            await self._set_phase(ctx, ClipJobStatus.RENDERING, "rendering")
            font_name = resolve_font_name(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)
            rows: list[dict] = []
            for segment in segments:
                rows.append(
                    await self._render_one(
                        ctx, segment, local_source, work_dir, silences, font_name, temp_paths
                    )
                )
            await self._save_clips(ctx, rows)
            await self._finish(ctx)
        finally:
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

            if not await cut_video_stream(local_source, raw_path, start, end):
                raise RuntimeError("ffmpeg stream copy failed")
            temp_paths.append(raw_path)

            crop = await compute_crop_path(raw_path, 0.0, end - start)
            Path(ass_path).write_text(
                build_ass(segment, font_name=font_name), encoding="utf-8"
            )

            if not await burn_vertical(
                raw_path,
                final_path,
                crop=crop,
                ass_path=ass_path,
                font_dir=settings.CLIP_FONT_DIR,
            ):
                raise RuntimeError("ffmpeg subtitle burn failed")

            row["clipspec"] = generate_clipspec(
                segment, video_url=video_url, crop=crop, ass_relative_path=subtitle_url
            )
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
