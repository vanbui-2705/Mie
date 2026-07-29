import pytest

from app.services.clip_storage import sanitize_link, save_upload


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
