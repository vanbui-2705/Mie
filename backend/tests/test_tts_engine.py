from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.ai_pipeline import scheduling, tts_engine
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


# ─── concurrency ──────────────────────────────────────────────────────────────

@pytest.fixture()
def concurrent_tts(monkeypatch, tmp_path: Path):
    """Records how many syntheses were in flight at once."""
    state = {"live": 0, "peak": 0, "order": []}

    async def fake_synthesize_cue(text, out_path, *, voice):
        state["live"] += 1
        state["peak"] = max(state["peak"], state["live"])
        state["order"].append(text)
        await asyncio.sleep(0.02)
        Path(out_path).write_bytes(b"mp3")
        state["live"] -= 1
        return True

    async def fake_probe_duration(path):
        return 1.0

    async def fake_mix_tracks(parts, out_path, *, total_sec):
        state["parts"] = list(parts)
        Path(out_path).write_bytes(b"m4a")
        return out_path

    monkeypatch.setattr(tts_engine, "synthesize_cue", fake_synthesize_cue)
    monkeypatch.setattr(tts_engine, "probe_duration", fake_probe_duration)
    monkeypatch.setattr(tts_engine, "mix_tracks", fake_mix_tracks)
    monkeypatch.setattr(scheduling.settings, "FLOW_TTS_SLOTS", 4)
    scheduling.reset_slots()
    return state


async def test_build_voice_track_speaks_cues_concurrently(concurrent_tts, tmp_path: Path):
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(8)]
    out = await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=8.0, work_dir=tmp_path, base="job",
    )
    assert out is not None
    assert concurrent_tts["peak"] > 1


async def test_build_voice_track_keeps_cue_order(concurrent_tts, tmp_path: Path):
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(8)]
    await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=8.0, work_dir=tmp_path, base="job",
    )
    # Concurrency must not reorder the mix: part i starts at cue i's timestamp.
    starts = [start for _path, start, _tempo in concurrent_tts["parts"]]
    assert starts == sorted(starts)
    assert starts == [float(i) for i in range(8)]


async def test_build_voice_track_respects_the_tts_slot_limit(monkeypatch, concurrent_tts, tmp_path: Path):
    monkeypatch.setattr(scheduling.settings, "FLOW_TTS_SLOTS", 2)
    scheduling.reset_slots()
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(8)]
    await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=8.0, work_dir=tmp_path, base="job",
    )
    assert concurrent_tts["peak"] == 2


async def test_build_voice_track_skips_a_failing_cue(monkeypatch, concurrent_tts, tmp_path: Path):
    async def flaky(text, out_path, *, voice):
        if text == "cue 2":
            return False
        Path(out_path).write_bytes(b"mp3")
        return True

    monkeypatch.setattr(tts_engine, "synthesize_cue", flaky)
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(4)]
    await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=4.0, work_dir=tmp_path, base="job",
    )
    starts = [start for _path, start, _tempo in concurrent_tts["parts"]]
    assert starts == [0.0, 1.0, 3.0]


async def test_synthesize_scene_tracks_runs_scenes_concurrently(concurrent_tts, tmp_path: Path):
    tracks = await tts_engine.synthesize_scene_tracks(
        [f"scene {i}" for i in range(6)],
        voice_id="vi-female", work_dir=tmp_path, base="gen",
    )
    assert len(tracks) == 6
    assert concurrent_tts["peak"] > 1
    assert all(duration == 1.0 for _path, duration in tracks)
