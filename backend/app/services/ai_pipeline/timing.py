"""Per-stage wall clock for one pipeline run.

A job on a two-hour source can spend minutes in a single stage. Without a
breakdown, a slow job in production is only diagnosable by reproducing it, and
reproducing it costs the same minutes again. The numbers are stored on the job
itself so a support question is answered from the row.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from collections.abc import Iterator


class StageTimer:
    """Accumulates seconds per named stage. Repeated names add up."""

    def __init__(self) -> None:
        self._seconds: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            # `finally`, not the happy path: a stage that raised still consumed
            # the wall clock, and that is usually the stage worth seeing.
            elapsed = time.perf_counter() - started
            self._seconds[name] = round(self._seconds.get(name, 0.0) + elapsed, 3)

    def as_dict(self) -> dict[str, float]:
        return dict(self._seconds)

    def total(self) -> float:
        return round(sum(self._seconds.values()), 3)
