from app.config import settings
from app.schemas import ClipJobCreate, ClipJobOut, ClipOut


def test_clip_settings_present() -> None:
    assert isinstance(settings.CLIP_UPLOAD_DIR, str)
    assert settings.CLIP_MAX_UPLOAD_BYTES > 0


def test_peer_settings_present() -> None:
    assert settings.FACE_BASE_URL.startswith("http")
    assert settings.FLOW_BASE_URL.startswith("http")
    assert settings.PEER_HEALTH_TIMEOUT_SECONDS > 0


def test_clip_job_create_defaults() -> None:
    body = ClipJobCreate()
    assert body.top_n == 10
    assert body.clip_min_sec == 120
    assert body.clip_max_sec == 300
    assert body.scoring_backend == settings.SCORING_BACKEND


def test_clip_job_out_serializes_clips() -> None:
    out = ClipJobOut(
        id="j1", source_type="link", status="done", error=None,
        clips=[ClipOut(id="c1", rank=1, score=90, hook_text="hi",
                       start_sec=1.0, end_sec=120.0, status="ready", output_ref="/x.mp4")],
    )
    assert out.clips[0].rank == 1
