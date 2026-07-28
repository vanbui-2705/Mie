from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.ai_pipeline import asr_engine
from app.services.ai_pipeline.types import HotRegion

SAMPLE_RATE = 16000


@pytest.fixture()
def wav_path(tmp_path: Path) -> str:
    path = tmp_path / "audio.wav"
    n = 60 * SAMPLE_RATE
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    pcm = (0.5 * np.sin(2 * math.pi * 220.0 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return str(path)


class FakeSegment:
    def __init__(self, text, words):
        self.text = text
        self.words = words


class FakeWord:
    def __init__(self, start, end, word):
        self.start = start
        self.end = end
        self.word = word


class FakeInfo:
    language = "en"
    language_probability = 0.98


class FakeModel:
    """Returns one segment whose word timings are region-relative."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        segments = [
            FakeSegment(" hello world", [FakeWord(0.0, 0.4, " hello"), FakeWord(0.5, 1.0, " world")])
        ]
        return iter(segments), FakeInfo()


class ExplodingModel(FakeModel):
    def transcribe(self, audio, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("ctranslate2 blew up")
        return super().transcribe(audio, **kwargs)


def test_slice_samples_extracts_the_region(wav_path: str):
    from app.services.ai_pipeline.prefilter import read_pcm16_mono

    samples, sr = read_pcm16_mono(wav_path)
    region = HotRegion(index=0, start_sec=10.0, end_sec=20.0, energy=-12.0)
    sliced = asr_engine.slice_samples(samples, sr, region)
    assert len(sliced) == 10 * SAMPLE_RATE


async def test_transcribe_regions_offsets_word_timestamps(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=30.0, end_sec=35.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(wav_path, regions)

    assert model.calls == 2
    assert transcript.language == "en"
    assert len(transcript.regions) == 2
    assert transcript.regions[0].text == "hello world"
    # Region 1 starts at 30s, so its words must be shifted by 30s.
    assert transcript.regions[1].words[0].start == pytest.approx(30.0)
    assert transcript.regions[1].words[1].end == pytest.approx(31.0)


async def test_transcribe_regions_skips_a_failing_region(monkeypatch, wav_path: str):
    model = ExplodingModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=10.0, end_sec=15.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(wav_path, regions)

    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.index == 1


async def test_transcribe_regions_with_no_regions_uses_whole_file(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)

    transcript = await asr_engine.transcribe_regions(wav_path, [])

    assert model.calls == 1
    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.start_sec == 0.0
    assert transcript.regions[0].region.end_sec == pytest.approx(60.0, abs=0.1)
