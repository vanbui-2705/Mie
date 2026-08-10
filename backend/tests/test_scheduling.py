from __future__ import annotations

import asyncio

import pytest

from app.services.ai_pipeline import scheduling


@pytest.fixture(autouse=True)
def fresh_slots():
    scheduling.reset_slots()
    yield
    scheduling.reset_slots()


def test_cpu_slots_auto_leaves_one_core_free(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 0)
    monkeypatch.setattr(scheduling.os, "cpu_count", lambda: 8)
    assert scheduling.cpu_slots() == 7


def test_cpu_slots_auto_never_returns_zero(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 0)
    monkeypatch.setattr(scheduling.os, "cpu_count", lambda: 1)
    assert scheduling.cpu_slots() == 1


def test_cpu_slots_honours_an_explicit_setting(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 3)
    assert scheduling.cpu_slots() == 3


def test_ffmpeg_threads_divides_the_cores_between_slots(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 4)
    monkeypatch.setattr(scheduling.os, "cpu_count", lambda: 8)
    assert scheduling.ffmpeg_threads() == 2


def test_ffmpeg_threads_is_at_least_one(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 16)
    monkeypatch.setattr(scheduling.os, "cpu_count", lambda: 2)
    assert scheduling.ffmpeg_threads() == 1


async def test_cpu_slot_limits_concurrency(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 2)
    scheduling.reset_slots()
    live = 0
    peak = 0

    async def work():
        nonlocal live, peak
        async with scheduling.cpu_slot():
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1

    await asyncio.gather(*(work() for _ in range(6)))
    assert peak == 2


async def test_cpu_slot_is_released_when_the_holder_is_cancelled(monkeypatch):
    """The trap this whole module exists to avoid.

    A cancelled job kills the ffmpeg holding a slot. If the slot is not
    released the worker silently never runs another job — no error, no log,
    just a queue that stops draining.
    """
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 1)
    scheduling.reset_slots()
    started = asyncio.Event()

    async def holder():
        async with scheduling.cpu_slot():
            started.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(holder())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The slot must be free again immediately.
    async with asyncio.timeout(1.0):
        async with scheduling.cpu_slot():
            pass


async def test_cpu_slot_is_released_when_the_body_raises(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 1)
    scheduling.reset_slots()
    with pytest.raises(RuntimeError):
        async with scheduling.cpu_slot():
            raise RuntimeError("ffmpeg died")
    async with asyncio.timeout(1.0):
        async with scheduling.cpu_slot():
            pass


async def test_tts_and_cpu_slots_are_independent(monkeypatch):
    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 1)
    monkeypatch.setattr(scheduling.settings, "FLOW_TTS_SLOTS", 4)
    scheduling.reset_slots()
    async with scheduling.cpu_slot():
        # Waiting on the network must not be blocked by a busy CPU.
        async with asyncio.timeout(1.0):
            async with scheduling.tts_slot():
                pass
