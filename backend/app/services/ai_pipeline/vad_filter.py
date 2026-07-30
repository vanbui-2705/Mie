"""Audio extraction for the AI pipeline.

Real VAD is *not* done here. faster-whisper runs Silero VAD internally
(`vad_filter=True`), and the coarse region selection lives in
`prefilter.detect_hot_regions`. This module only owns ffmpeg audio extraction
and duration probing.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.services.ai_pipeline import procs

logger = logging.getLogger("flowmeta.ai_pipeline.vad")


async def extract_audio(video_path: str, output_audio_path: str) -> bool:
    """Extract 16 kHz mono 16-bit PCM WAV — the format every later stage assumes."""
    Path(output_audio_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_BIN, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_audio_path,
    ]
    # Tracked: a cancelled job kills this mid-extraction (see procs.kill_live).
    process = await procs.spawn(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await procs.communicate(process)
    if process.returncode != 0:
        logger.error("ffmpeg audio extraction failed: %s", stderr.decode(errors="replace")[-2000:])
        return False
    return True


async def probe_duration(media_path: str) -> float:
    """Return media duration in seconds, or 0.0 when ffprobe cannot tell."""
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        media_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return 0.0
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
