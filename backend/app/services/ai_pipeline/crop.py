"""9:16 crop-window computation.

Samples frames at a low rate, finds the dominant face (OpenCV Haar cascade,
CPU, no model download beyond what ships with opencv), smooths the horizontal
centre with an EMA, and returns both a static crop rect for this render pass
and the full per-sample path for the editor to animate later.

If OpenCV is unavailable or no face is found, it degrades to a centre crop -
never an error.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.crop")

TARGET_RATIO = 9.0 / 16.0


async def probe_video_size(video_path: str) -> tuple[int, int]:
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=print_section=0:s=x",
        video_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return 0, 0
    try:
        w, h = stdout.decode().strip().split(",")[0].split("x")
        return int(w), int(h)
    except (ValueError, IndexError):
        return 0, 0


def smooth_positions(positions: list[float], *, alpha: float = 0.3) -> list[float]:
    """Exponential moving average — stops the crop jittering frame to frame."""
    out: list[float] = []
    state: float | None = None
    for value in positions:
        state = value if state is None else alpha * value + (1.0 - alpha) * state
        out.append(state)
    return out


def compute_crop(
    source_w: int, source_h: int, centres: list[tuple[float, float]]
) -> dict[str, Any]:
    """Build the crop rect from `[(t, centre_x)]` samples."""
    source_w = max(2, int(source_w))
    source_h = max(2, int(source_h))

    crop_h = source_h
    crop_w = int(round(source_h * TARGET_RATIO))
    crop_w -= crop_w % 2  # x264 requires even dimensions
    if crop_w >= source_w:
        crop_w = source_w - (source_w % 2)

    max_x = max(0, source_w - crop_w)
    default_x = max_x // 2

    if not centres:
        return {
            "source_w": source_w,
            "source_h": source_h,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "x": default_x,
            "y": 0,
            "path": [],
            "tracker": "center",
        }

    times = [t for t, _ in centres]
    smoothed = smooth_positions([c for _, c in centres], alpha=0.3)
    xs = [int(min(max_x, max(0, round(c - crop_w / 2.0)))) for c in smoothed]
    path = [{"t": round(t, 3), "x": x} for t, x in zip(times, xs)]
    ordered = sorted(xs)
    static_x = ordered[len(ordered) // 2]

    return {
        "source_w": source_w,
        "source_h": source_h,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "x": int(static_x),
        "y": 0,
        "path": path,
        "tracker": "face",
    }


def _sample_face_centres(
    video_path: str, start_sec: float, end_sec: float, sample_fps: float
) -> list[tuple[float, float]]:
    try:
        import cv2
    except ImportError:
        logger.info("opencv unavailable; falling back to centre crop")
        return []

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        logger.warning("opencv could not open %s", video_path)
        return []

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    step = 1.0 / max(sample_fps, 0.1)
    centres: list[tuple[float, float]] = []
    t = start_sec
    try:
        while t < end_sec:
            capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                centres.append((round(t - start_sec, 3), float(x) + float(w) / 2.0))
            t += step
    finally:
        capture.release()
    return centres


async def compute_crop_path(
    video_path: str, start_sec: float, end_sec: float, *, sample_fps: float = 1.0
) -> dict[str, Any]:
    """Full pipeline entry point: probe size, sample faces, build the crop rect."""
    source_w, source_h = await probe_video_size(video_path)
    if source_w <= 0 or source_h <= 0:
        logger.warning("could not probe size for %s; assuming 1920x1080", video_path)
        source_w, source_h = 1920, 1080

    if source_w <= int(round(source_h * TARGET_RATIO)):
        # Already portrait or narrower than 9:16 — nothing to track.
        return compute_crop(source_w, source_h, [])

    loop = asyncio.get_running_loop()
    centres = await loop.run_in_executor(
        None, _sample_face_centres, video_path, start_sec, end_sec, sample_fps
    )
    return compute_crop(source_w, source_h, centres)
