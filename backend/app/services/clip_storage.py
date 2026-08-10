"""Filesystem storage for Flow Studio source uploads."""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from app.config import settings

# 4 MB at a time: big enough that the syscall overhead disappears against disk
# throughput, small enough that a 4 GB upload never costs more than one chunk
# of resident memory.
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
GEN_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class UploadTooLarge(Exception):
    """The client sent more bytes than CLIP_MAX_UPLOAD_BYTES allows."""


class EmptyUpload(Exception):
    """The client sent a file part with no bytes in it."""


class UnsupportedImage(Exception):
    """The uploaded part is not a supported image or its bytes are spoofed."""


class ChunkReader(Protocol):
    """The part of Starlette's UploadFile this module needs."""

    async def read(self, size: int = -1) -> bytes: ...


def sanitize_link(link: str) -> str:
    cleaned = (link or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("source_link must be an http(s) URL")
    return cleaned


def build_upload_path(user_id: str, filename: str) -> Path:
    """Where an upload lands: <CLIP_UPLOAD_DIR>/<user>/<uuid>_<safe name><ext>.

    The uuid prefix is what makes the retention sweeper able to glob a job's
    debris, and it keeps two users' identically named files apart.
    """
    stem = Path(filename or "video").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80] or "video"
    suffix = Path(filename or "").suffix.lower()
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,5}", suffix):
        suffix = ".mp4"
    directory = Path(settings.CLIP_UPLOAD_DIR) / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"


def save_upload(user_id: str, filename: str, content: bytes) -> str:
    """Write bytes already in memory. Only for small payloads and tests."""
    path = build_upload_path(user_id, filename)
    path.write_bytes(content)
    return str(path)


async def save_upload_stream(
    user_id: str, filename: str, upload: ChunkReader, *, max_bytes: int
) -> str:
    """Copy an upload to disk chunk by chunk and return the path.

    Reading the whole part first (`await file.read()`) materialises the entire
    video as one bytes object — a 4 GB upload is a 4 GB allocation, and a
    handful of concurrent ones takes the process down. This holds one chunk at
    a time instead, enforces the size cap as it goes so an oversized upload is
    cut off rather than fully absorbed, and leaves nothing behind on failure.
    """
    path = build_upload_path(user_id, filename)
    written = 0
    try:
        handle = await asyncio.to_thread(path.open, "wb")
        try:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UploadTooLarge(f"upload exceeds {max_bytes} bytes")
                # Disk writes are blocking; keep them off the event loop so
                # other requests still get served during a long upload.
                await asyncio.to_thread(handle.write, chunk)
        finally:
            await asyncio.to_thread(handle.close)
        if written == 0:
            raise EmptyUpload("uploaded file is empty")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return str(path)


def _matches_image_header(header: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    return False


def _read_header(path: str, size: int = 16) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(size)


async def save_gen_image_stream(
    user_id: str,
    filename: str,
    content_type: str,
    upload: ChunkReader,
    *,
    max_bytes: int,
) -> str:
    """Validate and stream one user-supplied Gen image to job storage."""
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    suffix = GEN_IMAGE_TYPES.get(media_type)
    if suffix is None:
        raise UnsupportedImage("Only JPEG, PNG and WebP images are supported")

    safe_name = f"{Path(filename or 'product').stem}{suffix}"
    path = await save_upload_stream(user_id, safe_name, upload, max_bytes=max_bytes)
    try:
        header = await asyncio.to_thread(_read_header, path)
        if not _matches_image_header(header, media_type):
            raise UnsupportedImage("Uploaded image content does not match its file type")
    except BaseException:
        await asyncio.to_thread(Path(path).unlink, missing_ok=True)
        raise
    return path
