from __future__ import annotations

import pytest

from app.services.ai_pipeline.subtitle_gen import (
    ass_time,
    build_ass,
    generate_clipspec,
    split_cues,
)
from app.services.ai_pipeline.types import ScoredSegment, Word


def _seconds(stamp: str) -> float:
    hours, minutes, secs = stamp.strip().split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


@pytest.fixture()
def segment() -> ScoredSegment:
    words = tuple(Word(10.0 + i * 0.5, 10.4 + i * 0.5, f"w{i}") for i in range(20))
    return ScoredSegment(
        rank=1,
        score=92.0,
        region_index=0,
        start_sec=10.0,
        end_sec=40.0,
        hook_text="Đừng bỏ lỡ điều này",
        subtitle_text=(
            "Xin chào các bạn, hôm nay chúng ta sẽ nói về một chủ đề rất thú vị. "
            "Hãy cùng tìm hiểu ngay bây giờ nhé."
        ),
        words=words,
    )


def test_ass_time_formats_centiseconds():
    assert ass_time(0.0) == "0:00:00.00"
    assert ass_time(3661.25) == "1:01:01.25"
    assert ass_time(9.999) == "0:00:09.99"


def test_split_cues_respects_char_and_duration_limits(segment: ScoredSegment):
    cues = split_cues(segment.subtitle_text, 0.0, 30.0, max_chars=42, max_cue_sec=3.5)
    assert len(cues) >= 3
    assert all(len(text) <= 42 for _, _, text in cues)
    assert all(end - start <= 3.5 + 1e-6 for start, end, _ in cues)
    assert cues[0][0] == pytest.approx(0.0)
    assert cues[-1][1] <= 30.0 + 1e-6
    # Cues must be strictly ordered and non-overlapping.
    for prev, curr in zip(cues, cues[1:]):
        assert prev[1] <= curr[0] + 1e-6


def test_split_cues_on_empty_text_returns_nothing():
    assert split_cues("   ", 0.0, 10.0) == []


def test_build_ass_has_header_style_and_relative_timings(segment: ScoredSegment):
    ass = build_ass(segment, font_name="Be Vietnam Pro", video_w=1080, video_h=1920)
    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Be Vietnam Pro" in ass
    assert "Style: Hook," in ass
    assert "Style: Body," in ass
    assert "Đừng bỏ lỡ điều này" in ass
    # Timings are clip-relative (the burn runs on the already-cut file).
    assert "Dialogue: 0,0:00:00.00" in ass
    # The segment spans 10.0-40.0 in the source; every timing must land inside
    # 0..30 instead. (A substring check for "0:00:10." cannot express this —
    # 10.5s is a legitimate *relative* cue time in a 30s clip.)
    events = ass.split("[Events]")[1]
    stamps = [
        _seconds(part)
        for line in events.splitlines()
        if line.startswith("Dialogue:")
        for part in line.split(",")[1:3]
    ]
    assert stamps
    assert all(0.0 <= s <= 30.0 for s in stamps), stamps


def test_generate_clipspec_v2_shape(segment: ScoredSegment):
    crop = {
        "source_w": 1920, "source_h": 1080, "crop_w": 608, "crop_h": 1080,
        "x": 656, "y": 0, "path": [{"t": 0.0, "x": 656}], "tracker": "face",
    }
    spec = generate_clipspec(
        segment,
        video_url="/uploads/clips/u1/job_clip_1.mp4",
        crop=crop,
        ass_relative_path="/uploads/clips/u1/job_clip_1.ass",
    )
    assert spec["version"] == 2
    assert spec["video_url"] == "/uploads/clips/u1/job_clip_1.mp4"
    assert spec["subtitle_url"] == "/uploads/clips/u1/job_clip_1.ass"
    assert spec["duration"] == pytest.approx(30.0)
    assert spec["hook_text"] == "Đừng bỏ lỡ điều này"
    assert spec["crop"]["tracker"] == "face"
    assert spec["style"]["font"] == "Be Vietnam Pro"
    assert spec["words"][0] == {"start": 0.0, "end": pytest.approx(0.4), "word": "w0"}
    assert spec["cues"] and spec["cues"][0]["text"]
