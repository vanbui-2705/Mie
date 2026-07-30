"""Prompt -> scene script for Gen video.

The LLM writes Vietnamese narration (what the voice reads and the subtitle
shows) plus an ENGLISH image query per scene, because stock libraries index in
English and a Vietnamese query returns almost nothing.

Scene durations are NOT taken from the model: the narration is spoken first and
the measured audio decides how long its scene stays on screen. The `seconds`
the model suggests is only used to keep the script roughly the right length.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.ai_pipeline.llm_clients import LLMUnavailable, query_llm

logger = logging.getLogger("flowmeta.ai_pipeline.script")

MIN_SCENES = 2
MAX_SCENES = 12
_WORDS_PER_SECOND = 2.6  # comfortable Vietnamese narration pace


_PROMPT = """You write short vertical videos (9:16) for Vietnamese social media.

Topic: {prompt}
{avoid}Target length: about {duration} seconds, so roughly {words} Vietnamese words in total.

Write {scenes} scenes. For each scene:
- `narration`: Vietnamese, spoken aloud, one or two sentences, natural and idiomatic.
  No emoji, no markdown, no stage directions - only what the voice says.
- `image_query`: 2-5 ENGLISH words naming a concrete, photographable subject for
  stock footage of this scene. No abstractions ("success", "future"), no text.
- `seconds`: how long this scene should stay on screen.

Also write `title`: an on-screen hook in Vietnamese, at most 8 words.

Return ONLY a JSON object, no prose, no markdown fences:
{{"title": string, "scenes": [{{"narration": string, "image_query": string, "seconds": number}}]}}
"""


@dataclass(frozen=True)
class Scene:
    narration: str
    image_query: str
    seconds: float


@dataclass(frozen=True)
class VideoScript:
    title: str
    scenes: tuple[Scene, ...]

    @property
    def narrations(self) -> list[str]:
        return [scene.narration for scene in self.scenes]


def scene_count_for(duration_sec: float) -> int:
    """One scene per ~6 seconds — long enough to read, short enough to move."""
    return max(MIN_SCENES, min(MAX_SCENES, int(round(duration_sec / 6.0))))


def build_prompt(prompt: str, *, duration_sec: float, negative_prompt: str = "") -> str:
    scenes = scene_count_for(duration_sec)
    avoid = f"Avoid: {negative_prompt.strip()}\n" if negative_prompt.strip() else ""
    return _PROMPT.format(
        prompt=prompt.strip(),
        avoid=avoid,
        duration=int(duration_sec),
        words=int(duration_sec * _WORDS_PER_SECOND),
        scenes=scenes,
    )


def parse_script(payload: object, *, duration_sec: float) -> VideoScript:
    """Turn the model's JSON into a script, dropping anything unusable."""
    if not isinstance(payload, dict):
        raise LLMUnavailable("script response was not a JSON object")

    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list):
        raise LLMUnavailable("script response had no scenes array")

    scenes: list[Scene] = []
    for item in raw_scenes[:MAX_SCENES]:
        if not isinstance(item, dict):
            continue
        narration = str(item.get("narration") or "").strip()
        if not narration:
            continue
        query = str(item.get("image_query") or "").strip() or "abstract background"
        try:
            seconds = float(item.get("seconds", 0) or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        scenes.append(Scene(narration=narration, image_query=query, seconds=max(0.0, seconds)))

    if not scenes:
        raise LLMUnavailable("script response contained no usable scene")

    title = str(payload.get("title") or "").strip()
    logger.info(
        "script: %d scene(s), %d chars of narration (asked for ~%ds)",
        len(scenes), sum(len(s.narration) for s in scenes), int(duration_sec),
    )
    return VideoScript(title=title, scenes=tuple(scenes))


async def write_script(
    prompt: str, *, duration_sec: float, backend: str, negative_prompt: str = ""
) -> VideoScript:
    payload = await query_llm(
        build_prompt(prompt, duration_sec=duration_sec, negative_prompt=negative_prompt),
        backend=backend,
    )
    return parse_script(payload, duration_sec=duration_sec)
