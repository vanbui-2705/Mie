"""Shared value types for the Flow Studio AI pipeline.

Every stage exchanges these frozen dataclasses instead of loose dicts so a
misspelled key fails at import/attribute time rather than deep in ffmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Word:
    """One ASR word with absolute (whole-source) timestamps in seconds."""

    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        # Key is "word" (not "text") to stay compatible with the clipspec the
        # frontend already reads.
        return {"start": self.start, "end": self.end, "word": self.text}


@dataclass(frozen=True)
class HotRegion:
    """A candidate span found by the tier-1 audio prefilter."""

    index: int
    start_sec: float
    end_sec: float
    energy: float  # mean dBFS over the region; higher = louder

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


@dataclass(frozen=True)
class RegionTranscript:
    region: HotRegion
    text: str
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Transcript:
    language: str
    regions: tuple[RegionTranscript, ...]

    @property
    def all_words(self) -> tuple[Word, ...]:
        return tuple(w for r in self.regions for w in r.words)

    @property
    def total_text(self) -> str:
        return " ".join(r.text for r in self.regions if r.text)


@dataclass(frozen=True)
class ScoredSegment:
    """A clip the scorer selected, with Vietnamese copy attached."""

    rank: int
    score: float
    region_index: int
    start_sec: float
    end_sec: float
    hook_text: str
    subtitle_text: str
    words: tuple[Word, ...]

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": self.score,
            "region_index": self.region_index,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "hook_text": self.hook_text,
            "subtitle_text": self.subtitle_text,
            "words": [w.to_dict() for w in self.words],
        }
