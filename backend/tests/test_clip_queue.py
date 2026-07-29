from app.services.clip_queue import CLIP_QUEUE_KEY, build_clip_job


def test_build_clip_job_shape() -> None:
    assert build_clip_job("abc") == {"type": "clip_job", "job_id": "abc"}


def test_clip_queue_key_is_separate() -> None:
    # Must NOT collide with the comment worker's queue.
    from app.services.task_queue import QUEUE_KEY
    assert CLIP_QUEUE_KEY == "flowmeta:clip_queue"
    assert CLIP_QUEUE_KEY != QUEUE_KEY
