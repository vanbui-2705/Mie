from __future__ import annotations

from app.config import settings
from app.services.ai_pipeline.types import (
    HotRegion,
    RegionTranscript,
    ScoredSegment,
    Transcript,
    Word,
)


def test_word_to_dict_uses_word_key():
    assert Word(1.0, 1.5, "xin").to_dict() == {"start": 1.0, "end": 1.5, "word": "xin"}


def test_hot_region_duration():
    assert HotRegion(index=0, start_sec=10.0, end_sec=40.0, energy=-18.0).duration == 30.0


def test_transcript_all_words_and_text_are_ordered():
    r0 = HotRegion(index=0, start_sec=0.0, end_sec=2.0, energy=-20.0)
    r1 = HotRegion(index=1, start_sec=10.0, end_sec=12.0, energy=-15.0)
    transcript = Transcript(
        language="en",
        regions=(
            RegionTranscript(region=r0, text="hello there", words=(Word(0.0, 0.5, "hello"), Word(0.6, 1.0, "there"))),
            RegionTranscript(region=r1, text="second bit", words=(Word(10.0, 10.4, "second"), Word(10.5, 11.0, "bit"))),
        ),
    )
    assert [w.text for w in transcript.all_words] == ["hello", "there", "second", "bit"]
    assert transcript.total_text == "hello there second bit"


def test_scored_segment_duration():
    seg = ScoredSegment(
        rank=1,
        score=91.0,
        region_index=1,
        start_sec=10.0,
        end_sec=45.0,
        hook_text="Đừng bỏ lỡ",
        subtitle_text="Xin chào các bạn",
        words=(),
    )
    assert seg.duration == 35.0


def test_new_settings_have_expected_defaults():
    assert settings.SCORING_BACKEND == "gemini"
    assert settings.ASR_BACKEND == "local"
    assert settings.ASR_WHISPER_MODEL == "medium"
    assert settings.ASR_COMPUTE_TYPE == "int8"
    assert settings.CLIP_SUBTITLE_FONT == "Be Vietnam Pro"
    assert settings.CLIP_PIPELINE_VERSION == "ai-v1"
    assert settings.FFMPEG_BIN == "ffmpeg"
