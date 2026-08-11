from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.ai_pipeline import asr_engine
from app.services.ai_pipeline.audio import load_track
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


class FakeFeatureExtractor:
    nb_max_frames = 3000

    def __call__(self, audio):
        return np.zeros((80, 4000), dtype=np.float32)


class FakeModel:
    """Returns one segment whose word timings are region-relative.

    Also stands in for language identification: `feature_extractor`, `encode`
    and `model.detect_language` are the three hooks asr_engine reaches for.
    """

    scores = [("en", 0.98), ("cy", 0.01)]

    def __init__(self):
        self.calls = 0
        self.kwargs: list[dict] = []
        self.feature_extractor = FakeFeatureExtractor()
        self.encoded = 0
        outer = self

        class Inner:
            def detect_language(self, encoder_output):
                return [[(f"<|{code}|>", prob) for code, prob in outer.scores]]

        self.model = Inner()

    def encode(self, features):
        self.encoded += 1
        return object()

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
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
    track = load_track(wav_path)
    region = HotRegion(index=0, start_sec=10.0, end_sec=20.0, energy=-12.0)
    sliced = asr_engine.slice_samples(track.samples, track.sample_rate, region)
    assert len(sliced) == 10 * SAMPLE_RATE


async def test_transcribe_regions_offsets_word_timestamps(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)  # sequential engine

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=30.0, end_sec=35.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)

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
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)  # sequential engine

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=10.0, end_sec=15.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)

    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.index == 1


async def test_transcribe_regions_with_no_regions_uses_whole_file(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)  # sequential engine

    transcript = await asr_engine.transcribe_regions(load_track(wav_path), [])

    assert model.calls == 1
    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.start_sec == 0.0
    assert transcript.regions[0].region.end_sec == pytest.approx(60.0, abs=0.1)


class FakeBatchedPipeline:
    """Stands in for faster_whisper.BatchedInferencePipeline."""

    def __init__(self, model):
        self.model = model
        self.calls = 0
        self.batch_sizes: list[int] = []

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        self.batch_sizes.append(kwargs.get("batch_size"))
        assert kwargs.get("word_timestamps") is True
        segments = [
            FakeSegment(" hello world", [FakeWord(0.0, 0.4, " hello"), FakeWord(0.5, 1.0, " world")])
        ]
        return iter(segments), FakeInfo()


async def test_batched_path_still_offsets_word_timestamps(monkeypatch, wav_path: str):
    pipeline = FakeBatchedPipeline(FakeModel())
    monkeypatch.setattr(asr_engine, "_get_batched_pipeline", lambda: pipeline)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 4)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=30.0, end_sec=35.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)

    assert pipeline.batch_sizes == [4, 4]
    assert transcript.regions[1].words[0].start == pytest.approx(30.0)


async def test_batch_size_zero_uses_the_sequential_model(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)

    regions = [HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0)]
    await asr_engine.transcribe_regions(load_track(wav_path), regions)

    assert model.calls == 1


async def test_a_failing_region_is_still_skipped_in_batched_mode(monkeypatch, wav_path: str):
    class ExplodingPipeline(FakeBatchedPipeline):
        def transcribe(self, audio, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("ctranslate2 blew up")
            return super().transcribe(audio, **kwargs)

    pipeline = ExplodingPipeline(FakeModel())
    monkeypatch.setattr(asr_engine, "_get_batched_pipeline", lambda: pipeline)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 4)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=10.0, end_sec=15.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)
    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.index == 1


class FakeLidModel(FakeModel):
    """A model whose language identification can be scripted."""

    def __init__(self, scores, probe_logprobs=None):
        super().__init__()
        self.scores = scores
        self.probe_logprobs = probe_logprobs or {}

    def transcribe(self, audio, **kwargs):
        language = kwargs.get("language")
        if kwargs.get("max_new_tokens"):  # a probe, not the real transcription
            self.kwargs.append(kwargs)
            segment = FakeSegment(" probe", [])
            segment.avg_logprob = self.probe_logprobs.get(language, -1.0)
            return iter([segment]), FakeInfo()
        return super().transcribe(audio, **kwargs)


def test_a_confident_encoder_verdict_needs_no_probe():
    model = FakeLidModel([("vi", 0.93), ("en", 0.05)])

    assert asr_engine.identify_language(model, np.zeros(16000, dtype=np.float32)) == "vi"
    # Decoding a probe costs a real transcription; skip it when the encoder is sure.
    assert model.kwargs == []


def test_an_unsure_verdict_is_settled_by_decoding_each_candidate():
    # What whisper-small does on accented English: it calls it Welsh, twice as
    # confidently as English, on every slice of the file.
    model = FakeLidModel(
        [("cy", 0.62), ("en", 0.37), ("mi", 0.01)],
        probe_logprobs={"cy": -0.29, "en": -0.08},
    )

    assert asr_engine.identify_language(model, np.zeros(16000, dtype=np.float32)) == "en"
    # Only the two plausible candidates are probed, and each probe is bounded.
    assert [k["language"] for k in model.kwargs] == ["cy", "en"]
    assert all(k["max_new_tokens"] for k in model.kwargs)


async def test_language_is_identified_once_and_then_pinned(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)
    monkeypatch.setattr(asr_engine.settings, "ASR_LANGUAGE", "")

    calls: list[int] = []

    def fake_identify(_model, audio):
        calls.append(len(audio))
        return "en"

    monkeypatch.setattr(asr_engine, "identify_language", fake_identify)

    regions = [
        HotRegion(index=i, start_sec=i * 10.0, end_sec=i * 10.0 + 5.0, energy=-10.0)
        for i in range(3)
    ]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)

    # One identification for the whole job: detecting per region lets one bad
    # slice send the rest of the job into another language, and decoding in the
    # wrong one is 16x slower (192s vs 12s on a measured 20s slice).
    assert len(calls) == 1
    assert [k.get("language") for k in model.kwargs] == ["en", "en", "en"]
    assert transcript.language == "en"


async def test_a_configured_language_skips_detection_entirely(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)
    monkeypatch.setattr(asr_engine.settings, "ASR_LANGUAGE", "vi")

    regions = [HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0)]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)

    assert model.kwargs[0]["language"] == "vi"
    assert transcript.language == "vi"


async def test_slices_never_condition_on_the_previous_region(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)

    regions = [HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0)]
    await asr_engine.transcribe_regions(load_track(wav_path), regions)

    # Regions are not contiguous: the previous one ended somewhere else in the
    # source, so its text is not context for this one.
    assert model.kwargs[0]["condition_on_previous_text"] is False


async def test_transcribe_regions_reports_progress(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)

    seen: list[tuple[int, int]] = []

    async def record(done: int, total: int) -> None:
        seen.append((done, total))

    regions = [
        HotRegion(index=i, start_sec=i * 10.0, end_sec=i * 10.0 + 5.0, energy=-10.0)
        for i in range(3)
    ]
    await asr_engine.transcribe_regions(load_track(wav_path), regions, on_progress=record)
    assert seen == [(1, 3), (2, 3), (3, 3)]
