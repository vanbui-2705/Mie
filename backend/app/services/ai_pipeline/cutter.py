"""Fast stream-copy cutting with keyframe-aware boundaries.

Two fixes over the v0 implementation:
1. `-ss` goes BEFORE `-i` so ffmpeg seeks instead of decoding from frame 0
   (the difference is minutes on a long source).
2. Cut points are snapped to a keyframe that also sits inside a silence, so
   clips do not start on a black half-GOP or mid-word.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

from app.config import settings
from app.services.ai_pipeline import procs
from app.services.ai_pipeline.types import ScoredSegment

logger = logging.getLogger("flowmeta.ai_pipeline.cutter")


async def probe_keyframes(
    video_path: str, start_sec: float, end_sec: float, *, window_sec: float = 5.0
) -> list[float]:
    """Keyframe PTS around the requested cut points (two narrow read intervals)."""
    lo = max(0.0, start_sec - window_sec)
    hi = end_sec + window_sec
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-skip_frame", "nokey",
        "-select_streams", "v:0",
        "-show_entries", "frame=pts_time",
        "-of", "csv=print_section=0",
        "-read_intervals", f"{lo:.3f}%{hi:.3f}",
        video_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logger.warning("ffprobe keyframe scan failed: %s", stderr.decode(errors="replace")[-500:])
        return []

    keyframes: list[float] = []
    for line in stdout.decode(errors="replace").splitlines():
        token = line.strip().rstrip(",")
        if not token:
            continue
        try:
            keyframes.append(float(token))
        except ValueError:
            continue
    keyframes.sort()
    return keyframes


def _in_silence(t: float, silences: list[tuple[float, float]]) -> bool:
    return any(s <= t <= e for s, e in silences)


def snap_cut_points(
    start_sec: float,
    end_sec: float,
    keyframes: list[float],
    silences: list[tuple[float, float]],
    *,
    max_shift: float = 2.0,
    min_sec: float,
    max_sec: float,
) -> tuple[float, float]:
    """Move the cut points onto safe boundaries, then re-enforce the length band."""
    start = max(0.0, float(start_sec))
    end = float(end_sec)

    # START: prefer a keyframe at or before `start` that is inside a silence.
    reachable = [k for k in keyframes if start - max_shift <= k <= start]
    if reachable:
        quiet = [k for k in reachable if _in_silence(k, silences)]
        start = max(quiet) if quiet else max(reachable)

    # END: prefer the beginning of a silence just after `end` (never mid-word).
    quiet_ends = [s for s, _ in silences if end - max_shift <= s <= end + max_shift]
    if quiet_ends:
        end = min(quiet_ends, key=lambda s: abs(s - end))

    start = max(0.0, start)
    if end - start > max_sec:
        end = start + max_sec
    if end - start < min_sec:
        end = start + min_sec
    return round(start, 3), round(end, 3)


def resegment(segment: ScoredSegment, start_sec: float, end_sec: float) -> ScoredSegment:
    """Move a segment onto the window the cutter actually used.

    `build_ass` and `generate_clipspec` express everything relative to
    `segment.start_sec`, but the produced file starts at the SNAPPED start. Feeding
    them the pre-snap segment shifts every subtitle by the snap distance.
    """
    words = tuple(w for w in segment.words if w.end > start_sec and w.start < end_sec)
    return replace(segment, start_sec=start_sec, end_sec=end_sec, words=words)


def build_cut_command(
    input_path: str, output_path: str, start_sec: float, end_sec: float
) -> list[str]:
    duration = max(0.0, float(end_sec) - float(start_sec))
    return [
        settings.FFMPEG_BIN, "-y",
        "-ss", f"{float(start_sec):.3f}",
        "-i", input_path,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ]


async def cut_video_stream(
    input_path: str, output_path: str, start_sec: float, end_sec: float
) -> bool:
    """Stream copy — no re-encode. Returns False on ffmpeg failure."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = build_cut_command(input_path, output_path, start_sec, end_sec)
    logger.info("cutting %.3fs-%.3fs -> %s", start_sec, end_sec, output_path)
    process = await procs.spawn(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await procs.communicate(process)
    if process.returncode != 0:
        logger.error("ffmpeg cut failed: %s", stderr.decode(errors="replace")[-2000:])
        return False
    return True
