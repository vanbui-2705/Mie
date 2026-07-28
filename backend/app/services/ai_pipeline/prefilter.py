"""Tier-1 audio prefilter.

Whisper on a 2-hour source is the single most expensive CPU step in the
pipeline. This module narrows the source down to a handful of "hot" regions
using cheap signal statistics (frame energy) so ASR only runs where something
interesting is actually happening. It also produces the silence map that the
cutter uses to avoid cutting mid-word.

Deliberately numpy-only: no librosa, no torch, no model download.
"""
from __future__ import annotations

import logging
import wave

import numpy as np

from app.services.ai_pipeline.types import HotRegion

logger = logging.getLogger("flowmeta.ai_pipeline.prefilter")

_EPS = 1e-10
_DEFAULT_FRAME_SEC = 0.5

# Slack applied under the percentile cut when marking frames hot. Frame dB is
# computed in float32, so a run of genuinely equal-energy frames lands on
# values that differ in the last ulp; a strict `>= percentile` then keeps an
# arbitrary ~70% of them and shatters one region into several. Half a dB is
# far below anything audible, so this only ever absorbs numerical noise.
_HOT_TOLERANCE_DB = 0.5


def read_pcm16_mono(wav_path: str) -> tuple[np.ndarray, int]:
    """Read a 16-bit PCM WAV into float32 samples in [-1, 1], downmixed to mono."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM, got {wf.getsampwidth() * 8}-bit: {wav_path}")
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        usable = (len(samples) // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(samples), sample_rate


def frame_db(
    samples: np.ndarray, sample_rate: int, frame_sec: float = _DEFAULT_FRAME_SEC
) -> np.ndarray:
    """Per-frame RMS expressed in dBFS. Frames are non-overlapping."""
    frame_len = max(1, int(sample_rate * frame_sec))
    usable = (len(samples) // frame_len) * frame_len
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[:usable].reshape(-1, frame_len)
    rms = np.sqrt(np.mean(np.square(frames), axis=1) + _EPS)
    return (20.0 * np.log10(rms + _EPS)).astype(np.float32)


def detect_silences(
    wav_path: str,
    *,
    threshold_db: float = -35.0,
    min_silence_sec: float = 0.3,
    frame_sec: float = 0.1,
) -> list[tuple[float, float]]:
    """Return [(start_sec, end_sec)] spans quieter than `threshold_db`."""
    samples, sample_rate = read_pcm16_mono(wav_path)
    db = frame_db(samples, sample_rate, frame_sec=frame_sec)
    quiet = db < threshold_db

    spans: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, is_quiet in enumerate(quiet):
        if is_quiet and run_start is None:
            run_start = i
        elif not is_quiet and run_start is not None:
            spans.append((run_start, i))
            run_start = None
    if run_start is not None:
        spans.append((run_start, len(quiet)))

    out: list[tuple[float, float]] = []
    for start_idx, end_idx in spans:
        start = start_idx * frame_sec
        end = end_idx * frame_sec
        if end - start >= min_silence_sec:
            out.append((round(start, 3), round(end, 3)))
    return out


def _merge(spans: list[list[float]], gap_sec: float) -> list[list[float]]:
    merged: list[list[float]] = []
    for span in sorted(spans, key=lambda s: s[0]):
        if merged and span[0] - merged[-1][1] <= gap_sec:
            merged[-1][1] = max(merged[-1][1], span[1])
        else:
            merged.append([span[0], span[1]])
    return merged


def detect_hot_regions(
    wav_path: str,
    *,
    min_region_sec: float,
    max_region_sec: float,
    max_regions: int,
    frame_sec: float = _DEFAULT_FRAME_SEC,
) -> list[HotRegion]:
    """Find the loudest, most dynamic spans of the audio.

    Frames above the 70th percentile of *speech* energy are marked hot,
    contiguous runs are merged (bridging gaps up to 2s), each run is padded
    out to `min_region_sec` and truncated to `max_region_sec` around its
    loudest frame, and the top `max_regions` by mean energy are returned in
    chronological order with fresh indices.
    """
    samples, sample_rate = read_pcm16_mono(wav_path)
    db = frame_db(samples, sample_rate, frame_sec=frame_sec)
    if len(db) == 0:
        return []

    total_sec = len(db) * frame_sec
    floor_db = -55.0
    speech = db[db > floor_db]
    if speech.size == 0:
        logger.info("prefilter: no frame above %.0f dBFS in %s", floor_db, wav_path)
        return []

    threshold = float(np.percentile(speech, 70.0))
    hot = db >= threshold - _HOT_TOLERANCE_DB

    runs: list[list[float]] = []
    run_start: int | None = None
    for i, is_hot in enumerate(hot):
        if is_hot and run_start is None:
            run_start = i
        elif not is_hot and run_start is not None:
            runs.append([run_start * frame_sec, i * frame_sec])
            run_start = None
    if run_start is not None:
        runs.append([run_start * frame_sec, len(hot) * frame_sec])
    if not runs:
        return []

    runs = _merge(runs, gap_sec=2.0)

    candidates: list[tuple[float, float, float]] = []  # (start, end, energy)
    for start, end in runs:
        if end - start < min_region_sec:
            pad = (min_region_sec - (end - start)) / 2.0
            start = max(0.0, start - pad)
            end = min(total_sec, start + min_region_sec)
            start = max(0.0, end - min_region_sec)
        if end - start > max_region_sec:
            lo = int(start / frame_sec)
            hi = min(len(db), int(end / frame_sec))
            peak = lo + int(np.argmax(db[lo:hi]))
            centre = peak * frame_sec
            start = max(0.0, centre - max_region_sec / 2.0)
            end = min(total_sec, start + max_region_sec)
            start = max(0.0, end - max_region_sec)
        lo = int(start / frame_sec)
        hi = max(lo + 1, int(end / frame_sec))
        candidates.append((round(start, 3), round(end, 3), float(np.mean(db[lo:hi]))))

    merged_final = _merge([[c[0], c[1]] for c in candidates], gap_sec=0.0)
    scored: list[tuple[float, float, float]] = []
    for start, end in merged_final:
        lo = int(start / frame_sec)
        hi = max(lo + 1, int(end / frame_sec))
        scored.append((start, end, float(np.mean(db[lo:hi]))))

    scored.sort(key=lambda c: c[2], reverse=True)
    kept = scored[:max_regions]
    kept.sort(key=lambda c: c[0])

    regions = [
        HotRegion(index=i, start_sec=start, end_sec=end, energy=round(energy, 2))
        for i, (start, end, energy) in enumerate(kept)
    ]
    logger.info(
        "prefilter: %s -> %d region(s), %.1fs of %.1fs (%.0f%%)",
        wav_path,
        len(regions),
        sum(r.duration for r in regions),
        total_sec,
        100.0 * sum(r.duration for r in regions) / max(total_sec, 1.0),
    )
    return regions
