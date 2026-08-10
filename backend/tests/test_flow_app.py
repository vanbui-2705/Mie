import pytest

from route_paths import route_paths


def test_flow_app_has_clip_routes() -> None:
    from app.flow_app import app
    paths = route_paths(app)
    assert "/api/clip-jobs" in paths
    assert "/api/clip-jobs/{job_id}" in paths
    assert "/api/clips/{clip_id}/download" in paths
    assert "/api/clips/{clip_id}/stream" in paths
    assert "/api/flow/peers/face" in paths
    assert "/api/events/stream" in paths


def test_flow_app_excludes_face_routes() -> None:
    # Flow must be independent — no comment/task endpoints leak in.
    from app.flow_app import app
    paths = route_paths(app)
    assert not any(p.startswith("/api/comment-tasks") for p in paths)
    assert not any(p.startswith("/api/tasks") for p in paths)


def test_face_app_alias_is_main_app() -> None:
    from app import face_app, main
    assert face_app.app is main.app


@pytest.mark.asyncio
async def test_flow_worker_dispatches_clip_job(monkeypatch) -> None:
    import app.flow_worker as fw

    called = {}

    class _FakeRunner:
        def __init__(self, **kw):
            pass

        async def run(self, job_id):
            called["job_id"] = job_id

    monkeypatch.setattr(fw, "ClipRunner", _FakeRunner)
    handled = await fw.process_clip_job({"type": "clip_job", "job_id": "j-42"})
    assert handled is True
    assert called["job_id"] == "j-42"


@pytest.mark.asyncio
async def test_flow_worker_skips_foreign_job() -> None:
    import app.flow_worker as fw
    handled = await fw.process_clip_job({"type": "comment_task", "run_id": "x"})
    assert handled is False
