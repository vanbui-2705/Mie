"""HTTP-level tests for the Flow Studio endpoints the Studio page depends on."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth import create_token
from app.db.postgres import get_session
from app.flow_app import app
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus
from app.models.sqlmodels import User

CLIP_BYTES = b"0123456789abcdef"


@pytest_asyncio.fixture
async def client(session):
    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            yield http
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _make_user(session, name: str) -> User:
    user = User(id=uuid.uuid4(), username=name, password_hash=None, role="user")
    session.add(user)
    await session.flush()
    return user


async def _make_job(session, user: User, *, status=ClipJobStatus.DONE) -> ClipJob:
    job = ClipJob(
        id=uuid.uuid4(),
        user_id=user.id,
        source_type=ClipSourceType.UPLOAD,
        source_ref="/app/uploads/clips/u1/talk.mp4",
        params={"top_n": 3},
        status=status,
    )
    session.add(job)
    await session.flush()
    return job


async def _make_clip(session, job: ClipJob, *, output_ref: str | None, rank: int = 1) -> Clip:
    clip = Clip(
        id=uuid.uuid4(),
        job_id=job.id,
        rank=rank,
        score=91,
        hook_text="Bi quyet",
        start_sec=10.0,
        end_sec=40.0,
        clipspec={"version": 2, "words": [{"start": 0.0, "end": 0.4, "word": "Xin"}]},
        output_ref=output_ref,
        status=ClipStatus.READY if output_ref else ClipStatus.PENDING,
    )
    session.add(clip)
    await session.flush()
    return clip


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user.id)}"}


@pytest.mark.asyncio
async def test_list_returns_only_own_jobs_newest_first(client, session) -> None:
    owner = await _make_user(session, "owner-list")
    stranger = await _make_user(session, "stranger-list")
    older = await _make_job(session, owner)
    newer = await _make_job(session, owner)
    await _make_job(session, stranger)
    # created_at defaults to now() for every row in the same transaction, so pin
    # the order explicitly instead of trusting insertion time.
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    older.created_at = now - timedelta(hours=1)
    newer.created_at = now
    await session.flush()

    response = await client.get("/api/clip-jobs", headers=_auth(owner))

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [str(newer.id), str(older.id)]
    assert body[0]["source_name"] == "talk.mp4"


@pytest.mark.asyncio
async def test_list_counts_clips_and_honours_limit(client, session) -> None:
    owner = await _make_user(session, "owner-count")
    job = await _make_job(session, owner)
    await _make_clip(session, job, output_ref="/tmp/a.mp4", rank=1)
    await _make_clip(session, job, output_ref="/tmp/b.mp4", rank=2)
    await _make_job(session, owner)

    response = await client.get("/api/clip-jobs?limit=1", headers=_auth(owner))

    assert response.status_code == 200
    assert len(response.json()) == 1
    full = await client.get("/api/clip-jobs", headers=_auth(owner))
    counts = {row["id"]: row["clip_count"] for row in full.json()}
    assert counts[str(job.id)] == 2


@pytest.mark.asyncio
async def test_job_detail_includes_clipspec(client, session) -> None:
    owner = await _make_user(session, "owner-detail")
    job = await _make_job(session, owner)
    await _make_clip(session, job, output_ref="/tmp/a.mp4")

    response = await client.get(f"/api/clip-jobs/{job.id}", headers=_auth(owner))

    assert response.status_code == 200
    clip = response.json()["clips"][0]
    assert clip["clipspec"]["version"] == 2
    assert clip["clipspec"]["words"][0]["word"] == "Xin"


@pytest.mark.asyncio
async def test_stream_serves_whole_file_with_query_token(client, session, tmp_path) -> None:
    owner = await _make_user(session, "owner-stream")
    job = await _make_job(session, owner)
    media = tmp_path / "clip.mp4"
    media.write_bytes(CLIP_BYTES)
    clip = await _make_clip(session, job, output_ref=str(media))

    token = create_token(owner.id)
    response = await client.get(f"/api/clips/{clip.id}/stream?token={token}")

    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == CLIP_BYTES


@pytest.mark.asyncio
async def test_stream_honours_a_byte_range(client, session, tmp_path) -> None:
    owner = await _make_user(session, "owner-range")
    job = await _make_job(session, owner)
    media = tmp_path / "clip.mp4"
    media.write_bytes(CLIP_BYTES)
    clip = await _make_clip(session, job, output_ref=str(media))

    response = await client.get(
        f"/api/clips/{clip.id}/stream?token={create_token(owner.id)}",
        headers={"Range": "bytes=4-9"},
    )

    assert response.status_code == 206
    assert response.content == CLIP_BYTES[4:10]
    assert response.headers["content-range"] == f"bytes 4-9/{len(CLIP_BYTES)}"


@pytest.mark.asyncio
async def test_stream_rejects_a_missing_token(client, session, tmp_path) -> None:
    owner = await _make_user(session, "owner-anon")
    job = await _make_job(session, owner)
    media = tmp_path / "clip.mp4"
    media.write_bytes(CLIP_BYTES)
    clip = await _make_clip(session, job, output_ref=str(media))

    response = await client.get(f"/api/clips/{clip.id}/stream")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_stream_hides_another_users_clip(client, session, tmp_path) -> None:
    owner = await _make_user(session, "owner-private")
    stranger = await _make_user(session, "stranger-private")
    job = await _make_job(session, owner)
    media = tmp_path / "clip.mp4"
    media.write_bytes(CLIP_BYTES)
    clip = await _make_clip(session, job, output_ref=str(media))

    response = await client.get(
        f"/api/clips/{clip.id}/stream?token={create_token(stranger.id)}"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stream_reports_a_clip_without_output(client, session) -> None:
    owner = await _make_user(session, "owner-pending")
    job = await _make_job(session, owner, status=ClipJobStatus.RENDERING)
    clip = await _make_clip(session, job, output_ref=None)

    response = await client.get(
        f"/api/clips/{clip.id}/stream?token={create_token(owner.id)}"
    )

    assert response.status_code == 409
