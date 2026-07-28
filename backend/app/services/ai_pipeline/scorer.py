"""Clip selection: rubric scoring + Vietnamese translation.

The LLM never sees raw timestamps to echo back verbatim. It is given numbered
regions and returns `region_index` plus a rough start/end; this module snaps
those to real word boundaries inside that region. That removes the fragile
"find the snippet's first word anywhere in the transcript" mapping the v0 code
used, which could silently match a repeated word in a different part of the video.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.ai_pipeline.llm_clients import LLMUnavailable, query_llm
from app.services.ai_pipeline.types import HotRegion, ScoredSegment, Transcript, Word

logger = logging.getLogger("flowmeta.ai_pipeline.scorer")

OVERLAP_DROP_RATIO = 0.5

_RUBRIC = """You are a short-form video editor. Score candidate segments of a longer video.

Rubric (0-100, weighted):
- Hook strength in the first 3 seconds (30)
- Self-contained: understandable without the rest of the video (25)
- Emotional intensity or surprise (20)
- Clear payoff or conclusion inside the segment (15)
- Quotability / shareability (10)

Rules:
- Pick at most {top_n} segments, each from a DIFFERENT region when possible.
- Each segment must last between {min_sec} and {max_sec} seconds.
- start_sec and end_sec are ABSOLUTE seconds and must fall inside the region you name.
- The source audio may be in ANY language. `hook_text` and `subtitle_text` MUST be
  natural, idiomatic Vietnamese - translate, do not transliterate, and do not copy
  the source language.
- `hook_text`: at most 8 Vietnamese words, an on-screen title.
- `subtitle_text`: the full Vietnamese spoken content of the segment, punctuated.

Return ONLY a JSON array, no prose, no markdown fences. Each item:
{{"region_index": int, "score": number, "hook_text": string, "subtitle_text": string,
  "start_sec": number, "end_sec": number}}
"""


def build_prompt(transcript: Transcript, *, top_n: int, min_sec: float, max_sec: float) -> str:
    header = _RUBRIC.format(top_n=top_n, min_sec=int(min_sec), max_sec=int(max_sec))
    blocks = []
    for rt in transcript.regions:
        blocks.append(
            f"[REGION {rt.region.index}] {rt.region.start_sec:.1f}s - {rt.region.end_sec:.1f}s\n{rt.text}"
        )
    return f"{header}\nSource language: {transcript.language}\n\n" + "\n\n".join(blocks)


def clamp_to_words(
    words: tuple[Word, ...],
    start: float,
    end: float,
    *,
    min_sec: float,
    max_sec: float,
    region: HotRegion,
) -> tuple[float, float, tuple[Word, ...]]:
    """Snap [start, end] to word boundaries inside `region` and enforce the length band."""
    start = max(region.start_sec, min(float(start), region.end_sec))
    end = max(region.start_sec, min(float(end), region.end_sec))
    if end <= start:
        end = min(region.end_sec, start + min_sec)

    if end - start < min_sec:
        end = min(region.end_sec, start + min_sec)
        start = max(region.start_sec, end - min_sec)
    if end - start > max_sec:
        end = start + max_sec

    if words:
        starts = [w.start for w in words if w.start <= start]
        start = max(starts) if starts else words[0].start
        ends = [w.end for w in words if w.end <= end]
        end = max(ends) if ends else min(region.end_sec, start + min_sec)
        if end - start < min_sec:
            later = [w.end for w in words if w.end >= start + min_sec]
            end = later[0] if later else min(region.end_sec, start + min_sec)
        if end - start > max_sec:
            capped = [w.end for w in words if start < w.end <= start + max_sec]
            end = capped[-1] if capped else start + max_sec

    selected = tuple(w for w in words if w.start >= start - 1e-6 and w.end <= end + 1e-6)
    return round(start, 3), round(end, 3), selected


def overlap_ratio(a: ScoredSegment, b: ScoredSegment) -> float:
    """Intersection over the *shorter* segment. 1.0 means fully contained."""
    intersection = min(a.end_sec, b.end_sec) - max(a.start_sec, b.start_sec)
    if intersection <= 0:
        return 0.0
    shortest = min(a.duration, b.duration)
    return intersection / shortest if shortest > 0 else 0.0


def dedupe_and_rank(candidates: list[ScoredSegment], top_n: int) -> list[ScoredSegment]:
    """Highest score wins; anything overlapping a kept segment by >50% is dropped."""
    kept: list[ScoredSegment] = []
    for candidate in sorted(candidates, key=lambda s: s.score, reverse=True):
        if any(overlap_ratio(candidate, k) > OVERLAP_DROP_RATIO for k in kept):
            continue
        kept.append(candidate)
        if len(kept) >= top_n:
            break
    return [
        ScoredSegment(
            rank=i + 1,
            score=seg.score,
            region_index=seg.region_index,
            start_sec=seg.start_sec,
            end_sec=seg.end_sec,
            hook_text=seg.hook_text,
            subtitle_text=seg.subtitle_text,
            words=seg.words,
        )
        for i, seg in enumerate(kept)
    ]


def heuristic_select(
    transcript: Transcript, *, top_n: int, min_sec: float, max_sec: float
) -> list[ScoredSegment]:
    """Tier-2 fallback: no LLM, no network. Ranks regions by audio energy and
    word density and takes the densest window. Text stays in the source
    language - flag it so the UI can show 'translation unavailable'."""
    candidates: list[ScoredSegment] = []
    for rt in transcript.regions:
        if not rt.words:
            continue
        density = len(rt.words) / max(rt.region.duration, 1.0)
        score = max(0.0, min(100.0, 50.0 + rt.region.energy + density * 10.0))
        start, end, words = clamp_to_words(
            rt.words,
            rt.region.start_sec,
            rt.region.start_sec + max_sec,
            min_sec=min_sec,
            max_sec=max_sec,
            region=rt.region,
        )
        text = " ".join(w.text for w in words) or rt.text
        candidates.append(
            ScoredSegment(
                rank=0,
                score=round(score, 2),
                region_index=rt.region.index,
                start_sec=start,
                end_sec=end,
                hook_text=text[:60],
                subtitle_text=text,
                words=words,
            )
        )
    return dedupe_and_rank(candidates, top_n)


def _coerce_item(item: Any, by_index: dict[int, Any], min_sec: float, max_sec: float):
    if not isinstance(item, dict):
        return None
    try:
        region_index = int(item["region_index"])
    except (KeyError, TypeError, ValueError):
        return None
    rt = by_index.get(region_index)
    if rt is None:
        logger.warning("LLM referenced unknown region_index=%s, dropping", region_index)
        return None

    try:
        score = float(item.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    start, end, words = clamp_to_words(
        rt.words,
        item.get("start_sec", rt.region.start_sec),
        item.get("end_sec", rt.region.start_sec + max_sec),
        min_sec=min_sec,
        max_sec=max_sec,
        region=rt.region,
    )
    subtitle = str(item.get("subtitle_text") or "").strip() or rt.text
    hook = str(item.get("hook_text") or "").strip() or subtitle[:60]
    return ScoredSegment(
        rank=0,
        score=round(score, 2),
        region_index=region_index,
        start_sec=start,
        end_sec=end,
        hook_text=hook,
        subtitle_text=subtitle,
        words=words,
    )


async def select_clips(
    transcript: Transcript,
    *,
    top_n: int,
    min_sec: float,
    max_sec: float,
    backend: str,
) -> list[ScoredSegment]:
    """Pick the best `top_n` clips. Falls back to the heuristic tier whenever the
    LLM is unavailable or returns nothing usable."""
    if not transcript.regions:
        logger.warning("scorer received an empty transcript")
        return []

    if (backend or "").strip().lower() == "heuristic":
        return heuristic_select(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)

    prompt = build_prompt(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)
    try:
        payload = await query_llm(prompt, backend=backend)
    except LLMUnavailable as exc:
        logger.warning("scoring backend %s unavailable (%s); using heuristic tier", backend, exc)
        return heuristic_select(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)

    items = payload if isinstance(payload, list) else payload.get("clips", []) if isinstance(payload, dict) else []
    by_index = {rt.region.index: rt for rt in transcript.regions}
    candidates = [c for c in (_coerce_item(i, by_index, min_sec, max_sec) for i in items) if c]

    if not candidates:
        logger.warning("LLM returned no usable candidates; using heuristic tier")
        return heuristic_select(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)

    return dedupe_and_rank(candidates, top_n)


async def score_and_translate_clips(
    transcript: dict[str, Any],
    top_n: int = 3,
    min_sec: int = 30,
    max_sec: int = 60,
    backend: str = "gemini",
) -> list[dict[str, Any]]:
    """Legacy dict-in/dict-out wrapper over `select_clips`.

    Kept only so the not-yet-rewired `clip_runner` keeps importing; it is
    deleted when the runner moves to `select_clips`.
    """
    words = tuple(
        Word(start=float(w["start"]), end=float(w["end"]), text=str(w["word"]))
        for w in transcript.get("words") or []
    )
    end_sec = words[-1].end if words else float(max_sec)
    region = HotRegion(index=0, start_sec=0.0, end_sec=end_sec, energy=0.0)
    from app.services.ai_pipeline.types import RegionTranscript

    whole = Transcript(
        language=transcript.get("language") or "unknown",
        regions=(RegionTranscript(region=region, text=transcript.get("text") or "", words=words),),
    )
    clips = await select_clips(
        whole, top_n=top_n, min_sec=min_sec, max_sec=max_sec, backend=backend
    )
    return [
        {
            "rank": c.rank,
            "score": int(c.score),
            "start_sec": c.start_sec,
            "end_sec": c.end_sec,
            "hook_text": c.hook_text,
            "translated_text": c.subtitle_text,
            "original_words": [w.to_dict() for w in c.words],
        }
        for c in clips
    ]
