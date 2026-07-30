"""Region-scoped CPU ASR (faster-whisper / CTranslate2, int8).

Only the hot regions found by the prefilter are transcribed, and each region is
transcribed independently so one bad slice cannot fail the whole job. Word
timestamps come back region-relative and are shifted to absolute source time
before leaving this module — every downstream stage assumes absolute seconds.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import numpy as np

from app.config import settings
from app.services.ai_pipeline.prefilter import read_pcm16_mono
from app.services.ai_pipeline.types import HotRegion, RegionTranscript, Transcript, Word

logger = logging.getLogger("flowmeta.ai_pipeline.asr")

_MODEL = None


def _get_model():
    """Lazily construct the shared WhisperModel. Import is deferred so importing
    this module (in tests, in the router) does not pull in CTranslate2."""
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        logger.info(
            "loading whisper model=%s compute_type=%s threads=%d",
            settings.ASR_WHISPER_MODEL,
            settings.ASR_COMPUTE_TYPE,
            settings.ASR_CPU_THREADS,
        )
        _MODEL = WhisperModel(
            settings.ASR_WHISPER_MODEL,
            device="cpu",
            compute_type=settings.ASR_COMPUTE_TYPE,
            cpu_threads=settings.ASR_CPU_THREADS,
        )
    return _MODEL


def reset_model_cache() -> None:
    """Drop the cached model (used by tests and by long-lived worker restarts)."""
    global _MODEL
    _MODEL = None


def slice_samples(samples: np.ndarray, sample_rate: int, region: HotRegion) -> np.ndarray:
    lo = max(0, int(region.start_sec * sample_rate))
    hi = min(len(samples), int(region.end_sec * sample_rate))
    return np.ascontiguousarray(samples[lo:hi])


def _transcribe_slice(audio: np.ndarray, language: str | None) -> tuple[str, list[Word], str]:
    model = _get_model()
    segments, info = model.transcribe(
        audio,
        beam_size=settings.ASR_BEAM_SIZE,
        vad_filter=True,
        word_timestamps=True,
        language=language,
    )
    words: list[Word] = []
    texts: list[str] = []
    for segment in segments:
        texts.append(segment.text.strip())
        for w in getattr(segment, "words", None) or []:
            token = (w.word or "").strip()
            if token:
                words.append(Word(start=float(w.start), end=float(w.end), text=token))
    detected = getattr(info, "language", None) or language or "unknown"
    return " ".join(t for t in texts if t).strip(), words, detected


async def transcribe_regions(
    audio_path: str,
    regions: Sequence[HotRegion],
    *,
    language: str | None = None,
) -> Transcript:
    """Transcribe each hot region. When `regions` is empty the whole file is
    treated as a single region (prefilter found nothing — better slow than empty)."""
    loop = asyncio.get_running_loop()
    samples, sample_rate = await loop.run_in_executor(None, read_pcm16_mono, audio_path)
    total_sec = len(samples) / float(sample_rate)

    targets = list(regions)
    if not targets:
        logger.warning("no hot regions for %s; transcribing full %.1fs", audio_path, total_sec)
        targets = [HotRegion(index=0, start_sec=0.0, end_sec=total_sec, energy=0.0)]

    detected_language = language or "unknown"
    out: list[RegionTranscript] = []
    for region in targets:
        audio = slice_samples(samples, sample_rate, region)
        if audio.size == 0:
            logger.warning("region %d is empty, skipping", region.index)
            continue
        try:
            text, words, region_language = await loop.run_in_executor(
                None, _transcribe_slice, audio, language
            )
        except Exception:
            logger.exception("ASR failed on region %d (%.1fs-%.1fs); skipping",
                             region.index, region.start_sec, region.end_sec)
            continue

        if detected_language == "unknown":
            detected_language = region_language
        shifted = tuple(
            Word(
                start=round(w.start + region.start_sec, 3),
                end=round(w.end + region.start_sec, 3),
                text=w.text,
            )
            for w in words
        )
        if not text and not shifted:
            continue
        out.append(RegionTranscript(region=region, text=text, words=shifted))

    logger.info("ASR produced %d/%d usable regions (language=%s)",
                len(out), len(targets), detected_language)
    return Transcript(language=detected_language, regions=tuple(out))
