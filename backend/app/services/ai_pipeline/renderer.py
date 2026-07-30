"""Vertical render pass: crop to 9:16, scale to 1080x1920, burn the ASS.

This is the only re-encode in the pipeline (libx264 veryfast). Burning is done
server-side so Vietnamese diacritics render identically everywhere, which is
the whole reason for shipping the font with the image.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.ai_pipeline import procs

logger = logging.getLogger("flowmeta.ai_pipeline.renderer")

FALLBACK_FONT = "DejaVu Sans"
OUTPUT_W = 1080
OUTPUT_H = 1920


def resolve_font_name(font_dir: str, preferred: str) -> str:
    """Use the vendored font only if a TTF/OTF is actually present."""
    directory = Path(font_dir)
    if directory.is_dir():
        for pattern in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
            if any(directory.glob(pattern)):
                return preferred
    logger.warning("no font files in %s; falling back to %s", font_dir, FALLBACK_FONT)
    return FALLBACK_FONT


def escape_filter_path(path: str) -> str:
    """Escape a path for use inside an ffmpeg filtergraph argument.

    ffmpeg parses `:` as an option separator inside filters, so a Windows drive
    letter has to be escaped; backslashes become forward slashes.
    """
    escaped = str(path).replace("\\", "/")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("'", "\\'")
    return escaped


def build_render_command(
    input_path: str,
    output_path: str,
    *,
    crop: dict[str, Any],
    ass_path: str,
    font_dir: str,
    audio_path: str | None = None,
) -> list[str]:
    vf = (
        f"crop={int(crop['crop_w'])}:{int(crop['crop_h'])}:{int(crop['x'])}:{int(crop['y'])},"
        f"scale={OUTPUT_W}:{OUTPUT_H}:flags=bicubic,"
        # A source with non-square pixels carries its SAR through crop/scale, so
        # players stretch the 1080x1920 output back off 9:16. Pin it to square.
        "setsar=1,"
        f"subtitles='{escape_filter_path(ass_path)}':fontsdir='{escape_filter_path(font_dir)}'"
    )
    cmd = [settings.FFMPEG_BIN, "-y", "-i", input_path]
    if audio_path:
        # Voice-over replaces the source track outright; -shortest stops the mix
        # from extending the clip when the last cue overruns.
        cmd += ["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    return cmd + [
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]


async def burn_vertical(
    input_path: str,
    output_path: str,
    *,
    crop: dict[str, Any],
    ass_path: str,
    font_dir: str,
    audio_path: str | None = None,
) -> bool:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = build_render_command(
        input_path,
        output_path,
        crop=crop,
        ass_path=ass_path,
        font_dir=font_dir,
        audio_path=audio_path,
    )
    logger.info("rendering vertical clip -> %s", output_path)
    process = await procs.spawn(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await procs.communicate(process)
    if process.returncode != 0:
        logger.error("ffmpeg render failed: %s", stderr.decode(errors="replace")[-2000:])
        return False
    return True
