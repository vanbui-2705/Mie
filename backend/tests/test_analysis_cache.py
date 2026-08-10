from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.clip_models import ClipAnalysis
from app.services.ai_pipeline import analysis_cache
from app.services.ai_pipeline.types import (
    HotRegion,
    RegionTranscript,
    Transcript,
    Word,
)

PREFILTER = {"min_region_sec": 20.0, "max_region_sec": 90.0, "max_regions": 12}


def _transcript() -> Transcript:
    region = HotRegion(index=0, start_sec=12.5, end_sec=42.5, energy=-11.25)
    words = (Word(start=12.5, end=13.0, text="xin"), Word(start=13.0, end=13.6, text="chào"))
    return Transcript(
        language="vi",
        regions=(RegionTranscript(region=region, text="xin chào", words=words),),
    )


def test_cache_key_changes_with_the_audio():
    a = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=PREFILTER)
    b = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="bbb", prefilter=PREFILTER)
    assert a != b


def test_cache_key_changes_with_the_owner():
    # Per-user scope is the whole privacy story; two users must never collide.
    a = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=PREFILTER)
    b = analysis_cache.build_cache_key(owner_id="u2", audio_sha256="aaa", prefilter=PREFILTER)
    assert a != b


def test_cache_key_changes_with_the_prefilter_settings():
    other = dict(PREFILTER, max_regions=30)
    a = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=PREFILTER)
    b = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=other)
    assert a != b


def test_cache_key_changes_with_the_asr_model(monkeypatch):
    a = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=PREFILTER)
    monkeypatch.setattr(analysis_cache.settings, "ASR_WHISPER_MODEL", "medium")
    b = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=PREFILTER)
    assert a != b


def test_cache_key_is_stable_for_the_same_inputs():
    a = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=PREFILTER)
    b = analysis_cache.build_cache_key(owner_id="u1", audio_sha256="aaa", prefilter=dict(PREFILTER))
    assert a == b


def test_encode_decode_round_trips_the_transcript():
    transcript = _transcript()
    silences = [(1.0, 2.5), (10.0, 10.4)]
    decoded = analysis_cache.decode_analysis(
        analysis_cache.encode_analysis(transcript, silences)
    )
    assert decoded is not None
    got_transcript, got_silences = decoded
    assert got_transcript.language == "vi"
    assert got_transcript.regions[0].region == transcript.regions[0].region
    assert got_transcript.regions[0].words == transcript.regions[0].words
    assert got_transcript.regions[0].text == "xin chào"
    assert got_silences == silences


def test_decode_rejects_a_foreign_payload_version():
    payload = analysis_cache.encode_analysis(_transcript(), [])
    payload["version"] = analysis_cache.PAYLOAD_VERSION + 1
    assert analysis_cache.decode_analysis(payload) is None


def test_decode_rejects_a_malformed_payload():
    assert analysis_cache.decode_analysis({"version": analysis_cache.PAYLOAD_VERSION}) is None


async def test_put_then_get_returns_the_transcript(session_factory, user_id, _ensure_user):
    await analysis_cache.put_analysis(
        session_factory, cache_key="k1", owner_id=str(user_id),
        transcript=_transcript(), silences=[(1.0, 2.0)],
    )
    got = await analysis_cache.get_analysis(session_factory, "k1")
    assert got is not None
    assert got[0].regions[0].text == "xin chào"


async def test_get_counts_the_hit(session_factory, user_id, _ensure_user):
    await analysis_cache.put_analysis(
        session_factory, cache_key="k2", owner_id=str(user_id),
        transcript=_transcript(), silences=[],
    )
    await analysis_cache.get_analysis(session_factory, "k2")
    await analysis_cache.get_analysis(session_factory, "k2")
    async with session_factory() as session:
        row = (
            await session.execute(select(ClipAnalysis).where(ClipAnalysis.cache_key == "k2"))
        ).scalar_one()
    assert row.hit_count == 2


async def test_get_misses_return_none(session_factory):
    assert await analysis_cache.get_analysis(session_factory, "nope") is None


async def test_put_twice_updates_instead_of_colliding(session_factory, user_id, _ensure_user):
    # Two jobs on the same source can finish analysis at the same time; the
    # second write must not blow up on the unique index.
    for _ in range(2):
        await analysis_cache.put_analysis(
            session_factory, cache_key="k3", owner_id=str(user_id),
            transcript=_transcript(), silences=[],
        )
    async with session_factory() as session:
        rows = (
            await session.execute(select(ClipAnalysis).where(ClipAnalysis.cache_key == "k3"))
        ).scalars().all()
    assert len(rows) == 1


async def test_purge_expired_removes_only_stale_rows(session_factory, user_id, _ensure_user):
    await analysis_cache.put_analysis(
        session_factory, cache_key="fresh", owner_id=str(user_id),
        transcript=_transcript(), silences=[],
    )
    await analysis_cache.put_analysis(
        session_factory, cache_key="stale", owner_id=str(user_id),
        transcript=_transcript(), silences=[],
    )
    async with session_factory() as session:
        row = (
            await session.execute(select(ClipAnalysis).where(ClipAnalysis.cache_key == "stale"))
        ).scalar_one()
        row.last_used_at = datetime.now(timezone.utc) - timedelta(days=30)
        await session.commit()

    removed = await analysis_cache.purge_expired(session_factory, ttl_days=14)
    assert removed == 1
    assert await analysis_cache.get_analysis(session_factory, "fresh") is not None
    assert await analysis_cache.get_analysis(session_factory, "stale") is None
