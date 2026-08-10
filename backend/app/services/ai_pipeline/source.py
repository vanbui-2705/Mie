"""Turn a ClipJob source into a local file the pipeline can read.

Uploads are already on disk. Links go through yt-dlp — never through ffmpeg
directly, which would re-download the stream once per ffmpeg invocation.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.models.clip_models import ClipSourceType
from app.services.ai_pipeline import procs

logger = logging.getLogger("flowmeta.ai_pipeline.source")


class SourceUnavailable(RuntimeError):
    """The source video could not be obtained."""


def sha256_file(path: str, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_download_command(url: str, output_path: str) -> list[str]:
    return [
        settings.YTDLP_BIN,
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url,
    ]


async def _run(cmd: list[str]) -> tuple[int, str]:
    """Seam so tests can stub subprocess execution."""
    try:
        process = await procs.spawn(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise SourceUnavailable(f"{cmd[0]} is not installed on this host") from exc
    _, stderr = await procs.communicate(process)
    return process.returncode, stderr.decode(errors="replace")


async def resolve_source(
    source_type: ClipSourceType,
    source_ref: str,
    work_dir: Path,
    job_id: str,
) -> tuple[str, bool]:
    """Return `(local_path, is_temporary)`. Temporary files are the caller's to delete."""
    work_dir.mkdir(parents=True, exist_ok=True)

    if source_type == ClipSourceType.UPLOAD:
        if not Path(source_ref).is_file():
            raise SourceUnavailable(f"uploaded source is missing: {source_ref}")
        return source_ref, False

    output_path = str(work_dir / f"{job_id}_source.mp4")
    logger.info("downloading link source for job %s", job_id)
    code, stderr = await _run(build_download_command(source_ref, output_path))
    if code != 0 or not Path(output_path).is_file():
        raise SourceUnavailable(f"download failed: {stderr.strip()[-500:] or 'unknown error'}")
    return output_path, True


@dataclass
class ResolvedSource:
    """What the pipeline can start on, and what is still on its way.

    Analysis only ever reads audio, so it does not have to wait for a 1080p
    download to finish. The video is awaited immediately before the cut.
    """

    analysis_media: str
    analysis_is_temp: bool
    video_path: str | None
    video_task: "asyncio.Task[str] | None"
    video_is_temp: bool


def build_audio_download_command(url: str, output_path: str) -> list[str]:
    return [
        settings.YTDLP_BIN,
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "-f", "ba",
        "-o", output_path,
        url,
    ]


async def _download_video(url: str, output_path: str) -> str:
    code, stderr = await _run(build_download_command(url, output_path))
    if code != 0 or not Path(output_path).is_file():
        raise SourceUnavailable(
            f"download failed: {stderr.strip()[-500:] or 'unknown error'}"
        )
    return output_path


async def resolve_source_audio_first(
    source_type: ClipSourceType,
    source_ref: str,
    work_dir: Path,
    job_id: str,
) -> ResolvedSource:
    work_dir.mkdir(parents=True, exist_ok=True)

    if source_type == ClipSourceType.UPLOAD:
        if not Path(source_ref).is_file():
            raise SourceUnavailable(f"uploaded source is missing: {source_ref}")
        return ResolvedSource(
            analysis_media=source_ref, analysis_is_temp=False,
            video_path=source_ref, video_task=None, video_is_temp=False,
        )

    video_path = str(work_dir / f"{job_id}_source.mp4")

    if settings.CLIP_SOURCE_AUDIO_FIRST:
        audio_path = str(work_dir / f"{job_id}_source_audio.m4a")
        code, stderr = await _run(build_audio_download_command(source_ref, audio_path))
        if code == 0 and Path(audio_path).is_file():
            logger.info("audio ready for job %s; video downloads in the background", job_id)
            return ResolvedSource(
                analysis_media=audio_path, analysis_is_temp=True,
                video_path=None,
                video_task=asyncio.create_task(_download_video(source_ref, video_path)),
                video_is_temp=True,
            )
        # Some sites have no audio-only format, some rate-limit the second
        # request. Either way the old single-download path still works.
        logger.info(
            "audio-only download unavailable for job %s (%s); falling back",
            job_id, stderr.strip()[-200:] or "no output",
        )

    path = await _download_video(source_ref, video_path)
    return ResolvedSource(
        analysis_media=path, analysis_is_temp=True,
        video_path=path, video_task=None, video_is_temp=True,
    )


async def await_video(resolved: ResolvedSource) -> str:
    """Block until the video file exists. Cheap when it already does."""
    if resolved.video_path is not None:
        return resolved.video_path
    if resolved.video_task is None:
        raise SourceUnavailable("no video source was resolved")
    resolved.video_path = await resolved.video_task
    return resolved.video_path
