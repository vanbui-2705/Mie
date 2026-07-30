"""Backdrop images for Gen video: Pexels, Wikimedia Commons, then a gradient.

Pexels is free and its licence allows commercial use without attribution, but
it needs a key. Wikimedia Commons provides a keyless secondary source. A
generated gradient remains the final offline fallback so a network outage does
not fail the whole job.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import httpx

from app.config import settings
from app.services.ai_pipeline import procs

logger = logging.getLogger("flowmeta.ai_pipeline.stock")

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
COMMONS_SEARCH_URL = "https://commons.wikimedia.org/w/api.php"
COMMONS_USER_AGENT = "FlowMeta/1.0 (AI video backdrop fetcher)"
CANVAS_W = 1080
CANVAS_H = 1920

# Deterministic per scene index, so re-running a job looks the same and adjacent
# scenes never share a colour.
_GRADIENTS = [
    ("0x1f2937", "0x111827"),
    ("0x312e81", "0x1e1b4b"),
    ("0x7f1d1d", "0x450a0a"),
    ("0x064e3b", "0x022c22"),
    ("0x78350f", "0x431407"),
    ("0x581c87", "0x2e1065"),
]


def gradient_command(out_path: str, *, index: int) -> list[str]:
    """One PNG of a two-stop gradient — no network, no key, always available."""
    c0, c1 = _GRADIENTS[index % len(_GRADIENTS)]
    return [
        settings.FFMPEG_BIN, "-y",
        "-f", "lavfi",
        "-i", f"gradients=s={CANVAS_W}x{CANVAS_H}:c0={c0}:c1={c1}:n=2:duration=1",
        "-frames:v", "1",
        out_path,
    ]


async def render_gradient(out_path: str, *, index: int) -> str | None:
    process = await procs.spawn(
        gradient_command(out_path, index=index),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await procs.communicate(process)
    if process.returncode != 0:
        logger.error("gradient render failed: %s", stderr.decode(errors="replace")[-500:])
        return None
    return out_path


def pick_photo_url(payload: object) -> str | None:
    """Portrait-friendly source URL out of a Pexels search response."""
    if not isinstance(payload, dict):
        return None
    photos = payload.get("photos")
    if not isinstance(photos, list) or not photos:
        return None
    src = photos[0].get("src") if isinstance(photos[0], dict) else None
    if not isinstance(src, dict):
        return None
    # `portrait` is already 9:16-ish; the others are fallbacks in quality order.
    for key in ("portrait", "large2x", "large", "original"):
        url = src.get(key)
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def pick_commons_photo_url(payload: object) -> str | None:
    """Pick a safe JPEG result, preferring portrait media for the 9:16 canvas."""
    if not isinstance(payload, dict):
        return None
    query = payload.get("query")
    pages = query.get("pages") if isinstance(query, dict) else None
    if not isinstance(pages, list):
        return None

    candidates: list[tuple[bool, str]] = []
    for page in pages:
        infos = page.get("imageinfo") if isinstance(page, dict) else None
        info = (
            infos[0]
            if isinstance(infos, list) and infos and isinstance(infos[0], dict)
            else None
        )
        if not info or info.get("mime") != "image/jpeg":
            continue
        url = info.get("thumburl") or info.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        width = info.get("width")
        height = info.get("height")
        portrait = isinstance(width, int) and isinstance(height, int) and height >= width
        candidates.append((portrait, url))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates else None


async def fetch_stock_image(query: str, out_path: str) -> str | None:
    """Download one portrait photo for `query`. None = caller should fall back."""
    api_key = settings.PEXELS_API_KEY.strip()
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.STOCK_TIMEOUT_SECONDS) as client:
            response = await client.get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": api_key},
                params={"query": query, "orientation": "portrait", "per_page": 1},
            )
            if response.status_code != 200:
                logger.warning("Pexels search failed (%s) for %r", response.status_code, query)
                return None
            url = pick_photo_url(response.json())
            if url is None:
                logger.info("Pexels had no photo for %r", query)
                return None
            image = await client.get(url)
            if image.status_code != 200 or not image.content:
                return None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Pexels fetch failed for %r: %s", query, exc)
        return None

    Path(out_path).write_bytes(image.content)
    logger.info("stock image for %r (%d bytes)", query, len(image.content))
    return out_path


async def fetch_commons_image(query: str, out_path: str) -> str | None:
    """Download a relevant Commons JPEG without requiring an API key."""
    try:
        async with httpx.AsyncClient(
            timeout=settings.STOCK_TIMEOUT_SECONDS,
            headers={"User-Agent": COMMONS_USER_AGENT},
        ) as client:
            response = await client.get(
                COMMONS_SEARCH_URL,
                params={
                    "action": "query",
                    "generator": "search",
                    # "photograph" steers Commons away from scanned documents,
                    # logos and diagrams that often rank for broad concepts.
                    "gsrsearch": f"{query} photograph",
                    "gsrnamespace": 6,
                    "gsrlimit": 8,
                    "prop": "imageinfo",
                    "iiprop": "url|mime|size",
                    "iiurlwidth": CANVAS_W,
                    "format": "json",
                    "formatversion": 2,
                },
            )
            if response.status_code != 200:
                logger.warning("Commons search failed (%s) for %r", response.status_code, query)
                return None
            url = pick_commons_photo_url(response.json())
            if url is None:
                logger.info("Commons had no usable photo for %r", query)
                return None
            image = await client.get(url)
            content_type = image.headers.get("content-type", "").lower()
            if (
                image.status_code != 200
                or not image.content
                or not content_type.startswith("image/jpeg")
            ):
                logger.warning("Commons image download failed for %r", query)
                return None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Commons fetch failed for %r: %s", query, exc)
        return None

    Path(out_path).write_bytes(image.content)
    logger.info("Commons image for %r (%d bytes)", query, len(image.content))
    return out_path


def backdrop_source(path: str) -> str:
    name = Path(path).name
    if "_pexels_" in name:
        return "pexels"
    if "_commons_" in name:
        return "wikimedia_commons"
    return "generated_gradient"


async def resolve_backdrop(query: str, work_dir: Path, base: str, index: int) -> str | None:
    """Try both photo providers before using the offline visual fallback."""
    stem = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
    photo = await fetch_stock_image(
        query, str(work_dir / f"{base}_pexels_{index}_{stem}.jpg")
    )
    if photo:
        return photo
    photo = await fetch_commons_image(
        query, str(work_dir / f"{base}_commons_{index}_{stem}.jpg")
    )
    if photo:
        return photo
    return await render_gradient(str(work_dir / f"{base}_bg_{index}.png"), index=index)
