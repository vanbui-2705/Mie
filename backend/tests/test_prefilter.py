from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.ai_pipeline.audio import load_track
from app.services.ai_pipeline.prefilter import (
    detect_hot_regions,
    detect_silences,
    frame_db,
    read_pcm16_mono,
)

SAMPLE_RATE = 16000


def _write_wav(path: Path, segments: list[tuple[float, float]]) -> None:
    """segments = [(duration_sec, amplitude 0..1)] rendered as a 220 Hz tone."""
    chunks = []
    for duration, amplitude in segments:
        n = int(duration * SAMPLE_RATE)
        t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
        chunks.append((amplitude * np.sin(2 * math.pi * 220.0 * t)).astype(np.float32))
    samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


@pytest.fixture()
def loud_middle_wav(tmp_path: Path) -> str:
    # 10s quiet, 20s loud, 10s quiet
    path = tmp_path / "sample.wav"
    _write_wav(path, [(10.0, 0.002), (20.0, 0.8), (10.0, 0.002)])
    return str(path)


def test_read_pcm16_mono_returns_normalised_samples(loud_middle_wav: str):
    samples, sr = read_pcm16_mono(loud_middle_wav)
    assert sr == SAMPLE_RATE
    assert samples.dtype == np.float32
    assert len(samples) == 40 * SAMPLE_RATE
    assert float(np.max(np.abs(samples))) <= 1.0


def test_frame_db_is_louder_in_the_middle(loud_middle_wav: str):
    samples, sr = read_pcm16_mono(loud_middle_wav)
    db = frame_db(samples, sr, frame_sec=0.5)
    assert len(db) == 80
    assert db[30] > db[5] + 20.0  # middle is far louder than the quiet head


def test_detect_silences_finds_head_and_tail(loud_middle_wav: str):
    silences = detect_silences(load_track(loud_middle_wav), threshold_db=-35.0, min_silence_sec=1.0)
    assert len(silences) == 2
    head, tail = silences
    assert head[0] == pytest.approx(0.0, abs=0.6)
    assert head[1] == pytest.approx(10.0, abs=0.6)
    assert tail[0] == pytest.approx(30.0, abs=0.6)


def test_detect_hot_regions_covers_the_loud_span(loud_middle_wav: str):
    regions = detect_hot_regions(
        load_track(loud_middle_wav), min_region_sec=5.0, max_region_sec=30.0, max_regions=5
    )
    assert len(regions) == 1
    region = regions[0]
    assert region.index == 0
    assert region.start_sec <= 11.0
    assert region.end_sec >= 29.0
    assert region.duration <= 30.0


def test_detect_hot_regions_respects_max_regions(tmp_path: Path):
    path = tmp_path / "many.wav"
    segments: list[tuple[float, float]] = []
    for _ in range(6):
        segments.append((4.0, 0.9))
        segments.append((4.0, 0.002))
    _write_wav(path, segments)
    regions = detect_hot_regions(
        load_track(str(path)), min_region_sec=3.0, max_region_sec=10.0, max_regions=2
    )
    assert len(regions) == 2
    assert [r.index for r in regions] == [0, 1]
    assert regions[0].start_sec < regions[1].start_sec


def test_detect_hot_regions_never_remerges_padded_windows_past_the_cap(tmp_path: Path):
    path = tmp_path / "overlapping-padded-windows.wav"
    segments: list[tuple[float, float]] = []
    for _ in range(8):
        segments.append((1.0, 0.9))
        segments.append((2.5, 0.002))
    _write_wav(path, segments)

    regions = detect_hot_regions(
        load_track(str(path)),
        min_region_sec=5.0,
        max_region_sec=5.0,
        max_regions=8,
        frame_sec=0.25,
    )

    assert regions
    assert all(region.duration <= 5.0 for region in regions)


def test_detect_hot_regions_on_silent_audio_returns_empty(tmp_path: Path):
    path = tmp_path / "silent.wav"
    _write_wav(path, [(20.0, 0.0)])
    assert detect_hot_regions(load_track(str(path)), min_region_sec=5.0, max_region_sec=30.0, max_regions=5) == []

