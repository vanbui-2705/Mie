from __future__ import annotations

import pytest

from app.services.ai_pipeline import scorer
from app.services.ai_pipeline.llm_clients import LLMUnavailable
from app.services.ai_pipeline.types import HotRegion, RegionTranscript, ScoredSegment, Transcript, Word


def _region_transcript(index: int, start: float, n_words: int = 120) -> RegionTranscript:
    region = HotRegion(index=index, start_sec=start, end_sec=start + n_words * 0.5, energy=-12.0)
    words = tuple(
        Word(start=start + i * 0.5, end=start + i * 0.5 + 0.4, text=f"w{index}_{i}")
        for i in range(n_words)
    )
    return RegionTranscript(region=region, text=" ".join(w.text for w in words), words=words)


@pytest.fixture()
def transcript() -> Transcript:
    return Transcript(language="en", regions=(_region_transcript(0, 0.0), _region_transcript(1, 300.0)))


def test_build_prompt_lists_regions_and_demands_vietnamese(transcript: Transcript):
    prompt = scorer.build_prompt(transcript, top_n=3, min_sec=30, max_sec=60)
    assert "region_index" in prompt
    assert "[REGION 0]" in prompt and "[REGION 1]" in prompt
    assert "Vietnamese" in prompt
    assert "30" in prompt and "60" in prompt


def test_clamp_to_words_snaps_to_word_boundaries(transcript: Transcript):
    region_transcript = transcript.regions[0]
    start, end, words = scorer.clamp_to_words(
        region_transcript.words, 10.3, 41.9, min_sec=30, max_sec=60,
        region=region_transcript.region,
    )
    assert start == pytest.approx(10.0)          # snapped down to a word start
    assert end == pytest.approx(41.9, abs=0.6)   # snapped to the last word end <= 41.9
    assert 30.0 <= end - start <= 60.0
    assert words[0].start >= start and words[-1].end <= end


def test_clamp_to_words_extends_a_too_short_window(transcript: Transcript):
    rt = transcript.regions[0]
    start, end, _ = scorer.clamp_to_words(
        rt.words, 5.0, 12.0, min_sec=30, max_sec=60, region=rt.region
    )
    assert end - start >= 30.0


def test_overlap_ratio_and_dedupe_drops_the_lower_score():
    a = ScoredSegment(0, 90.0, 0, 10.0, 50.0, "hook a", "vi a", ())
    b = ScoredSegment(0, 70.0, 0, 20.0, 60.0, "hook b", "vi b", ())  # 30/40 = 75% overlap
    c = ScoredSegment(0, 80.0, 1, 300.0, 340.0, "hook c", "vi c", ())

    assert scorer.overlap_ratio(a, b) == pytest.approx(0.75)
    ranked = scorer.dedupe_and_rank([a, b, c], top_n=5)
    assert [seg.score for seg in ranked] == [90.0, 80.0]
    assert [seg.rank for seg in ranked] == [1, 2]


def test_dedupe_and_rank_respects_top_n():
    segs = [
        ScoredSegment(0, float(90 - i), 0, i * 100.0, i * 100.0 + 40.0, "h", "v", ())
        for i in range(5)
    ]
    assert len(scorer.dedupe_and_rank(segs, top_n=2)) == 2


async def test_select_clips_maps_llm_output_back_to_timestamps(monkeypatch, transcript: Transcript):
    async def fake_query_llm(prompt, *, backend):
        assert backend == "gemini"
        return [
            {
                "region_index": 1,
                "score": 93,
                "hook_text": "Bạn sẽ bất ngờ",
                "subtitle_text": "Đây là nội dung tiếng Việt.",
                "start_sec": 310.0,
                "end_sec": 350.0,
            }
        ]

    monkeypatch.setattr(scorer, "query_llm", fake_query_llm)
    clips = await scorer.select_clips(transcript, top_n=3, min_sec=30, max_sec=60, backend="gemini")

    assert len(clips) == 1
    clip = clips[0]
    assert clip.rank == 1
    assert clip.region_index == 1
    assert 300.0 <= clip.start_sec < clip.end_sec <= 360.0
    assert 30.0 <= clip.duration <= 60.0
    assert clip.subtitle_text == "Đây là nội dung tiếng Việt."
    assert clip.words and clip.words[0].start >= clip.start_sec


async def test_select_clips_ignores_unknown_region_index(monkeypatch, transcript: Transcript):
    async def fake_query_llm(prompt, *, backend):
        return [
            {"region_index": 99, "score": 99, "hook_text": "x", "subtitle_text": "y",
             "start_sec": 0.0, "end_sec": 40.0},
            {"region_index": 0, "score": 80, "hook_text": "ok", "subtitle_text": "vi",
             "start_sec": 0.0, "end_sec": 40.0},
        ]

    monkeypatch.setattr(scorer, "query_llm", fake_query_llm)
    clips = await scorer.select_clips(transcript, top_n=3, min_sec=30, max_sec=60, backend="gemini")
    assert [c.region_index for c in clips] == [0]


async def test_select_clips_falls_back_to_heuristic(monkeypatch, transcript: Transcript):
    async def failing_query_llm(prompt, *, backend):
        raise LLMUnavailable("no key")

    monkeypatch.setattr(scorer, "query_llm", failing_query_llm)
    clips = await scorer.select_clips(transcript, top_n=2, min_sec=30, max_sec=60, backend="gemini")

    assert len(clips) == 2
    assert all(30.0 <= c.duration <= 60.0 for c in clips)
    assert all(c.subtitle_text for c in clips)


async def test_select_clips_heuristic_backend_skips_llm(monkeypatch, transcript: Transcript):
    async def boom(prompt, *, backend):
        raise AssertionError("LLM must not be called for backend=heuristic")

    monkeypatch.setattr(scorer, "query_llm", boom)
    clips = await scorer.select_clips(transcript, top_n=1, min_sec=30, max_sec=60, backend="heuristic")
    assert len(clips) == 1
