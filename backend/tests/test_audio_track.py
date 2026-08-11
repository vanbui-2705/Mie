from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.ai_pipeline.audio import AudioTrack, load_track

SAMPLE_RATE = 16000


@pytest.fixture()
def wav_path(tmp_path: Path) -> str:
    path = tmp_path / "audio.wav"
    n = 5 * SAMPLE_RATE
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    pcm = (0.5 * np.sin(2 * math.pi * 220.0 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return str(path)


def test_load_track_returns_normalised_mono_samples(wav_path: str):
    track = load_track(wav_path)
    assert track.sample_rate == SAMPLE_RATE
    assert track.samples.dtype == np.float32
    assert float(np.max(np.abs(track.samples))) <= 1.0


def test_duration_sec_matches_the_sample_count(wav_path: str):
    track = load_track(wav_path)
    assert track.duration_sec == pytest.approx(5.0, abs=0.01)


def test_duration_sec_of_an_empty_track_is_zero():
    track = AudioTrack(samples=np.zeros(0, dtype=np.float32), sample_rate=16000)
    assert track.duration_sec == 0.0
