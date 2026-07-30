"""Vietnamese voice-over: one WAV track aligned to the subtitle cues.

The scorer already produced idiomatic Vietnamese (`subtitle_text`) and
`subtitle_gen.split_cues` already placed it on the clip timeline, so this module
only has to speak each cue and drop it at the timestamp the burned subtitle
uses. Voice and text therefore never drift apart.

Backends sit behind `synthesize_cue` the way `llm_clients` hides the LLM:
- `edge`: Microsoft Edge's read-aloud endpoint. Free, no key, neural quality,
  but an undocumented service — treat an outage as "no voice-over", never as a
  failed clip.
- `none`: disabled.

A spoken Vietnamese line is usually longer than the cue window it has to fit.
Rather than let cues overlap, each one is sped up with `atempo` — capped, so a
badly over-long line stays intelligible and simply runs into its own silence.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.services.ai_pipeline import procs

logger = logging.getLogger("flowmeta.ai_pipeline.tts")

# The ids the UI sends, mapped to the backend's own voice names.
VOICES: dict[str, str] = {
    "vi-female": "vi-VN-HoaiMyNeural",
    "vi-male": "vi-VN-NamMinhNeural",
}

MIN_TEMPO = 1.0
SAMPLE_RATE = 44100


class TTSUnavailable(Exception):
    """The backend could not speak this text."""


def resolve_voice(voice_id: str | None) -> str:
    return VOICES.get((voice_id or "").strip(), VOICES[settings.TTS_DEFAULT_VOICE])


def tempo_for(spoken_sec: float, window_sec: float, *, cap: float) -> float:
    """Playback rate that fits `spoken_sec` of speech into `window_sec`.

    Returns 1.0 when the line already fits — slowing speech down to pad a gap
    sounds worse than leaving the silence.
    """
    if spoken_sec <= 0 or window_sec <= 0:
        return MIN_TEMPO
    return max(MIN_TEMPO, min(float(cap), spoken_sec / window_sec))


def build_mix_command(
    parts: list[tuple[str, float, float]], out_path: str, *, total_sec: float
) -> list[str]:
    """ffmpeg command mixing spoken cues onto one silent track.

    `parts` is `[(path, start_sec, tempo)]`. Each input is time-stretched, then
    delayed to its cue start; `amix` with `normalize=0` keeps every cue at its
    original level (normalising would duck them all by 1/N).
    """
    cmd: list[str] = [settings.FFMPEG_BIN, "-y"]
    for path, _start, _tempo in parts:
        cmd += ["-i", path]

    chains: list[str] = []
    for i, (_path, start, tempo) in enumerate(parts):
        delay_ms = max(0, int(round(start * 1000)))
        filters = []
        if tempo > MIN_TEMPO + 1e-3:
            filters.append(f"atempo={tempo:.3f}")
        filters.append(f"adelay={delay_ms}|{delay_ms}")
        chains.append(f"[{i}:a]{','.join(filters)}[a{i}]")

    labels = "".join(f"[a{i}]" for i in range(len(parts)))
    chains.append(
        f"{labels}amix=inputs={len(parts)}:normalize=0:dropout_transition=0,"
        f"apad=whole_dur={max(0.1, total_sec):.3f}[out]"
    )

    return cmd + [
        "-filter_complex", ";".join(chains),
        "-map", "[out]",
        "-ac", "2",
        "-ar", str(SAMPLE_RATE),
        "-t", f"{max(0.1, total_sec):.3f}",
        out_path,
    ]


async def probe_duration(path: str) -> float:
    cmd = [
        settings.FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=print_section=0",
        path,
    ]
    process = await procs.spawn(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await procs.communicate(process)
    try:
        return float(stdout.decode().strip().split(",")[0])
    except (ValueError, IndexError):
        return 0.0


async def synthesize_cue(text: str, out_path: str, *, voice: str) -> bool:
    """Speak one cue to `out_path`. False means "no audio", never an exception."""
    backend = settings.TTS_BACKEND.strip().lower()
    if backend == "none":
        return False
    if backend != "edge":
        logger.warning("unknown TTS backend %r; skipping voice-over", backend)
        return False

    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts is not installed; skipping voice-over")
        return False

    retries = max(0, settings.TTS_MAX_RETRIES)
    for attempt in range(retries + 1):
        try:
            Path(out_path).unlink(missing_ok=True)
            communicate = edge_tts.Communicate(text, voice)
            await asyncio.wait_for(
                communicate.save(out_path), timeout=settings.TTS_TIMEOUT_SECONDS
            )
            break
        except Exception as exc:  # network, service change, empty text
            if attempt >= retries:
                logger.warning(
                    "TTS failed for a cue (%s, %s): %r",
                    voice, type(exc).__name__, exc,
                )
                # edge-tts may create an empty/partial file before timing out.
                # Failed tracks are not returned to the runner, so clean them
                # here instead of leaving an untracked file for retention.
                Path(out_path).unlink(missing_ok=True)
                return False
            delay = settings.TTS_RETRY_BASE_SECONDS * (2 ** attempt)
            logger.warning(
                "TTS failed for a cue (%s, %s); retrying in %.2fs",
                voice, type(exc).__name__, delay,
            )
            await asyncio.sleep(max(0.0, delay))
    return Path(out_path).exists() and Path(out_path).stat().st_size > 0


async def synthesize_scene_tracks(
    texts: list[str], *, voice_id: str | None, work_dir: Path, base: str
) -> list[tuple[str, float]]:
    """Speak each scene and report how long it took.

    Gen video works the other way round from reup: the narration decides how
    long its scene lasts, so the caller needs the measured durations before it
    can lay out the timeline.
    """
    voice = resolve_voice(voice_id)
    tracks: list[tuple[str, float]] = []
    for i, text in enumerate(texts):
        path = str(work_dir / f"{base}_scene_{i}.mp3")
        if not await synthesize_cue(text, path, voice=voice):
            tracks.append(("", 0.0))
            continue
        tracks.append((path, await probe_duration(path)))
    return tracks


async def mix_tracks(
    parts: list[tuple[str, float, float]], out_path: str, *, total_sec: float
) -> str | None:
    """Mix `[(path, start_sec, tempo)]` into one track. None on failure."""
    if not parts:
        return None
    cmd = build_mix_command(parts, out_path, total_sec=total_sec)
    process = await procs.spawn(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await procs.communicate(process)
    if process.returncode != 0:
        logger.error("voice mix failed: %s", stderr.decode(errors="replace")[-1000:])
        return None
    return out_path


async def build_voice_track(
    cues: list[tuple[float, float, str]],
    out_path: str,
    *,
    voice_id: str | None,
    total_sec: float,
    work_dir: Path,
    base: str,
) -> str | None:
    """Speak every cue and mix them into one track. None = keep the source audio.

    Best-effort by design: a cue the backend refuses is simply left silent, and
    a total failure returns None so the caller renders with the original audio.
    """
    if not cues:
        return None
    voice = resolve_voice(voice_id)
    temp_files: list[str] = []
    parts: list[tuple[str, float, float]] = []

    try:
        for i, (start, end, text) in enumerate(cues):
            spoken_path = str(work_dir / f"{base}_tts_{i}.mp3")
            if not await synthesize_cue(text, spoken_path, voice=voice):
                continue
            temp_files.append(spoken_path)
            spoken = await probe_duration(spoken_path)
            if spoken <= 0:
                continue
            window = max(0.1, float(end) - float(start))
            parts.append(
                (spoken_path, float(start), tempo_for(spoken, window, cap=settings.TTS_MAX_TEMPO))
            )

        if not parts:
            logger.warning("voice-over produced no audio; keeping the source track")
            return None

        mixed = await mix_tracks(parts, out_path, total_sec=total_sec)
        if mixed:
            logger.info("voice-over built from %d/%d cues -> %s", len(parts), len(cues), out_path)
        return mixed
    finally:
        for path in temp_files:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.warning("could not remove TTS temp file %s", path)
