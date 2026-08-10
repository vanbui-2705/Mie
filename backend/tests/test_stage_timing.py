from __future__ import annotations

import asyncio

from app.services.ai_pipeline.timing import StageTimer


def test_stage_timer_records_each_stage():
    timer = StageTimer()
    with timer.stage("analyze"):
        pass
    with timer.stage("render"):
        pass
    recorded = timer.as_dict()
    assert set(recorded) == {"analyze", "render"}
    assert all(value >= 0.0 for value in recorded.values())


def test_stage_timer_accumulates_a_repeated_stage():
    timer = StageTimer()
    for _ in range(3):
        with timer.stage("render_clip"):
            pass
    assert set(timer.as_dict()) == {"render_clip"}


def test_stage_timer_records_a_stage_that_raised():
    # A failed render still cost wall clock; losing that hides the slow stage.
    timer = StageTimer()
    try:
        with timer.stage("burn"):
            raise RuntimeError("ffmpeg died")
    except RuntimeError:
        pass
    assert "burn" in timer.as_dict()


def test_stage_timer_total_is_the_sum():
    timer = StageTimer()
    with timer.stage("a"):
        pass
    with timer.stage("b"):
        pass
    assert timer.total() == sum(timer.as_dict().values())


async def test_stage_timer_measures_time_spent_awaiting():
    timer = StageTimer()
    with timer.stage("sleep"):
        await asyncio.sleep(0.05)
    assert timer.as_dict()["sleep"] >= 0.04
