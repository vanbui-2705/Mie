"""Region-scoped CPU ASR (faster-whisper / CTranslate2, int8).

Only the hot regions found by the prefilter are transcribed, and each region is
transcribed independently so one bad slice cannot fail the whole job. Word
timestamps come back region-relative and are shifted to absolute source time
before leaving this module — every downstream stage assumes absolute seconds.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

import numpy as np

from app.config import settings
from app.services.ai_pipeline.types import HotRegion, RegionTranscript, Transcript, Word

if TYPE_CHECKING:
    from app.services.ai_pipeline.audio import AudioTrack

logger = logging.getLogger("flowmeta.ai_pipeline.asr")

_MODEL = None
_BATCHED = None


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


def _get_batched_pipeline():
    global _BATCHED
    if _BATCHED is None:
        from faster_whisper import BatchedInferencePipeline

        logger.info("loading batched whisper pipeline (batch_size=%d)", settings.ASR_BATCH_SIZE)
        _BATCHED = BatchedInferencePipeline(model=_get_model())
    return _BATCHED


def reset_model_cache() -> None:
    """Drop the cached model (used by tests and by long-lived worker restarts)."""
    global _MODEL, _BATCHED
    _MODEL = None
    _BATCHED = None


def slice_samples(samples: np.ndarray, sample_rate: int, region: HotRegion) -> np.ndarray:
    lo = max(0, int(region.start_sec * sample_rate))
    hi = min(len(samples), int(region.end_sec * sample_rate))
    return np.ascontiguousarray(samples[lo:hi])


def _transcribe_slice(audio: np.ndarray, language: str | None) -> tuple[str, list[Word], str]:
    batch_size = int(settings.ASR_BATCH_SIZE)
    kwargs = dict(
        beam_size=settings.ASR_BEAM_SIZE,
        vad_filter=True,
        word_timestamps=True,
        language=language,
    )
    if batch_size > 0:
        engine = _get_batched_pipeline()
        kwargs["batch_size"] = batch_size
    else:
        engine = _get_model()
    segments, info = engine.transcribe(audio, **kwargs)
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
    track: "AudioTrack",
    regions: Sequence[HotRegion],
    *,
    language: str | None = None,
    on_progress: "Callable[[int, int], Awaitable[None]] | None" = None,
) -> Transcript:
    """Transcribe each hot region. When `regions` is empty the whole track is
    treated as a single region (prefilter found nothing — better slow than empty)."""
    loop = asyncio.get_running_loop()
    samples, sample_rate = track.samples, track.sample_rate
    total_sec = track.duration_sec

    targets = list(regions)
    if not targets:
        logger.warning("no hot regions; transcribing full %.1fs", total_sec)
        targets = [HotRegion(index=0, start_sec=0.0, end_sec=total_sec, energy=0.0)]

    detected_language = language or "unknown"
    out: list[RegionTranscript] = []
    # A skipped or failed region still finished, so the tick has to fire on
    # every path: freezing the bar on exactly the run that went wrong is the
    # worst time to freeze it. That is why the body is one if/else, not
    # a chain of `continue`s.
    for index, region in enumerate(targets):
        audio = slice_samples(samples, sample_rate, region)
        if audio.size == 0:
            logger.warning("region %d is empty, skipping", region.index)
        else:
            try:
                text, words, region_language = await loop.run_in_executor(
                    None, _transcribe_slice, audio, language
                )
            except Exception:
                logger.exception("ASR failed on region %d (%.1fs-%.1fs); skipping",
                                 region.index, region.start_sec, region.end_sec)
            else:
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
                if text or shifted:
                    out.append(RegionTranscript(region=region, text=text, words=shifted))

        if on_progress is not None:
            await on_progress(index + 1, len(targets))

    logger.info("ASR produced %d/%d usable regions (language=%s)",
                len(out), len(targets), detected_language)
    return Transcript(language=detected_language, regions=tuple(out))
