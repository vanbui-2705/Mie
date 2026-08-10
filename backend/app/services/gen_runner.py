"""Gen video pipeline: prompt -> script -> voice -> stills -> vertical video.

Shares the ClipJob table, the queue, the retention sweeper and the result
gallery with reup — a Gen job is just a job whose `source_type` is PROMPT and
whose `source_ref` is the prompt text. That is what makes history, streaming
and auto-purge work here without a second implementation of any of them.

The order matters: the narration is spoken BEFORE the timeline is laid out, so
every scene lasts exactly as long as its voice-over plus a breath. Images and
subtitles are then fitted to that timeline, never the other way round.
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
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipStatus
from app.services.ai_pipeline.procs import kill_live, spawn, communicate
from app.services.ai_pipeline.renderer import escape_filter_path, resolve_font_name
from app.services.ai_pipeline.script_writer import VideoScript, write_script
from app.services.ai_pipeline.slideshow import build_slideshow_command
from app.services.ai_pipeline.stock_media import backdrop_source, resolve_backdrop
from app.services.ai_pipeline.subtitle_gen import build_ass_from_cues, split_cues
from app.services.ai_pipeline.tts_engine import mix_tracks, synthesize_scene_tracks
from app.services.clip_retention import is_cancelled

logger = logging.getLogger("flowmeta.gen_runner")

MIN_SCENE_SEC = 2.0


class JobCancelled(Exception):
    """The browser session went away; the sweeper already wrote CANCELLED."""


@dataclass(frozen=True)
class GenContext:
    job_id: str
    job_uuid: uuid.UUID
    user_id: str
    prompt: str
    negative_prompt: str
    duration_sec: float
    voice: str
    backend: str
    image_paths: tuple[str, ...]


@dataclass(frozen=True)
class Timeline:
    """Scene start/duration pairs derived from the spoken narration."""

    starts: tuple[float, ...]
    durations: tuple[float, ...]

    @property
    def total(self) -> float:
        return (self.starts[-1] + self.durations[-1]) if self.starts else 0.0


def lay_out_scenes(
    spoken: list[float], suggested: list[float], *, pad_sec: float
) -> Timeline:
    """Place each scene on the timeline from how long its voice actually took.

    A scene whose TTS failed (0s) falls back to the length the script asked for,
    so a partial voice failure still produces a watchable video.
    """
    starts: list[float] = []
    durations: list[float] = []
    cursor = 0.0
    for i, seconds in enumerate(spoken):
        fallback = suggested[i] if i < len(suggested) else 0.0
        length = seconds + pad_sec if seconds > 0 else max(MIN_SCENE_SEC, fallback)
        length = max(MIN_SCENE_SEC, round(length, 3))
        starts.append(round(cursor, 3))
        durations.append(length)
        cursor += length
    return Timeline(starts=tuple(starts), durations=tuple(durations))


def build_cues(
    script: VideoScript, timeline: Timeline
) -> list[tuple[float, float, str]]:
    """Subtitle cues for the whole video, each scene inside its own window."""
    cues: list[tuple[float, float, str]] = []
    for i, scene in enumerate(script.scenes):
        if i >= len(timeline.starts):
            break
        start = timeline.starts[i]
        cues.extend(split_cues(scene.narration, start, start + timeline.durations[i]))
    return cues


def uploaded_image_for_scene(
    image_paths: tuple[str, ...], scene_index: int, scene_count: int
) -> str | None:
    """Spread ordered product images across the story without random jumps."""
    if not image_paths:
        return None
    count = max(1, scene_count)
    image_index = min(len(image_paths) - 1, scene_index * len(image_paths) // count)
    return image_paths[image_index]


class GenRunner:
    PIPELINE_VERSION = "gen-v1"

    def __init__(self, session_factory, publish) -> None:
        self._session_factory = session_factory
        self._publish = publish
        self._cancelled = False

    # ------------------------------------------------------------------ DB

    async def _load_context(self, job_id: str) -> GenContext:
        job_uuid = uuid.UUID(job_id)
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))).scalar_one()
            params = job.params or {}
            return GenContext(
                job_id=job_id,
                job_uuid=job_uuid,
                user_id=str(job.user_id),
                prompt=job.source_ref,
                negative_prompt=str(params.get("negative_prompt") or ""),
                duration_sec=float(params.get("duration_sec", 30)),
                voice=str(params.get("voice", settings.TTS_DEFAULT_VOICE)),
                backend=str(params.get("scoring_backend", settings.SCORING_BACKEND)),
                image_paths=tuple(
                    path for path in params.get("image_paths", [])
                    if isinstance(path, str) and path
                ),
            )

    async def _set_phase(self, ctx: GenContext, status: ClipJobStatus, phase: str) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.status = status
            await session.commit()
        await self._publish(
            "clip", "phase", {"user_id": ctx.user_id, "job_id": ctx.job_id, "phase": phase}
        )

    async def _save_clip(self, ctx: GenContext, row: dict) -> None:
        async with self._session_factory() as session:
            session.add(Clip(job_id=ctx.job_uuid, **row))
            await session.commit()

    async def _finish(self, ctx: GenContext) -> None:
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

    async def _watch_cancel(self, ctx: GenContext) -> None:
        while True:
            if await is_cancelled(self._session_factory, ctx.job_uuid):
                self._cancelled = True
                logger.info("gen job %s cancelled; killed %d process(es)", ctx.job_id, kill_live())
                return
            await asyncio.sleep(max(0.5, settings.CLIP_CANCEL_POLL_SECONDS))

    def _abort_point(self, ctx: GenContext) -> None:
        if self._cancelled:
            raise JobCancelled(ctx.job_id)

    # ------------------------------------------------------------- pipeline

    async def run(self, job_id: str) -> None:
        try:
            await self._process(job_id)
        except Exception as exc:
            if self._cancelled or isinstance(exc, JobCancelled):
                logger.info("gen job %s stopped: browser session gone", job_id)
                return
            logger.exception("gen pipeline failed for job %s", job_id)
            await self._mark_error(job_id, str(exc))
            raise

    async def _process(self, job_id: str) -> None:
        ctx = await self._load_context(job_id)
        work_dir = Path(settings.CLIP_UPLOAD_DIR) / ctx.user_id
        work_dir.mkdir(parents=True, exist_ok=True)
        base = f"{ctx.job_id}_gen"
        temp_paths: list[str] = []
        watcher = asyncio.create_task(self._watch_cancel(ctx))

        try:
            # ---- ANALYZING: the script ----
            await self._set_phase(ctx, ClipJobStatus.ANALYZING, "scripting")
            script = await write_script(
                ctx.prompt,
                duration_sec=ctx.duration_sec,
                backend=ctx.backend,
                negative_prompt=ctx.negative_prompt,
                minimum_scenes=len(ctx.image_paths),
            )

            # ---- SCORING: voice first, then the timeline it implies ----
            self._abort_point(ctx)
            await self._set_phase(ctx, ClipJobStatus.SCORING, "gathering")
            tracks = await synthesize_scene_tracks(
                script.narrations, voice_id=ctx.voice, work_dir=work_dir, base=base
            )
            temp_paths.extend(path for path, _ in tracks if path)
            timeline = lay_out_scenes(
                [duration for _path, duration in tracks],
                [scene.seconds for scene in script.scenes],
                pad_sec=settings.GEN_SCENE_PAD_SEC,
            )

            self._abort_point(ctx)
            backdrops: list[tuple[str, float]] = []
            visual_sources: list[str] = []
            for i, scene in enumerate(script.scenes):
                image = uploaded_image_for_scene(ctx.image_paths, i, len(script.scenes))
                visual_source = "uploaded" if image else ""
                if image and not os.path.isfile(image):
                    raise RuntimeError(f"uploaded image is missing for scene {i + 1}")
                if image is None:
                    image = await resolve_backdrop(scene.image_query, work_dir, base, i)
                    visual_source = backdrop_source(image) if image else ""
                if image is None:
                    raise RuntimeError(f"could not obtain a backdrop for scene {i + 1}")
                if visual_source != "uploaded":
                    temp_paths.append(image)
                backdrops.append((image, timeline.durations[i]))
                visual_sources.append(visual_source)

            # ---- RENDERING ----
            self._abort_point(ctx)
            await self._set_phase(ctx, ClipJobStatus.RENDERING, "rendering")
            row = await self._render(
                ctx, script, timeline, tracks, backdrops, visual_sources, work_dir, temp_paths
            )
            await self._save_clip(ctx, row)
            await self._finish(ctx)
        finally:
            watcher.cancel()
            for path in temp_paths:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    logger.warning("could not remove temp file %s", path)

    async def _render(
        self,
        ctx: GenContext,
        script: VideoScript,
        timeline: Timeline,
        tracks: list[tuple[str, float]],
        backdrops: list[tuple[str, float]],
        visual_sources: list[str],
        work_dir: Path,
        temp_paths: list[str],
    ) -> dict:
        base = f"{ctx.job_id}_clip_1"
        ass_path = str(work_dir / f"{base}.ass")
        voice_path = str(work_dir / f"{base}_voice.m4a")
        final_path = str(work_dir / f"{base}.mp4")
        video_url = f"/uploads/clips/{ctx.user_id}/{base}.mp4"
        subtitle_url = f"/uploads/clips/{ctx.user_id}/{base}.ass"

        row: dict = {
            "rank": 1,
            "score": 0,
            "hook_text": script.title,
            "start_sec": 0.0,
            "end_sec": round(timeline.total, 3),
            "clipspec": {},
            "output_ref": None,
            "status": ClipStatus.ERROR,
        }

        try:
            font_name = resolve_font_name(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)
            cues = build_cues(script, timeline)
            Path(ass_path).write_text(
                build_ass_from_cues(cues, font_name=font_name, hook_text=script.title),
                encoding="utf-8",
            )
            temp_paths.append(ass_path)

            # Each scene's speech starts when its scene does; tempo stays 1.0
            # because the timeline was built around these very durations.
            parts = [
                (path, timeline.starts[i], 1.0)
                for i, (path, duration) in enumerate(tracks)
                if path and duration > 0 and i < len(timeline.starts)
            ]
            mixed = await mix_tracks(parts, voice_path, total_sec=timeline.total) if parts else None
            if mixed:
                temp_paths.append(mixed)

            cmd = build_slideshow_command(
                backdrops,
                final_path,
                audio_path=mixed,
                ass_path=ass_path,
                font_dir=settings.CLIP_FONT_DIR,
                escape_path=escape_filter_path,
            )
            logger.info("rendering gen video (%d scenes, %.1fs) -> %s",
                        len(backdrops), timeline.total, final_path)
            process = await spawn(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await communicate(process)
            if process.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg slideshow failed: {stderr.decode(errors='replace')[-500:]}"
                )

            row["clipspec"] = {
                "version": 2,
                "kind": "gen",
                "video_url": video_url,
                "subtitle_url": subtitle_url,
                "duration": round(timeline.total, 3),
                "hook_text": script.title,
                "voiceover": bool(mixed),
                "prompt": ctx.prompt,
                "scenes": [
                    {
                        "start": timeline.starts[i],
                        "duration": timeline.durations[i],
                        "narration": scene.narration,
                        "image_query": scene.image_query,
                        "visual_source": visual_sources[i],
                    }
                    for i, scene in enumerate(script.scenes)
                    if i < len(timeline.starts)
                ],
                "words": [],
            }
            row["output_ref"] = final_path
            row["status"] = ClipStatus.READY
            await self._publish(
                "clip", "clip_ready", {"user_id": ctx.user_id, "job_id": ctx.job_id, "rank": 1}
            )
        except Exception as exc:
            logger.exception("gen render failed for job %s", ctx.job_id)
            row["clipspec"] = {"version": 2, "kind": "gen", "error": str(exc)[:500]}
        return row
