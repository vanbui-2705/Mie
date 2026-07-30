"""ASS subtitle generation + clipspec v2.

Two outputs, one source of truth:
- `build_ass` produces the file libass burns into the video (server-side, so
  Vietnamese diacritics are guaranteed regardless of the viewer's fonts).
- `generate_clipspec` produces the JSON the OpenCut editor round-trips.

Both use clip-RELATIVE timings, because the burn happens on the already-cut
file where t=0 is the clip start.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.ai_pipeline.types import ScoredSegment

logger = logging.getLogger("flowmeta.ai_pipeline.subtitle")

MAX_CUE_CHARS = 42
MAX_CUE_SEC = 3.5
MIN_CUE_SEC = 0.8

# WrapStyle 0 (smart wrapping), not 2 ("no wrapping"): a hook or a cue wider
# than the safe area is drawn past both edges under WrapStyle 2 instead of
# breaking onto a second line. Gen titles hit that on the very first video.
_ASS_TEMPLATE = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {video_w}
PlayResY: {video_h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},{hook_size},&H0000D7FF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,8,60,60,180,1
Style: Body,{font},{body_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""


def ass_time(seconds: float) -> str:
    """ASS timestamp: H:MM:SS.cc (centiseconds, truncated)."""
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    centis = int((total - int(total)) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def split_cues(
    text: str,
    start_sec: float,
    end_sec: float,
    *,
    max_chars: int = MAX_CUE_CHARS,
    max_cue_sec: float = MAX_CUE_SEC,
) -> list[tuple[float, float, str]]:
    """Split subtitle text into readable cues and distribute them across the clip.

    Timing is proportional to character count — the translated Vietnamese text
    does not align 1:1 with source-language word timestamps, so per-character
    interpolation is the honest approximation.
    """
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    duration = max(0.0, float(end_sec) - float(start_sec))
    total_chars = sum(len(line) for line in lines) or 1
    cues: list[tuple[float, float, str]] = []
    cursor = float(start_sec)
    for i, line in enumerate(lines):
        share = duration * (len(line) / total_chars)
        cue_len = max(MIN_CUE_SEC, min(max_cue_sec, share))
        cue_end = min(float(end_sec), cursor + cue_len)
        if i == len(lines) - 1:
            cue_end = min(float(end_sec), max(cue_end, cursor + MIN_CUE_SEC))
        if cue_end <= cursor:
            break
        cues.append((round(cursor, 3), round(cue_end, 3), line))
        cursor = cue_end
    return cues


def build_ass_from_cues(
    cues: list[tuple[float, float, str]],
    *,
    font_name: str,
    hook_text: str = "",
    hook_sec: float = 3.0,
    video_w: int = 1080,
    video_h: int = 1920,
) -> str:
    """Render an ASS file from cues that are already placed on the timeline.

    Reup derives its cues from the clip duration; Gen derives them from how long
    the voice actually took to read each scene. Both end up here so there is one
    subtitle style in the product, not two.
    """
    events: list[str] = []
    hook = _escape_ass_text(hook_text.strip())
    if hook:
        events.append(f"Dialogue: 0,{ass_time(0.0)},{ass_time(hook_sec)},Hook,,0,0,0,,{hook}")

    for start, end, line in cues:
        events.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Body,,0,0,0,,{_escape_ass_text(line)}"
        )

    return _ASS_TEMPLATE.format(
        video_w=video_w,
        video_h=video_h,
        font=font_name,
        hook_size=int(video_h * 0.045),
        body_size=int(video_h * 0.035),
        events="\n".join(events),
    )


def build_ass(
    segment: ScoredSegment,
    *,
    font_name: str,
    video_w: int = 1080,
    video_h: int = 1920,
) -> str:
    """Render the ASS file for one clip. Timings are clip-relative."""
    duration = segment.duration
    events: list[str] = []

    hook = _escape_ass_text(segment.hook_text.strip())
    if hook:
        hook_end = min(duration, 3.0)
        events.append(
            f"Dialogue: 0,{ass_time(0.0)},{ass_time(hook_end)},Hook,,0,0,0,,{hook}"
        )

    for start, end, line in split_cues(segment.subtitle_text, 0.0, duration):
        events.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Body,,0,0,0,,{_escape_ass_text(line)}"
        )

    return _ASS_TEMPLATE.format(
        video_w=video_w,
        video_h=video_h,
        font=font_name,
        hook_size=int(video_h * 0.045),
        body_size=int(video_h * 0.035),
        events="\n".join(events),
    )


def generate_clipspec(
    segment: ScoredSegment,
    *,
    video_url: str,
    crop: dict[str, Any],
    ass_relative_path: str,
) -> dict[str, Any]:
    """The editor-facing contract. Version 2 = burned server-side + crop path."""
    duration = segment.duration
    return {
        "version": 2,
        "video_url": video_url,
        "subtitle_url": ass_relative_path,
        "duration": round(duration, 3),
        "source_start_sec": segment.start_sec,
        "source_end_sec": segment.end_sec,
        "rank": segment.rank,
        "score": segment.score,
        "hook_text": segment.hook_text,
        "subtitle_text": segment.subtitle_text,
        # Relative to the clip, so the editor can scrub without re-deriving offsets.
        "words": [
            {
                "start": round(w.start - segment.start_sec, 3),
                "end": round(w.end - segment.start_sec, 3),
                "word": w.text,
            }
            for w in segment.words
        ],
        "cues": [
            {"start": start, "end": end, "text": text}
            for start, end, text in split_cues(segment.subtitle_text, 0.0, duration)
        ],
        "crop": crop,
        "style": {
            "font": "Be Vietnam Pro",
            "fontSize": 48,
            "color": "#FFFFFF",
            "highlightColor": "#FFD700",
            "stroke": "#000000",
        },
    }
