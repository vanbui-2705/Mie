"""Filesystem storage for Flow Studio source uploads."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings


def sanitize_link(link: str) -> str:
    cleaned = (link or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("source_link must be an http(s) URL")
    return cleaned


def save_upload(user_id: str, filename: str, content: bytes) -> str:
    stem = Path(filename or "video").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80] or "video"
    suffix = Path(filename or "").suffix.lower()
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,5}", suffix):
        suffix = ".mp4"
    directory = Path(settings.CLIP_UPLOAD_DIR) / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"
    path.write_bytes(content)
    return str(path)
