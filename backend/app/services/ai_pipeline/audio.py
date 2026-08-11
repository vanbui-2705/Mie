"""One decoded copy of a job's audio, shared by every stage that needs it.

A two-hour source at 16 kHz is ~115 million float32 samples — about 460 MB.
The pipeline used to decode that WAV three separate times (hot regions,
silences, ASR), paying the decode and the allocation once per caller. Decoding
once and passing this object around removes two of the three.

Deliberately a value object: it knows nothing about jobs, the database or video.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.ai_pipeline.prefilter import read_pcm16_mono


@dataclass(frozen=True)
class AudioTrack:
    samples: np.ndarray   # float32, mono, [-1, 1]
    sample_rate: int

    @property
    def duration_sec(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return len(self.samples) / float(self.sample_rate)


def load_track(wav_path: str) -> AudioTrack:
    """Decode a 16-bit PCM WAV once."""
    samples, sample_rate = read_pcm16_mono(wav_path)
    return AudioTrack(samples=samples, sample_rate=sample_rate)
