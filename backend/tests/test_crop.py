from __future__ import annotations

import pytest

from app.services.ai_pipeline.crop import compute_crop, smooth_positions


def test_smooth_positions_damps_a_spike():
    raw = [100.0, 100.0, 800.0, 100.0, 100.0]
    smoothed = smooth_positions(raw, alpha=0.3)
    assert len(smoothed) == len(raw)
    assert smoothed[0] == pytest.approx(100.0)
    assert smoothed[2] < 400.0            # the 800 spike is heavily damped
    assert max(smoothed) <= max(raw)


def test_compute_crop_centres_when_there_are_no_detections():
    crop = compute_crop(1920, 1080, [])
    assert crop["crop_h"] == 1080
    assert crop["crop_w"] == 608          # round(1080 * 9 / 16) == 608, already even
    assert crop["x"] == 656               # (1920 - 608) // 2
    assert crop["tracker"] == "center"
    assert crop["y"] == 0


def test_compute_crop_follows_detections_and_clamps_to_frame():
    crop = compute_crop(1920, 1080, [(0.0, 1900.0), (1.0, 1900.0), (2.0, 1900.0)])
    assert crop["x"] + crop["crop_w"] <= 1920
    assert crop["x"] >= 0
    assert crop["tracker"] == "face"
    assert len(crop["path"]) == 3
    assert all(p["x"] >= 0 for p in crop["path"])


def test_compute_crop_on_portrait_source_uses_full_width():
    crop = compute_crop(1080, 1920, [])
    assert crop["crop_w"] == 1080
    assert crop["x"] == 0


def test_compute_crop_path_entries_carry_timestamps():
    crop = compute_crop(1920, 1080, [(0.0, 500.0), (1.5, 700.0)])
    assert [p["t"] for p in crop["path"]] == [0.0, 1.5]
