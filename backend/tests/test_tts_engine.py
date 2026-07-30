from __future__ import annotations

import sys
from types import SimpleNamespace

from app.config import settings
from app.services.ai_pipeline.renderer import build_render_command
from app.services.ai_pipeline.tts_engine import (
    VOICES,
    build_mix_command,
    resolve_voice,
    synthesize_cue,
    tempo_for,
)

CROP = {
    "source_w": 1920, "source_h": 1080, "crop_w": 608, "crop_h": 1080,
    "x": 656, "y": 0, "path": [], "tracker": "center",
}


def test_resolve_voice_maps_the_ui_id_to_a_backend_voice():
    assert resolve_voice("vi-male") == VOICES["vi-male"]


def test_resolve_voice_falls_back_on_an_unknown_id():
    assert resolve_voice("klingon") == VOICES["vi-female"]
    assert resolve_voice(None) == VOICES["vi-female"]


def test_tempo_for_leaves_speech_that_already_fits_alone():
    # Never slow speech down to fill a gap — silence sounds better than drawl.
    assert tempo_for(2.0, 3.0, cap=1.6) == 1.0


def test_tempo_for_speeds_up_an_overlong_line():
    assert tempo_for(3.0, 2.0, cap=1.6) == 1.5


def test_tempo_for_respects_the_cap():
    assert tempo_for(10.0, 2.0, cap=1.6) == 1.6


def test_tempo_for_handles_degenerate_windows():
    assert tempo_for(0.0, 3.0, cap=1.6) == 1.0
    assert tempo_for(3.0, 0.0, cap=1.6) == 1.0


def test_build_mix_command_delays_each_cue_to_its_timestamp():
    cmd = build_mix_command(
        [("a.mp3", 0.0, 1.0), ("b.mp3", 2.5, 1.25)], "out.m4a", total_sec=10.0
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[0:a]adelay=0|0[a0]" in graph
    assert "[1:a]atempo=1.250,adelay=2500|2500[a1]" in graph
    # normalize=0: mixing N cues must not duck every one of them to 1/N.
    assert (
        "[a0][a1]amix=inputs=2:normalize=0:dropout_transition=0,"
        "apad=whole_dur=10.000[out]"
    ) in graph
    assert cmd[cmd.index("-t") + 1] == "10.000"
    assert cmd[-1] == "out.m4a"


async def test_failed_tts_removes_a_partial_file(tmp_path, monkeypatch):
    class Communicate:
        def __init__(self, text, voice):
            pass

        async def save(self, out_path):
            from pathlib import Path

            Path(out_path).write_bytes(b"partial")
            raise TimeoutError()

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=Communicate))
    monkeypatch.setattr(settings, "TTS_BACKEND", "edge")
    monkeypatch.setattr(settings, "TTS_MAX_RETRIES", 0)
    output = tmp_path / "cue.mp3"

    assert await synthesize_cue("xin chao", str(output), voice=VOICES["vi-female"]) is False
    assert not output.exists()


def test_render_command_without_voice_keeps_the_source_audio():
    cmd = build_render_command(
        "in.mp4", "out.mp4", crop=CROP, ass_path="/app/x.ass", font_dir="/app/fonts"
    )
    assert "-map" not in cmd


def test_render_command_with_voice_replaces_the_audio_stream():
    cmd = build_render_command(
        "in.mp4", "out.mp4", crop=CROP, ass_path="/app/x.ass", font_dir="/app/fonts",
        audio_path="voice.m4a",
    )
    assert cmd[cmd.index("-i") + 1] == "in.mp4"
    assert "voice.m4a" in cmd
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "1:a:0"
    assert "-shortest" in cmd
    # The video filter chain must survive the extra input.
    assert "subtitles='/app/x.ass'" in cmd[cmd.index("-vf") + 1]
