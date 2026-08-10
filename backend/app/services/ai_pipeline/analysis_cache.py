"""Cached transcripts, keyed by audio and by the settings that shaped them.

ASR on a two-hour source is the most expensive step in the product, and it
depends on nothing the user tweaks between runs: not top_n, not the length
band, not the editing instructions, not the voice, not the LLM backend. Caching
it turns "run it again with a different brief" from minutes into seconds.

The key folds in the ASR model, the compute type, the pipeline version and the
prefilter parameters, so changing any of them invalidates the cache by itself —
there is no manual purge step to forget.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.config import settings
from app.models.clip_models import ClipAnalysis
from app.services.ai_pipeline.types import (
    HotRegion,
    RegionTranscript,
    Transcript,
    Word,
)

logger = logging.getLogger("flowmeta.ai_pipeline.cache")

PAYLOAD_VERSION = 1


def build_cache_key(*, owner_id: str, audio_sha256: str, prefilter: dict) -> str:
    material = json.dumps(
        {
            "owner": owner_id,
            "audio": audio_sha256,
            "model": settings.ASR_WHISPER_MODEL,
            "compute": settings.ASR_COMPUTE_TYPE,
            "pipeline": settings.CLIP_PIPELINE_VERSION,
            "prefilter": prefilter,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def encode_analysis(
    transcript: Transcript, silences: list[tuple[float, float]]
) -> dict:
    return {
        "version": PAYLOAD_VERSION,
        "language": transcript.language,
        "regions": [
            {
                "index": rt.region.index,
                "start_sec": rt.region.start_sec,
                "end_sec": rt.region.end_sec,
                "energy": rt.region.energy,
                "text": rt.text,
                "words": [
                    {"start": w.start, "end": w.end, "text": w.text} for w in rt.words
                ],
            }
            for rt in transcript.regions
        ],
        "silences": [[start, end] for start, end in silences],
    }


def decode_analysis(
    payload: dict,
) -> tuple[Transcript, list[tuple[float, float]]] | None:
    """None means "treat this as a miss" — never guess at a foreign payload."""
    if not isinstance(payload, dict) or payload.get("version") != PAYLOAD_VERSION:
        return None
    try:
        regions = tuple(
            RegionTranscript(
                region=HotRegion(
                    index=int(item["index"]),
                    start_sec=float(item["start_sec"]),
                    end_sec=float(item["end_sec"]),
                    energy=float(item["energy"]),
                ),
                text=str(item["text"]),
                words=tuple(
                    Word(start=float(w["start"]), end=float(w["end"]), text=str(w["text"]))
                    for w in item["words"]
                ),
            )
            for item in payload["regions"]
        )
        silences = [(float(a), float(b)) for a, b in payload["silences"]]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("discarding a malformed analysis payload: %s", exc)
        return None
    return Transcript(language=str(payload["language"]), regions=regions), silences


async def get_analysis(
    session_factory, cache_key: str
) -> tuple[Transcript, list[tuple[float, float]]] | None:
    if not settings.CLIP_ANALYSIS_CACHE_ENABLED:
        return None
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ClipAnalysis).where(ClipAnalysis.cache_key == cache_key)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        decoded = decode_analysis(row.payload)
        if decoded is None:
            return None
        row.hit_count = (row.hit_count or 0) + 1
        row.last_used_at = datetime.now(timezone.utc)
        await session.commit()
    logger.info("analysis cache hit for %s", cache_key[:12])
    return decoded


async def put_analysis(
    session_factory,
    *,
    cache_key: str,
    owner_id: str,
    transcript: Transcript,
    silences: list[tuple[float, float]],
) -> None:
    if not settings.CLIP_ANALYSIS_CACHE_ENABLED:
        return
    payload = encode_analysis(transcript, silences)
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ClipAnalysis).where(ClipAnalysis.cache_key == cache_key)
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(
                ClipAnalysis(
                    id=uuid.uuid4(),
                    cache_key=cache_key,
                    owner_id=uuid.UUID(str(owner_id)),
                    payload=payload,
                )
            )
        else:
            row.payload = payload
            row.last_used_at = datetime.now(timezone.utc)
        await session.commit()


async def purge_expired(session_factory, ttl_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(ttl_days)))
    async with session_factory() as session:
        result = await session.execute(
            delete(ClipAnalysis).where(ClipAnalysis.last_used_at < cutoff)
        )
        await session.commit()
    return int(result.rowcount or 0)
