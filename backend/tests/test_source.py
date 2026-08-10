from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from app.models.clip_models import ClipSourceType
from app.services.ai_pipeline import source as source_mod
from app.services.ai_pipeline.source import (
    SourceUnavailable,
    await_video,
    build_audio_download_command,
    build_download_command,
    resolve_source,
    resolve_source_audio_first,
    sha256_file,
)


def test_sha256_file_matches_hashlib(tmp_path: Path):
    path = tmp_path / "blob.bin"
    payload = b"flowmeta" * 5000
    path.write_bytes(payload)
    assert sha256_file(str(path)) == hashlib.sha256(payload).hexdigest()


def test_build_download_command_is_argument_list_not_shell():
    cmd = build_download_command("https://youtu.be/abc", "/tmp/out.mp4")
    assert cmd[0] == "yt-dlp"
    assert "--no-playlist" in cmd
    assert cmd[cmd.index("-o") + 1] == "/tmp/out.mp4"
    assert cmd[-1] == "https://youtu.be/abc"
    assert all(isinstance(part, str) for part in cmd)


async def test_resolve_source_upload_returns_the_path_untouched(tmp_path: Path):
    src = tmp_path / "uploaded.mp4"
    src.write_bytes(b"video")
    path, is_temp = await resolve_source(
        ClipSourceType.UPLOAD, str(src), tmp_path, "job-1"
    )
    assert path == str(src)
    assert is_temp is False


async def test_resolve_source_upload_missing_file_raises(tmp_path: Path):
    with pytest.raises(SourceUnavailable):
        await resolve_source(ClipSourceType.UPLOAD, str(tmp_path / "nope.mp4"), tmp_path, "job-1")


async def test_resolve_source_link_downloads_and_marks_temporary(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"downloaded")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)

    path, is_temp = await resolve_source(
        ClipSourceType.LINK, "https://youtu.be/abc", tmp_path, "job-1"
    )
    assert is_temp is True
    assert Path(path).exists()
    assert len(calls) == 1


async def test_resolve_source_link_failure_raises(monkeypatch, tmp_path: Path):
    async def fake_run(cmd: list[str]) -> tuple[int, str]:
        return 1, "ERROR: Video unavailable"

    monkeypatch.setattr(source_mod, "_run", fake_run)

    with pytest.raises(SourceUnavailable) as exc:
        await resolve_source(ClipSourceType.LINK, "https://youtu.be/abc", tmp_path, "job-1")
    assert "unavailable" in str(exc.value).lower()


# ─── audio-first resolution ───────────────────────────────────────────────────

def test_build_audio_download_command_asks_for_audio_only():
    cmd = build_audio_download_command("https://youtu.be/x", "/tmp/a.m4a")
    assert "-f" in cmd
    assert cmd[cmd.index("-f") + 1] == "ba"
    assert "/tmp/a.m4a" in cmd


async def test_upload_source_needs_no_download(tmp_path: Path):
    upload = tmp_path / "upload.mp4"
    upload.write_bytes(b"video")
    resolved = await resolve_source_audio_first(
        ClipSourceType.UPLOAD, str(upload), tmp_path, "job-1"
    )
    assert resolved.analysis_media == str(upload)
    assert resolved.video_path == str(upload)
    assert resolved.video_task is None
    assert await await_video(resolved) == str(upload)


async def test_link_source_returns_audio_before_the_video_lands(monkeypatch, tmp_path: Path):
    """The point of the whole task: analysis starts while the video downloads."""
    video_started = asyncio.Event()

    async def fake_run(cmd):
        out = cmd[cmd.index("-o") + 1]
        if cmd[cmd.index("-f") + 1] == "ba":
            Path(out).write_bytes(b"audio")
            return 0, ""
        video_started.set()
        await asyncio.sleep(0.05)
        Path(out).write_bytes(b"video")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)
    resolved = await resolve_source_audio_first(
        ClipSourceType.LINK, "https://youtu.be/x", tmp_path, "job-2"
    )

    assert Path(resolved.analysis_media).read_bytes() == b"audio"
    assert resolved.analysis_is_temp is True
    assert resolved.video_path is None          # still downloading
    assert resolved.video_task is not None

    video = await await_video(resolved)
    assert Path(video).read_bytes() == b"video"
    assert video_started.is_set()


async def test_link_falls_back_to_a_plain_video_download(monkeypatch, tmp_path: Path):
    async def fake_run(cmd):
        out = cmd[cmd.index("-o") + 1]
        if cmd[cmd.index("-f") + 1] == "ba":
            return 1, "audio-only format not available"
        Path(out).write_bytes(b"video")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)
    resolved = await resolve_source_audio_first(
        ClipSourceType.LINK, "https://youtu.be/x", tmp_path, "job-3"
    )
    # No audio track: analysis reads the video itself, exactly as before.
    assert Path(resolved.analysis_media).read_bytes() == b"video"
    assert await await_video(resolved) == resolved.analysis_media


async def test_audio_first_can_be_switched_off(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(source_mod.settings, "CLIP_SOURCE_AUDIO_FIRST", False)
    calls: list[str] = []

    async def fake_run(cmd):
        calls.append(cmd[cmd.index("-f") + 1])
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"video")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)
    resolved = await resolve_source_audio_first(
        ClipSourceType.LINK, "https://youtu.be/x", tmp_path, "job-4"
    )
    assert "ba" not in calls
    assert resolved.video_task is None
