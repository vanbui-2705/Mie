"""Safe, user-scoped rental image download storage."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import mimetypes
import socket
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import settings
from app.services.nhatrovn_adapter import BASE


MAX_MEDIA_FILES = 10
MAX_MEDIA_BYTES = 10 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class RentalMediaError(Exception):
    pass


class RentalMediaStore:
    def __init__(
        self,
        root: Path | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._root = (root or Path(settings.UPLOAD_DIR) / "rental").resolve()
        self._http_client = http_client

    async def download(
        self,
        *,
        user_id: uuid.UUID,
        config_id: uuid.UUID,
        external_room_id: str,
        urls: list[str],
    ) -> list[str]:
        normalized = list(dict.fromkeys(
            urljoin(f"{BASE}/", str(url).strip())
            for url in urls
            if str(url).strip()
        ))[:MAX_MEDIA_FILES]
        if not normalized:
            return []

        room_key = hashlib.sha256(external_room_id.encode()).hexdigest()[:24]
        target_dir = (self._root / str(user_id) / str(config_id) / room_key).resolve()
        if self._root not in target_dir.parents:
            raise RentalMediaError("Invalid media storage path")
        target_dir.mkdir(parents=True, exist_ok=True)

        if self._http_client is not None:
            return await self._download_all(self._http_client, normalized, target_dir)
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            return await self._download_all(client, normalized, target_dir)

    async def _download_all(
        self,
        client: httpx.AsyncClient,
        urls: list[str],
        target_dir: Path,
    ) -> list[str]:
        paths: list[str] = []
        for index, url in enumerate(urls):
            await _validate_public_url(url)
            try:
                async with client.stream("GET", url, follow_redirects=False) as response:
                    if 300 <= response.status_code < 400:
                        raise RentalMediaError("Rental image redirects are not allowed")
                    if response.status_code >= 400:
                        raise RentalMediaError(
                            f"Rental image returned HTTP {response.status_code}"
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in ALLOWED_MEDIA_TYPES:
                        raise RentalMediaError(
                            f"Unsupported rental image type: {content_type or 'unknown'}"
                        )
                    declared_size = int(response.headers.get("content-length") or 0)
                    if declared_size > MAX_MEDIA_BYTES:
                        raise RentalMediaError("Rental image is too large")
                    extension = mimetypes.guess_extension(content_type) or ".img"
                    filename = f"{index:02d}-{hashlib.sha256(url.encode()).hexdigest()[:16]}{extension}"
                    path = (target_dir / filename).resolve()
                    if target_dir not in path.parents:
                        raise RentalMediaError("Invalid rental image filename")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_MEDIA_BYTES:
                            raise RentalMediaError("Rental image is too large")
                    await asyncio.to_thread(path.write_bytes, bytes(data))
                    paths.append(str(path))
            except httpx.HTTPError as exc:
                raise RentalMediaError("Could not download rental image") from exc
        return paths


async def _validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RentalMediaError("Rental image URL must use http or https")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise RentalMediaError("Private rental image URL is not allowed")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, host, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise RentalMediaError("Rental image host could not be resolved") from exc
    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0])
        if not address.is_global:
            raise RentalMediaError("Private rental image URL is not allowed")
