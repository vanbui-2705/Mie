from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.models.clip_models import ClipSourceType
from app.services.ai_pipeline import source as source_mod
from app.services.ai_pipeline.source import (
    SourceUnavailable,
    build_download_command,
    resolve_source,
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
