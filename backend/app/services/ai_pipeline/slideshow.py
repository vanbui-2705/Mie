"""Still images + narration -> one vertical video, in a single ffmpeg pass.

Each scene is a still, so it needs motion or the result looks like a PowerPoint:
`zoompan` does a slow Ken Burns push on every image. Images are first scaled to
a larger canvas and cropped, because zoompan on an exactly-sized input shows a
1px jitter as the crop window lands between pixels.

One pass, not one per scene plus a concat: encoding is the expensive part and
doing it once keeps a 60s video inside a minute of CPU.
"""
from __future__ import annotations

from app.config import settings
from app.services.ai_pipeline.scheduling import ffmpeg_threads

OUTPUT_W = 1080
OUTPUT_H = 1920
FPS = 30
# Oversample before zoompan, then let it sample down into the output size.
WORK_W = OUTPUT_W * 2
WORK_H = OUTPUT_H * 2
ZOOM_MAX = 1.15


def zoom_expression(frames: int, *, zoom_in: bool) -> str:
    """Per-frame zoom, alternating direction so consecutive scenes differ."""
    step = (ZOOM_MAX - 1.0) / max(1, frames)
    if zoom_in:
        return f"min(zoom+{step:.6f},{ZOOM_MAX})"
    return f"max({ZOOM_MAX}-on*{step:.6f},1.0)"


def scene_filter(index: int, duration_sec: float) -> str:
    """The filter chain turning still `index` into `duration_sec` of video."""
    frames = max(1, int(round(duration_sec * FPS)))
    zoom = zoom_expression(frames, zoom_in=index % 2 == 0)
    return (
        f"[{index}:v]scale={WORK_W}:{WORK_H}:force_original_aspect_ratio=increase,"
        f"crop={WORK_W}:{WORK_H},"
        f"zoompan=z='{zoom}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={OUTPUT_W}x{OUTPUT_H}:fps={FPS},"
        "setsar=1[v" + str(index) + "]"
    )


def build_slideshow_command(
    images: list[tuple[str, float]],
    output_path: str,
    *,
    audio_path: str | None,
    ass_path: str,
    font_dir: str,
    escape_path,
) -> list[str]:
    """ffmpeg command for the whole video.

    `images` is `[(path, seconds)]`. `escape_path` is passed in (rather than
    imported) so this module stays independent of the reup renderer.
    """
    if not images:
        raise ValueError("a slideshow needs at least one image")

    cmd: list[str] = [settings.FFMPEG_BIN, "-y"]
    # A still-image input already contains exactly one frame. `zoompan` expands
    # that frame to the scene duration through its `d=frames` setting. Looping
    # the input here would feed many copies of the same frame into zoompan, and
    # every copy would expand again; scene one would then outlast the complete
    # video and hide every later scene.
    for path, _seconds in images:
        cmd += ["-i", path]
    if audio_path:
        cmd += ["-i", audio_path]

    chains = [scene_filter(i, seconds) for i, (_path, seconds) in enumerate(images)]
    labels = "".join(f"[v{i}]" for i in range(len(images)))
    chains.append(f"{labels}concat=n={len(images)}:v=1:a=0[cat]")
    chains.append(
        f"[cat]subtitles='{escape_path(ass_path)}':fontsdir='{escape_path(font_dir)}'[out]"
    )

    cmd += ["-filter_complex", ";".join(chains), "-map", "[out]"]
    if audio_path:
        cmd += ["-map", f"{len(images)}:a:0", "-c:a", "aac", "-b:a", "128k"]

    total_sec = sum(max(0.1, seconds) for _path, seconds in images)
    return cmd + [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        # A partial narration must not cut off later visual scenes.
        "-t", f"{total_sec:.3f}",
        # One slideshow per job: nothing else is encoding beside it.
        "-threads", str(ffmpeg_threads(1)),
        "-movflags", "+faststart",
        output_path,
    ]
