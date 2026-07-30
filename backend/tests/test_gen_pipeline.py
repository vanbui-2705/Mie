from __future__ import annotations

import pytest

from app.services.ai_pipeline.llm_clients import LLMUnavailable
from app.services.ai_pipeline.script_writer import (
    Scene,
    VideoScript,
    build_prompt,
    parse_script,
    scene_count_for,
)
from app.services.ai_pipeline.slideshow import (
    FPS,
    OUTPUT_H,
    OUTPUT_W,
    build_slideshow_command,
    scene_filter,
    zoom_expression,
)
from app.services.ai_pipeline.stock_media import (
    backdrop_source,
    gradient_command,
    pick_commons_photo_url,
    pick_photo_url,
)
from app.services.gen_runner import MIN_SCENE_SEC, build_cues, lay_out_scenes


def _script(*narrations: str) -> VideoScript:
    return VideoScript(
        title="Hook",
        scenes=tuple(Scene(narration=n, image_query="morning coffee", seconds=5.0)
                     for n in narrations),
    )


# ─── script_writer ────────────────────────────────────────────────────────────

def test_scene_count_scales_with_duration_inside_the_bounds():
    assert scene_count_for(5) == 2      # floor
    assert scene_count_for(30) == 5
    assert scene_count_for(600) == 12   # ceiling


def test_build_prompt_includes_the_topic_and_omits_an_empty_avoid_line():
    text = build_prompt("thói quen buổi sáng", duration_sec=30)
    assert "thói quen buổi sáng" in text
    assert "Avoid:" not in text


def test_build_prompt_passes_the_negative_prompt_through():
    text = build_prompt("x" * 12, duration_sec=30, negative_prompt="chính trị")
    assert "Avoid: chính trị" in text


def test_parse_script_keeps_usable_scenes_and_drops_the_rest():
    script = parse_script(
        {
            "title": " Ba thói quen ",
            "scenes": [
                {"narration": "Câu một.", "image_query": "sunrise city", "seconds": 4},
                {"narration": "   ", "image_query": "x", "seconds": 4},   # empty
                "not a dict",                                              # wrong type
                {"narration": "Câu hai.", "seconds": "bad"},               # bad number
            ],
        },
        duration_sec=30,
    )
    assert script.title == "Ba thói quen"
    assert script.narrations == ["Câu một.", "Câu hai."]
    # A scene with no query still gets a renderable one.
    assert script.scenes[1].image_query == "abstract background"
    assert script.scenes[1].seconds == 0.0


@pytest.mark.parametrize("payload", ["nope", {}, {"scenes": []}, {"scenes": [{}]}])
def test_parse_script_rejects_unusable_responses(payload):
    with pytest.raises(LLMUnavailable):
        parse_script(payload, duration_sec=30)


# ─── timeline ─────────────────────────────────────────────────────────────────

def test_lay_out_scenes_follows_the_measured_voice_plus_a_breath():
    timeline = lay_out_scenes([3.0, 4.0], [5.0, 5.0], pad_sec=0.4)
    assert timeline.durations == (3.4, 4.4)
    assert timeline.starts == (0.0, 3.4)
    assert timeline.total == pytest.approx(7.8)


def test_lay_out_scenes_falls_back_to_the_script_when_tts_failed():
    # A scene with no audio must still occupy the screen, or the images shift.
    timeline = lay_out_scenes([0.0, 4.0], [6.0, 5.0], pad_sec=0.4)
    assert timeline.durations == (6.0, 4.4)


def test_lay_out_scenes_never_produces_a_flash_frame():
    timeline = lay_out_scenes([0.1, 0.0], [0.0, 0.0], pad_sec=0.4)
    assert timeline.durations == (MIN_SCENE_SEC, MIN_SCENE_SEC)


def test_build_cues_places_every_scene_inside_its_own_window():
    timeline = lay_out_scenes([3.0, 3.0], [3.0, 3.0], pad_sec=0.0)
    cues = build_cues(_script("Câu một.", "Câu hai."), timeline)
    assert cues[0][0] == 0.0
    assert cues[-1][1] <= timeline.total + 0.001
    # Cues never run backwards across the scene boundary.
    assert all(a[1] <= b[0] + 0.001 for a, b in zip(cues, cues[1:]))


def test_build_cues_stops_at_the_timeline_it_was_given():
    timeline = lay_out_scenes([3.0], [3.0], pad_sec=0.0)
    cues = build_cues(_script("Câu một.", "Câu hai."), timeline)
    assert cues and all(end <= timeline.total + 0.001 for _s, end, _t in cues)


# ─── slideshow ────────────────────────────────────────────────────────────────

def test_zoom_expression_alternates_direction():
    assert zoom_expression(30, zoom_in=True).startswith("min(zoom+")
    assert zoom_expression(30, zoom_in=False).startswith("max(")


def test_scene_filter_holds_the_still_for_the_whole_scene():
    chain = scene_filter(1, 2.0)
    assert f"d={2 * FPS}" in chain
    assert f"s={OUTPUT_W}x{OUTPUT_H}" in chain
    assert chain.startswith("[1:v]") and chain.endswith("[v1]")
    # setsar=1 or the player letterboxes a 9:16 clip as if it were 16:9.
    assert "setsar=1" in chain


def test_build_slideshow_command_concats_every_scene_and_burns_subtitles():
    cmd = build_slideshow_command(
        [("a.jpg", 3.0), ("b.jpg", 2.0)],
        "out.mp4",
        audio_path=None,
        ass_path="/app/x.ass",
        font_dir="/app/fonts",
        escape_path=lambda p: p,
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[v0][v1]concat=n=2:v=1:a=0[cat]" in graph
    assert "[cat]subtitles='/app/x.ass'" in graph
    assert cmd[cmd.index("-map") + 1] == "[out]"
    assert cmd.count("-loop") == 2
    assert "-c:a" not in cmd
    assert cmd[-1] == "out.mp4"


def test_build_slideshow_command_maps_the_voice_track_after_the_images():
    cmd = build_slideshow_command(
        [("a.jpg", 3.0), ("b.jpg", 2.0)],
        "out.mp4",
        audio_path="voice.m4a",
        ass_path="/app/x.ass",
        font_dir="/app/fonts",
        escape_path=lambda p: p,
    )
    # Two images occupy inputs 0 and 1, so the audio is input 2.
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "2:a:0"
    assert "-shortest" not in cmd
    assert cmd[cmd.index("-t", cmd.index("-filter_complex")) + 1] == "5.000"


def test_build_slideshow_command_rejects_an_empty_script():
    with pytest.raises(ValueError):
        build_slideshow_command(
            [], "out.mp4", audio_path=None, ass_path="x.ass", font_dir="f",
            escape_path=lambda p: p,
        )


# ─── stock media ──────────────────────────────────────────────────────────────

def test_pick_photo_url_prefers_the_portrait_rendition():
    url = pick_photo_url(
        {"photos": [{"src": {"large": "https://x/l.jpg", "portrait": "https://x/p.jpg"}}]}
    )
    assert url == "https://x/p.jpg"


def test_pick_photo_url_falls_back_through_the_quality_order():
    assert pick_photo_url({"photos": [{"src": {"original": "https://x/o.jpg"}}]}) == "https://x/o.jpg"


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"photos": []}, {"photos": ["x"]}, {"photos": [{"src": {}}]},
     {"photos": [{"src": {"portrait": "http://insecure/p.jpg"}}]}],
)
def test_pick_photo_url_returns_none_when_there_is_nothing_usable(payload):
    assert pick_photo_url(payload) is None


def test_pick_commons_photo_prefers_a_portrait_jpeg():
    payload = {
        "query": {
            "pages": [
                {
                    "imageinfo": [{
                        "mime": "image/jpeg",
                        "width": 1600,
                        "height": 900,
                        "thumburl": "https://upload.wikimedia.org/landscape.jpg",
                    }]
                },
                {
                    "imageinfo": [{
                        "mime": "image/jpeg",
                        "width": 900,
                        "height": 1600,
                        "thumburl": "https://upload.wikimedia.org/portrait.jpg",
                    }]
                },
            ]
        }
    }

    assert pick_commons_photo_url(payload) == "https://upload.wikimedia.org/portrait.jpg"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"query": {"pages": []}},
        {"query": {"pages": [{"imageinfo": [{"mime": "image/png", "url": "https://x/a.png"}]}]}},
        {"query": {"pages": [{"imageinfo": [{"mime": "image/jpeg", "url": "http://x/a.jpg"}]}]}},
    ],
)
def test_pick_commons_photo_returns_none_without_a_safe_jpeg(payload):
    assert pick_commons_photo_url(payload) is None


def test_backdrop_source_is_derived_from_the_generated_filename():
    assert backdrop_source("/tmp/job_pexels_0_a.jpg") == "pexels"
    assert backdrop_source("/tmp/job_commons_0_a.jpg") == "wikimedia_commons"
    assert backdrop_source("/tmp/job_bg_0.png") == "generated_gradient"


def test_gradient_command_is_deterministic_per_scene_index():
    first = gradient_command("a.png", index=0)
    assert first == gradient_command("a.png", index=0)
    # Adjacent scenes must not share a colour pair.
    assert gradient_command("a.png", index=1) != first
    assert first[-1] == "a.png"
