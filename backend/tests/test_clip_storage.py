from pathlib import Path

import pytest

from app.services.clip_storage import (
    EmptyUpload,
    UploadTooLarge,
    sanitize_link,
    save_upload,
    save_upload_stream,
)


class FakeUpload:
    """Hands out bytes in chunks and records the largest read it was asked for."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.max_chunk = 0

    async def read(self, size: int = -1) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        self.max_chunk = max(self.max_chunk, len(chunk))
        return chunk


def test_sanitize_link_accepts_https() -> None:
    assert sanitize_link("  https://youtu.be/abc  ") == "https://youtu.be/abc"


def test_sanitize_link_rejects_non_http() -> None:
    with pytest.raises(ValueError):
        sanitize_link("javascript:alert(1)")


def test_save_upload_writes_file(tmp_path, monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))
    path = save_upload("user-1", "My Video.mp4", b"data-bytes")
    with open(path, "rb") as fh:
        assert fh.read() == b"data-bytes"
    assert path.endswith(".mp4")


@pytest.mark.asyncio
async def test_save_upload_stream_writes_in_chunks(tmp_path, monkeypatch) -> None:
    from app.config import settings
    from app.services import clip_storage

    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(clip_storage, "UPLOAD_CHUNK_BYTES", 8)

    payload = b"x" * 100
    upload = FakeUpload(payload)
    path = await save_upload_stream("user-1", "clip.mp4", upload, max_bytes=1024)

    assert Path(path).read_bytes() == payload
    # The whole file never sat in memory: no single read exceeded a chunk.
    assert upload.max_chunk == 8


@pytest.mark.asyncio
async def test_save_upload_stream_stops_at_the_limit(tmp_path, monkeypatch) -> None:
    from app.config import settings
    from app.services import clip_storage

    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(clip_storage, "UPLOAD_CHUNK_BYTES", 8)

    with pytest.raises(UploadTooLarge):
        await save_upload_stream("user-1", "big.mp4", FakeUpload(b"y" * 100), max_bytes=20)

    # Nothing half-written is left behind for the sweeper to trip over.
    assert list((tmp_path / "user-1").iterdir()) == []


@pytest.mark.asyncio
async def test_save_upload_stream_rejects_an_empty_part(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))

    with pytest.raises(EmptyUpload):
        await save_upload_stream("user-1", "empty.mp4", FakeUpload(b""), max_bytes=1024)

    assert list((tmp_path / "user-1").iterdir()) == []
