from __future__ import annotations

import pytest

from app.services.ai_pipeline.cutter import build_cut_command, snap_cut_points


def test_build_cut_command_seeks_before_input():
    cmd = build_cut_command("in.mp4", "out.mp4", 12.0, 52.0)
    assert cmd[0] == "ffmpeg"
    ss = cmd.index("-ss")
    i = cmd.index("-i")
    assert ss < i, "-ss must precede -i for fast seeking"
    assert cmd[ss + 1] == "12.000"
    assert cmd[cmd.index("-t") + 1] == "40.000"
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "out.mp4"


def test_snap_cut_points_prefers_a_keyframe_inside_a_silence():
    keyframes = [0.0, 8.0, 10.0, 12.0, 50.0, 52.0]
    silences = [(9.5, 10.5), (51.5, 53.0)]
    start, end = snap_cut_points(
        11.0, 52.2, keyframes, silences, max_shift=2.0, min_sec=30, max_sec=60
    )
    assert start == pytest.approx(10.0)   # keyframe at 10.0 sits inside the 9.5-10.5 silence
    assert end == pytest.approx(51.5)     # end pulled back to the start of the next silence


def test_snap_cut_points_falls_back_to_nearest_keyframe():
    keyframes = [0.0, 9.0, 45.0]
    start, end = snap_cut_points(
        10.0, 45.5, keyframes, [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert start == pytest.approx(9.0)
    assert end == pytest.approx(45.5)


def test_snap_cut_points_ignores_keyframes_beyond_max_shift():
    keyframes = [0.0, 4.0]
    start, end = snap_cut_points(
        20.0, 60.0, keyframes, [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert start == pytest.approx(20.0)


def test_snap_cut_points_enforces_the_length_band():
    start, end = snap_cut_points(
        10.0, 200.0, [10.0], [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert end - start == pytest.approx(60.0)

    start, end = snap_cut_points(
        10.0, 15.0, [10.0], [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert end - start == pytest.approx(30.0)


def test_snap_cut_points_never_goes_negative():
    start, _ = snap_cut_points(0.5, 40.0, [], [], max_shift=2.0, min_sec=30, max_sec=60)
    assert start >= 0.0
