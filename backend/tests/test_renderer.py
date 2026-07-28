from __future__ import annotations

from pathlib import Path

from app.services.ai_pipeline.renderer import (
    build_render_command,
    escape_filter_path,
    resolve_font_name,
)

CROP = {
    "source_w": 1920, "source_h": 1080, "crop_w": 608, "crop_h": 1080,
    "x": 656, "y": 0, "path": [], "tracker": "center",
}


def test_escape_filter_path_handles_windows_drive_letters():
    assert escape_filter_path(r"E:\clips\job.ass") == r"E\:/clips/job.ass"


def test_escape_filter_path_leaves_posix_paths_intact():
    assert escape_filter_path("/app/uploads/clips/job.ass") == "/app/uploads/clips/job.ass"


def test_escape_filter_path_escapes_single_quotes():
    assert escape_filter_path("/tmp/it's.ass") == "/tmp/it\\'s.ass"


def test_resolve_font_name_prefers_the_vendored_font(tmp_path: Path):
    (tmp_path / "BeVietnamPro-Bold.ttf").write_bytes(b"\x00")
    assert resolve_font_name(str(tmp_path), "Be Vietnam Pro") == "Be Vietnam Pro"


def test_resolve_font_name_falls_back_when_dir_is_empty(tmp_path: Path):
    assert resolve_font_name(str(tmp_path), "Be Vietnam Pro") == "DejaVu Sans"


def test_resolve_font_name_falls_back_when_dir_is_missing():
    assert resolve_font_name("/definitely/not/here", "Be Vietnam Pro") == "DejaVu Sans"


def test_build_render_command_chains_crop_scale_and_subtitles():
    cmd = build_render_command(
        "in.mp4", "out.mp4", crop=CROP, ass_path="/app/x.ass", font_dir="/app/assets/fonts"
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("crop=608:1080:656:0,")
    assert "scale=1080:1920" in vf
    assert "subtitles='/app/x.ass'" in vf
    assert "fontsdir='/app/assets/fonts'" in vf
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-preset") + 1] == "veryfast"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[-1] == "out.mp4"
