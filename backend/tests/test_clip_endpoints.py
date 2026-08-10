"""HTTP-level tests for the Flow Studio endpoints the Studio page depends on."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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
async def test_stream_reports_a_purged_clip_as_gone(client, session) -> None:
    from datetime import datetime, timezone

    owner = await _make_user(session, "owner-purged")
    job = await _make_job(session, owner)
    job.purged_at = datetime.now(timezone.utc)
    clip = await _make_clip(session, job, output_ref=None)
    clip.status = ClipStatus.PURGED
    await session.flush()

    response = await client.get(
        f"/api/clips/{clip.id}/stream?token={create_token(owner.id)}"
    )

    assert response.status_code == 410


@pytest.mark.asyncio
async def test_heartbeat_touches_only_own_jobs(client, session) -> None:
    from app.services.clip_retention import _as_utc

    owner = await _make_user(session, "owner-beat")
    stranger = await _make_user(session, "stranger-beat")
    job = await _make_job(session, owner)
    other = await _make_job(session, stranger)
    from datetime import datetime, timedelta, timezone

    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    job.last_seen_at = stale
    await session.flush()

    response = await client.post(
        "/api/clip-jobs/heartbeat",
        json={"job_ids": [str(job.id), str(other.id)]},
        headers=_auth(owner),
    )

    assert response.status_code == 200
    assert response.json() == {"touched": 1}
    await session.refresh(job)
    assert _as_utc(job.last_seen_at) > _as_utc(stale)


@pytest.mark.asyncio
async def test_heartbeat_needs_auth(client, session) -> None:
    response = await client.post("/api/clip-jobs/heartbeat", json={"job_ids": []})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_job_detail_exposes_purged_at(client, session) -> None:
    from datetime import datetime, timezone

    owner = await _make_user(session, "owner-purged-detail")
    job = await _make_job(session, owner)
    job.purged_at = datetime.now(timezone.utc)
    await session.flush()

    response = await client.get(f"/api/clip-jobs/{job.id}", headers=_auth(owner))

    assert response.status_code == 200
    assert response.json()["purged_at"] is not None


@pytest.mark.asyncio
async def test_stream_reports_a_clip_without_output(client, session) -> None:
    owner = await _make_user(session, "owner-pending")
    job = await _make_job(session, owner, status=ClipJobStatus.RENDERING)
    clip = await _make_clip(session, job, output_ref=None)

    response = await client.get(
        f"/api/clips/{clip.id}/stream?token={create_token(owner.id)}"
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_job_streams_the_upload_to_disk(client, session, tmp_path, monkeypatch) -> None:
    from app.config import settings
    from app.routers import clip_jobs as router_mod

    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))
    enqueued: list[object] = []

    async def _fake_enqueue(payload):
        enqueued.append(payload)

    monkeypatch.setattr(router_mod, "enqueue_clip_job", _fake_enqueue)
    user = await _make_user(session, "uploader")
    payload = b"v" * 5000

    response = await client.post(
        "/api/clip-jobs",
        headers=_auth(user),
        files={"file": ("talk.mp4", payload, "video/mp4")},
        data={"top_n": "3"},
    )

    assert response.status_code == 200, response.text
    assert len(enqueued) == 1
    saved = list((tmp_path / str(user.id)).iterdir())
    assert len(saved) == 1
    assert saved[0].read_bytes() == payload


@pytest.mark.asyncio
async def test_create_job_persists_ai_edit_instructions(
    client, session, monkeypatch
) -> None:
    from app.routers import clip_jobs as router_mod

    async def _fake_enqueue(payload):
        return None

    monkeypatch.setattr(router_mod, "enqueue_clip_job", _fake_enqueue)
    user = await _make_user(session, "configured-editor")
    instructions = "Ưu tiên đoạn tự đủ ý và không giật tít sai."

    response = await client.post(
        "/api/clip-jobs",
        headers=_auth(user),
        data={
            "source_link": "https://example.com/video",
            "edit_instructions": instructions,
        },
    )

    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    job = await session.get(ClipJob, uuid.UUID(job_id))
    assert job is not None
    assert job.params["edit_instructions"] == instructions


@pytest.mark.asyncio
async def test_create_job_rejects_an_oversized_upload(client, session, tmp_path, monkeypatch) -> None:
    from app.config import settings
    from app.routers import clip_jobs as router_mod

    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CLIP_MAX_UPLOAD_BYTES", 64)

    async def _fail(payload):  # pragma: no cover - must never run
        raise AssertionError("an oversized upload must not be enqueued")

    monkeypatch.setattr(router_mod, "enqueue_clip_job", _fail)
    user = await _make_user(session, "uploader-big")

    response = await client.post(
        "/api/clip-jobs",
        headers=_auth(user),
        files={"file": ("big.mp4", b"v" * 5000, "video/mp4")},
        data={"top_n": "3"},
    )

    assert response.status_code == 413
    assert list((tmp_path / str(user.id)).iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "detail"),
    [
        ({"source_link": "https://example.com/video", "top_n": "0"}, "top_n"),
        (
            {
                "source_link": "https://example.com/video",
                "clip_min_sec": "90",
                "clip_max_sec": "30",
            },
            "clip_min_sec",
        ),
        (
            {
                "source_link": "https://example.com/video",
                "scoring_backend": "unknown",
            },
            "Unsupported scoring backend",
        ),
        (
            {
                "source_link": "https://example.com/video",
                "edit_instructions": "x" * 2001,
            },
            "AI edit instructions",
        ),
    ],
)
async def test_create_job_rejects_invalid_pipeline_parameters(
    client, session, data, detail
) -> None:
    user = await _make_user(session, f"invalid-{uuid.uuid4().hex[:8]}")

    response = await client.post("/api/clip-jobs", headers=_auth(user), data=data)

    assert response.status_code == 400
    assert detail in response.json()["detail"]


@pytest.mark.asyncio
async def test_gen_job_rejects_heuristic_backend(client, session) -> None:
    user = await _make_user(session, "gen-heuristic")

    response = await client.post(
        "/api/gen-jobs",
        headers=_auth(user),
        json={
            "prompt": "Một video đủ dài để kiểm tra tạo kịch bản",
            "duration_sec": 30,
            "voice": "vi-female",
            "scoring_backend": "heuristic",
        },
    )

    assert response.status_code == 400
    assert "requires one of these AI backends" in response.json()["detail"]


@pytest.mark.asyncio
async def test_gen_job_from_images_saves_ordered_product_images(
    client, session, tmp_path, monkeypatch,
) -> None:
    from app.config import settings
    from app.routers import clip_jobs

    user = await _make_user(session, "gen-images")
    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))

    async def fake_enqueue(_payload):
        return 1

    monkeypatch.setattr(clip_jobs, "enqueue_clip_job", fake_enqueue)
    png = b"\x89PNG\r\n\x1a\n" + b"product"
    response = await client.post(
        "/api/gen-jobs/from-images",
        headers=_auth(user),
        data={
            "prompt": "Tạo video bán sản phẩm chăm sóc da dịu nhẹ",
            "duration_sec": "60",
            "voice": "vi-female",
            "scoring_backend": "gemini",
        },
        files=[
            ("images", ("front.png", png, "image/png")),
            ("images", ("detail.png", png + b"-detail", "image/png")),
        ],
    )

    assert response.status_code == 200
    job = (
        await session.execute(
            select(ClipJob).where(ClipJob.id == uuid.UUID(response.json()["job_id"]))
        )
    ).scalar_one()
    assert job.params["image_count"] == 2
    assert [path.rsplit("_", 1)[-1] for path in job.params["image_paths"]] == [
        "front.png", "detail.png",
    ]
