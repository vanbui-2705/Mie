# Flow Video Pipeline Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut wall-clock time of one Flow Studio video job on a 30–120 minute source, without changing any pipeline output.

**Architecture:** Keep every algorithm exactly as it is and change only *scheduling*: decode the audio once and pass an `AudioTrack` around, put CPU work and network work behind separate semaphores, render clips and speak TTS cues concurrently, download link audio before link video, and cache the transcript per user keyed by the audio's sha256.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + Alembic, Postgres, Redis, pytest (`asyncio_mode = auto`), ffmpeg/ffprobe, faster-whisper, edge-tts, OpenCV, Next.js frontend.

## Global Constraints

- **Never change algorithm behaviour.** Every task except Task 10 must leave clip `start_sec`, `end_sec` and `subtitle_text` byte-identical to the baseline. Task 10 has its own quality gate (see the task).
- **Spec:** `docs/superpowers/specs/2026-08-10-flow-video-pipeline-latency-design.md`. Read it before starting.
- **Work in `backend/` for every backend command.** `pytest` is configured by `backend/pytest.ini` with `pythonpath = .`, so run it from `backend/`.
- **Repo conventions:** all algorithms live in `app/services/ai_pipeline/*`; `clip_runner.py` and `gen_runner.py` orchestrate only. Do not put pipeline logic in the runners.
- **Clip-related models live in `app/models/clip_models.py`**, not `sqlmodels.py`.
- **Every new setting goes in `backend/app/config.py`** with a safe default, and is listed in `.env.example` if it is operational.
- **Do not touch Face** (comment/account/proxy/sheets code).
- **Not in scope:** GPU, cloud ASR, output resolution/quality changes, scoring-algorithm changes.
- **Commit after every task** with a `feat(flow-studio):` / `perf(flow-studio):` / `test(flow-studio):` prefix.
- **Existing tests must keep passing.** Full suite: `cd backend && python -m pytest -q`.

---

## File Structure

**New backend files**

| File | Responsibility |
|---|---|
| `backend/app/services/ai_pipeline/audio.py` | `AudioTrack` value object + one-shot WAV decode. Knows nothing about jobs, DB or video. |
| `backend/app/services/ai_pipeline/scheduling.py` | CPU / network / TTS semaphores and the ffmpeg thread count. No pipeline knowledge. |
| `backend/app/services/ai_pipeline/timing.py` | `StageTimer` — records per-stage wall clock. Pure data. |
| `backend/app/services/ai_pipeline/analysis_cache.py` | Encode/decode the analysis payload and read/write the `clip_analysis` table. |
| `backend/alembic/versions/20260810_0010_clip_analysis.py` | Migration for `clip_analysis`. |
| `backend/tests/test_audio_track.py` | Tests for `audio.py`. |
| `backend/tests/test_scheduling.py` | Tests for `scheduling.py`. |
| `backend/tests/test_stage_timing.py` | Tests for `timing.py`. |
| `backend/tests/test_analysis_cache.py` | Tests for `analysis_cache.py`. |

**Modified backend files**

| File | Change |
|---|---|
| `app/config.py` | New settings (Task 6, 10, 11, 14). |
| `app/services/ai_pipeline/prefilter.py` | `detect_hot_regions` / `detect_silences` take `AudioTrack`; `detect_silences` vectorised. |
| `app/services/ai_pipeline/asr_engine.py` | `transcribe_regions` takes `AudioTrack`; optional progress callback; optional batching. |
| `app/services/ai_pipeline/renderer.py` | `-threads` in the render command. |
| `app/services/ai_pipeline/slideshow.py` | `-threads` in the slideshow command. |
| `app/services/ai_pipeline/tts_engine.py` | Concurrent cue / scene synthesis. |
| `app/services/ai_pipeline/stock_media.py` | Backdrop fetches go through the network slot. |
| `app/services/ai_pipeline/source.py` | Audio-first resolution + download progress. |
| `app/services/clip_runner.py` | Single decode, cache, concurrent clips, stage timings, progress events. |
| `app/services/gen_runner.py` | Concurrent scene TTS and backdrops, stage timings. |
| `app/services/clip_retention.py` | Purge expired `clip_analysis` rows. |
| `app/models/clip_models.py` | `ClipAnalysis` model. |
| `backend/tests/conftest.py` | Create the `ClipAnalysis` table for tests. |
| `backend/tests/test_prefilter.py`, `test_asr_engine.py`, `test_clip_runner.py`, `test_gen_pipeline.py`, `test_renderer.py`, `test_tts_engine.py`, `test_source.py` | Follow the signature changes. |
| `backend/scripts/eval_pipeline.py` | JSON report used as the before/after and equality gate. |

**Modified frontend files**

| File | Change |
|---|---|
| `frontend/src/components/flow-studio/useFlowJobStream.ts` | `progress?: number` on the phase event. |
| `frontend/src/components/flow-studio/JobProgress.tsx` | Interpolate the bar inside a phase. |

---

## Task 1: Stage timing recorder

**Files:**
- Create: `backend/app/services/ai_pipeline/timing.py`
- Create: `backend/tests/test_stage_timing.py`
- Modify: `backend/app/services/clip_runner.py`
- Modify: `backend/app/services/gen_runner.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class StageTimer` with `stage(name: str)` (a sync context manager usable around `await`s), `as_dict() -> dict[str, float]`, and `total() -> float`.
  - `ClipRunner`/`GenRunner` write `job.params["timings"] = timer.as_dict()` when the job finishes or errors.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_stage_timing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stage_timing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ai_pipeline.timing'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/ai_pipeline/timing.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stage_timing.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire the timer into `ClipRunner`**

In `backend/app/services/clip_runner.py`:

Add the import next to the other `ai_pipeline` imports:

```python
from app.services.ai_pipeline.timing import StageTimer
```

In `ClipRunner.__init__`, add `self._timer = StageTimer()` after `self._cancelled = False`.

Add this method next to `_record_source`:

```python
    async def _save_timings(self, job_uuid: uuid.UUID) -> None:
        """Persist the stage breakdown on the job so a slow run is diagnosable."""
        async with self._session_factory() as session:
            job = (
                await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))
            ).scalar_one_or_none()
            if job is None:
                return
            params = dict(job.params or {})
            params["timings"] = self._timer.as_dict()
            job.params = params
            await session.commit()
```

In `_process`, wrap the existing phases (do not reorder anything):

- wrap the `resolve_source(...)` call in `with self._timer.stage("resolve_source"):`
- wrap `extract_audio(...)` in `with self._timer.stage("extract_audio"):`
- wrap `detect_hot_regions(...)` in `with self._timer.stage("prefilter"):`
- wrap `detect_silences(...)` in `with self._timer.stage("silences"):`
- wrap `transcribe_regions(...)` in `with self._timer.stage("asr"):`
- wrap `select_clips(...)` in `with self._timer.stage("scoring"):`
- wrap the `for segment in segments:` loop in `with self._timer.stage("render"):`

In the `finally:` block of `_process`, before the temp-file cleanup, add:

```python
            await self._save_timings(ctx.job_uuid)
```

- [ ] **Step 6: Wire the timer into `GenRunner`**

In `backend/app/services/gen_runner.py` do the same: import `StageTimer`, add `self._timer = StageTimer()` in `__init__`, add the identical `_save_timings` method, and wrap `write_script` as `"script"`, `synthesize_scene_tracks` as `"tts"`, the backdrop loop as `"backdrops"`, and `self._render(...)` as `"render"`. Add `await self._save_timings(ctx.job_uuid)` at the top of the `finally:` block.

- [ ] **Step 7: Run the clip and gen test suites**

Run: `cd backend && python -m pytest tests/test_clip_runner.py tests/test_gen_pipeline.py tests/test_stage_timing.py -q`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/ai_pipeline/timing.py backend/tests/test_stage_timing.py backend/app/services/clip_runner.py backend/app/services/gen_runner.py
git commit -m "feat(flow-studio): record per-stage wall clock on the job"
```

---

## Task 2: Eval harness JSON report

**Files:**
- Modify: `backend/scripts/eval_pipeline.py`

**Interfaces:**
- Consumes: nothing from Task 1 (the harness times stages itself).
- Produces: `eval_out/<source-sha12>-<git-rev>.json` containing `{"source", "git_rev", "stages": {...}, "peak_rss_kb": int | null, "clips": [{"rank", "start_sec", "end_sec", "subtitle_text"}], "metrics": {...}}`. Later tasks use two of these files as the before/after and equality gate.

- [ ] **Step 1: Read the harness**

Read `backend/scripts/eval_pipeline.py` end to end. It already measures per-stage wall clock, realtime factor, hot-region coverage/recall and mid-word-cut rate, and prints them. This task only adds a machine-readable file; do not change what it measures.

- [ ] **Step 2: Add the report writer**

Add near the top of the file, after the imports:

```python
import os
import subprocess


def _git_rev() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "nogit"


def _peak_rss_kb() -> int | None:
    """Peak resident set size. POSIX only — returns None on Windows."""
    try:
        import resource
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def write_report(
    out_dir: Path,
    *,
    source_path: str,
    source_sha: str,
    stages: dict[str, float],
    clips: list[dict],
    metrics: dict,
) -> Path:
    """One JSON per run. Two of these files are the before/after comparison."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{source_sha[:12]}-{_git_rev()}.json"
    payload = {
        "source": os.path.basename(source_path),
        "source_sha256": source_sha,
        "git_rev": _git_rev(),
        "stages": stages,
        "total_sec": round(sum(stages.values()), 3),
        "peak_rss_kb": _peak_rss_kb(),
        # The equality gate: these three fields per clip must not move.
        "clips": clips,
        "metrics": metrics,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 3: Call it at the end of the single-video run**

In the function that runs one video (the `--video` path), after the existing metrics are computed, build the clip list from the scored segments the run produced and call the writer:

```python
    clips = [
        {
            "rank": segment.rank,
            "start_sec": segment.start_sec,
            "end_sec": segment.end_sec,
            "subtitle_text": segment.subtitle_text,
        }
        for segment in segments
    ]
    report_path = write_report(
        Path("eval_out"),
        source_path=video_path,
        source_sha=source_sha,
        stages=stage_seconds,
        clips=clips,
        metrics=metrics,
    )
    print(f"report: {report_path}")
```

Use the harness's existing variable names for `segments`, `stage_seconds`, `metrics`, `source_sha` and `video_path` — if a name differs, adapt to the harness, do not rename the harness's variables.

- [ ] **Step 4: Verify the harness still imports and shows help**

Run: `cd backend && python scripts/eval_pipeline.py --help`
Expected: usage text, exit 0, no traceback.

- [ ] **Step 5: Record the baseline**

This step needs the fixed 30–120 minute sample video agreed in the spec. Put it at `backend/samples/baseline.mp4` (git-ignored).

Run: `cd backend && python scripts/eval_pipeline.py --video samples/baseline.mp4`
Expected: a JSON file appears under `backend/eval_out/`. **Copy it to `backend/eval_out/BASELINE.json` and keep it** — every later task compares against this file.

If the sample video is not available yet, stop here and report that Task 2 is blocked on it. Do not start Task 3: without a baseline no later gate can be evaluated.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/eval_pipeline.py
git commit -m "feat(flow-studio): eval harness writes a JSON before/after report"
```

---

## Task 3: `AudioTrack` — decode the audio once

**Files:**
- Create: `backend/app/services/ai_pipeline/audio.py`
- Create: `backend/tests/test_audio_track.py`
- Modify: `backend/app/services/ai_pipeline/prefilter.py`
- Modify: `backend/app/services/ai_pipeline/asr_engine.py`
- Modify: `backend/tests/test_prefilter.py`
- Modify: `backend/tests/test_asr_engine.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `AudioTrack(samples: np.ndarray, sample_rate: int)` with `.duration_sec -> float`.
  - `load_track(wav_path: str) -> AudioTrack`.
  - `prefilter.detect_hot_regions(track: AudioTrack, *, min_region_sec: float, max_region_sec: float, max_regions: int, frame_sec: float = 0.5) -> list[HotRegion]`
  - `prefilter.detect_silences(track: AudioTrack, *, threshold_db: float = -35.0, min_silence_sec: float = 0.3, frame_sec: float = 0.1) -> list[tuple[float, float]]`
  - `asr_engine.transcribe_regions(track: AudioTrack, regions, *, language: str | None = None) -> Transcript`
  - `prefilter.read_pcm16_mono` and `prefilter.frame_db` keep their current signatures.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_audio_track.py`:

```python
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.ai_pipeline.audio import AudioTrack, load_track

SAMPLE_RATE = 16000


@pytest.fixture()
def wav_path(tmp_path: Path) -> str:
    path = tmp_path / "audio.wav"
    n = 5 * SAMPLE_RATE
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    pcm = (0.5 * np.sin(2 * math.pi * 220.0 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return str(path)


def test_load_track_returns_normalised_mono_samples(wav_path: str):
    track = load_track(wav_path)
    assert track.sample_rate == SAMPLE_RATE
    assert track.samples.dtype == np.float32
    assert float(np.max(np.abs(track.samples))) <= 1.0


def test_duration_sec_matches_the_sample_count(wav_path: str):
    track = load_track(wav_path)
    assert track.duration_sec == pytest.approx(5.0, abs=0.01)


def test_duration_sec_of_an_empty_track_is_zero():
    track = AudioTrack(samples=np.zeros(0, dtype=np.float32), sample_rate=16000)
    assert track.duration_sec == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_audio_track.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ai_pipeline.audio'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/ai_pipeline/audio.py`:

```python
"""One decoded copy of a job's audio, shared by every stage that needs it.

A two-hour source at 16 kHz is ~115 million float32 samples — about 460 MB.
The pipeline used to decode that WAV three separate times (hot regions,
silences, ASR), paying the decode and the allocation once per caller. Decoding
once and passing this object around removes two of the three.

Deliberately a value object: it knows nothing about jobs, the database or video.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.ai_pipeline.prefilter import read_pcm16_mono


@dataclass(frozen=True)
class AudioTrack:
    samples: np.ndarray   # float32, mono, [-1, 1]
    sample_rate: int

    @property
    def duration_sec(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return len(self.samples) / float(self.sample_rate)


def load_track(wav_path: str) -> AudioTrack:
    """Decode a 16-bit PCM WAV once."""
    samples, sample_rate = read_pcm16_mono(wav_path)
    return AudioTrack(samples=samples, sample_rate=sample_rate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_audio_track.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Change `prefilter` to take an `AudioTrack`**

In `backend/app/services/ai_pipeline/prefilter.py`:

Do **not** import `audio.py` (it imports this module — that would be a cycle). Type the parameter with a string annotation and `TYPE_CHECKING`:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.ai_pipeline.audio import AudioTrack
```

Change the two entry points to take the track and drop their own decode. `detect_silences`:

```python
def detect_silences(
    track: "AudioTrack",
    *,
    threshold_db: float = -35.0,
    min_silence_sec: float = 0.3,
    frame_sec: float = 0.1,
) -> list[tuple[float, float]]:
    """Return [(start_sec, end_sec)] spans quieter than `threshold_db`."""
    db = frame_db(track.samples, track.sample_rate, frame_sec=frame_sec)
    quiet = db < threshold_db
    ...
```

and `detect_hot_regions`:

```python
def detect_hot_regions(
    track: "AudioTrack",
    *,
    min_region_sec: float,
    max_region_sec: float,
    max_regions: int,
    frame_sec: float = _DEFAULT_FRAME_SEC,
) -> list[HotRegion]:
    ...
    db = frame_db(track.samples, track.sample_rate, frame_sec=frame_sec)
    ...
```

Delete the `samples, sample_rate = read_pcm16_mono(wav_path)` line from both. Keep every other line of both functions exactly as it is. The log line at the end of `detect_hot_regions` references `wav_path`; change that one argument to `"track"` so the format string still has an argument.

- [ ] **Step 6: Change `asr_engine.transcribe_regions` to take an `AudioTrack`**

In `backend/app/services/ai_pipeline/asr_engine.py`, replace the head of `transcribe_regions`:

```python
async def transcribe_regions(
    track: "AudioTrack",
    regions: Sequence[HotRegion],
    *,
    language: str | None = None,
) -> Transcript:
    """Transcribe each hot region. When `regions` is empty the whole track is
    treated as a single region (prefilter found nothing — better slow than empty)."""
    loop = asyncio.get_running_loop()
    samples, sample_rate = track.samples, track.sample_rate
    total_sec = track.duration_sec
```

Add the same `TYPE_CHECKING` import block as in Step 5, and delete the now-unused `from app.services.ai_pipeline.prefilter import read_pcm16_mono` import. The rest of the function is unchanged. The `logger.warning("no hot regions for %s; ...", audio_path, total_sec)` line loses its path — change it to `logger.warning("no hot regions; transcribing full %.1fs", total_sec)`.

- [ ] **Step 7: Update the existing tests to the new signatures**

In `backend/tests/test_prefilter.py`: import `load_track` from `app.services.ai_pipeline.audio`, and change the `loud_middle_wav` fixture and the two `tmp_path` tests to pass `load_track(path)` instead of the path string into `detect_silences` / `detect_hot_regions`. Keep `read_pcm16_mono` and `frame_db` tests as they are.

In `backend/tests/test_asr_engine.py`: change the three `transcribe_regions(wav_path, ...)` calls to `transcribe_regions(load_track(wav_path), ...)` and change `test_slice_samples_extracts_the_region` to build the track through `load_track`.

- [ ] **Step 8: Update the runner call sites**

In `backend/app/services/clip_runner.py`, inside the ANALYZING phase, replace the three separate calls so the WAV is decoded once:

```python
            with self._timer.stage("decode_audio"):
                track = load_track(audio_path)

            with self._timer.stage("prefilter"):
                regions = detect_hot_regions(
                    track,
                    min_region_sec=settings.CLIP_PREFILTER_MIN_REGION_SEC,
                    max_region_sec=settings.CLIP_PREFILTER_MAX_REGION_SEC,
                    max_regions=min(
                        settings.CLIP_PREFILTER_MAX_REGIONS,
                        max(8, ctx.top_n * 4),
                    ),
                )
            with self._timer.stage("silences"):
                silences = detect_silences(track)
            self._abort_point(ctx)
            with self._timer.stage("asr"):
                transcript = await transcribe_regions(track, regions)
```

Add `from app.services.ai_pipeline.audio import load_track` to the imports.

- [ ] **Step 9: Update `test_clip_runner.py`'s fakes**

The fixture stubs `detect_hot_regions(wav_path, **kwargs)` and `detect_silences(wav_path, **kwargs)`. Rename their first parameter to `track` and add a `load_track` stub so no real WAV parsing happens:

```python
    def fake_load_track(wav_path):
        return object()  # the fakes below never look inside it

    def fake_detect_hot_regions(track, **kwargs):
        state["prefilter_max_regions"].append(kwargs["max_regions"])
        return [HotRegion(index=0, start_sec=0.0, end_sec=120.0, energy=-12.0)]

    def fake_detect_silences(track, **kwargs):
        return [(39.0, 40.5)]

    async def fake_transcribe_regions(track, regions, **kwargs):
        ...  # body unchanged
```

and register it: `monkeypatch.setattr(runner_mod, "load_track", fake_load_track)`.

- [ ] **Step 10: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/ai_pipeline/audio.py backend/app/services/ai_pipeline/prefilter.py backend/app/services/ai_pipeline/asr_engine.py backend/app/services/clip_runner.py backend/tests/
git commit -m "perf(flow-studio): decode the job audio once and share it"
```

---

## Task 4: Vectorise `detect_silences`

**Files:**
- Modify: `backend/app/services/ai_pipeline/prefilter.py`
- Modify: `backend/tests/test_prefilter.py`

**Interfaces:**
- Consumes: `AudioTrack` and the Task 3 signature of `detect_silences`.
- Produces: no signature change. Output must be identical to the loop version.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_prefilter.py`:

```python
def test_detect_silences_matches_a_reference_scan(tmp_path: Path):
    """The vectorised run finder must agree with a plain scan, span for span."""
    path = tmp_path / "alternating.wav"
    segments: list[tuple[float, float]] = []
    for _ in range(5):
        segments.append((0.8, 0.9))
        segments.append((0.6, 0.001))
    _write_wav(path, segments)
    track = load_track(str(path))

    got = detect_silences(track, threshold_db=-35.0, min_silence_sec=0.3, frame_sec=0.1)

    # Reference: the straightforward scan the vectorised version replaces.
    db = frame_db(track.samples, track.sample_rate, frame_sec=0.1)
    quiet = db < -35.0
    expected: list[tuple[float, float]] = []
    run_start = None
    for i, is_quiet in enumerate(quiet):
        if is_quiet and run_start is None:
            run_start = i
        elif not is_quiet and run_start is not None:
            if (i - run_start) * 0.1 >= 0.3:
                expected.append((round(run_start * 0.1, 3), round(i * 0.1, 3)))
            run_start = None
    if run_start is not None and (len(quiet) - run_start) * 0.1 >= 0.3:
        expected.append((round(run_start * 0.1, 3), round(len(quiet) * 0.1, 3)))

    assert got == expected


def test_detect_silences_on_fully_quiet_audio_is_one_span(tmp_path: Path):
    path = tmp_path / "quiet.wav"
    _write_wav(path, [(3.0, 0.0)])
    spans = detect_silences(load_track(str(path)), min_silence_sec=0.3, frame_sec=0.1)
    assert len(spans) == 1
    assert spans[0][0] == 0.0


def test_detect_silences_on_fully_loud_audio_is_empty(tmp_path: Path):
    path = tmp_path / "loud.wav"
    _write_wav(path, [(3.0, 0.9)])
    assert detect_silences(load_track(str(path)), min_silence_sec=0.3, frame_sec=0.1) == []
```

Add `frame_db` to the imports at the top of the test file if it is not already there.

- [ ] **Step 2: Run the tests to confirm they pass against the current loop**

Run: `cd backend && python -m pytest tests/test_prefilter.py -v`
Expected: PASS. These tests pin the *current* behaviour before it is rewritten — that is the point. If they fail now, the reference scan in the test does not match the implementation; fix the test, not the implementation.

- [ ] **Step 3: Replace the loop with a vectorised run finder**

In `detect_silences`, replace the `for i, is_quiet in enumerate(quiet):` block (and the `if run_start is not None:` tail) with:

```python
    # A two-hour source at frame_sec=0.1 is 72 000 frames; a Python loop over
    # that is the slowest part of an otherwise numpy-only module. `np.diff` on
    # the padded boolean finds every run boundary in one pass.
    padded = np.concatenate(([False], quiet, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)

    out: list[tuple[float, float]] = []
    for start_idx, end_idx in zip(starts, ends):
        start = float(start_idx) * frame_sec
        end = float(end_idx) * frame_sec
        if end - start >= min_silence_sec:
            out.append((round(start, 3), round(end, 3)))
    return out
```

Delete the old `spans` list and the loop that filtered it.

- [ ] **Step 4: Run the tests again**

Run: `cd backend && python -m pytest tests/test_prefilter.py -v`
Expected: PASS — same results as Step 2, now from the vectorised path.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai_pipeline/prefilter.py backend/tests/test_prefilter.py
git commit -m "perf(flow-studio): vectorise the silence run finder"
```

---

## Task 5: Equality gate for Tasks 3–4

**Files:**
- No source changes. This task runs the gate defined in the spec §6.2.

**Interfaces:**
- Consumes: `backend/eval_out/BASELINE.json` from Task 2.
- Produces: a recorded verdict. Nothing later depends on code from this task.

- [ ] **Step 1: Run the equality gate**

Run, from `backend/`:

```bash
SCORING_BACKEND=heuristic python scripts/eval_pipeline.py --video samples/baseline.mp4
```

On Windows PowerShell: `$env:SCORING_BACKEND = "heuristic"; python scripts/eval_pipeline.py --video samples/baseline.mp4`

`heuristic` is the deterministic tier of `scorer.py` — pure numpy, no network. Running the gate against `gemini` compares two different LLM answers and reports a difference that is not a regression.

- [ ] **Step 2: Compare the clips against the baseline**

The baseline in `eval_out/BASELINE.json` was recorded with the LLM backend, so it cannot be compared directly. Record a **heuristic baseline once** by checking out the pre-Task-3 commit, running the same command, and saving the result as `eval_out/BASELINE-heuristic.json`:

```bash
git stash list  # ensure a clean tree first
git worktree add ../flowmeta-baseline <commit-before-task-3>
cd ../flowmeta-baseline/backend && SCORING_BACKEND=heuristic python scripts/eval_pipeline.py --video ../../Comment_Edit_Delete/backend/samples/baseline.mp4
```

Copy that report to `backend/eval_out/BASELINE-heuristic.json` in the main worktree, then remove the temporary worktree: `git worktree remove ../flowmeta-baseline`.

Compare:

```bash
cd backend && python -c "import json,sys; a=json.load(open('eval_out/BASELINE-heuristic.json'))['clips']; b=json.load(open('eval_out/<new-report>.json'))['clips']; sys.exit(0 if a==b else 1)"; echo "exit=$?"
```

Expected: `exit=0`. A non-zero exit means Task 3 or 4 changed behaviour — stop and fix before continuing.

- [ ] **Step 3: Compare the timings**

Open both reports and compare `stages`. Expected: `decode_audio` appears once instead of the decode cost being paid inside `prefilter`, `silences` and `asr`; `silences` drops sharply. Record the two numbers in the commit message.

- [ ] **Step 4: Commit the gate result**

```bash
git add backend/eval_out/BASELINE-heuristic.json
git commit -m "test(flow-studio): record the deterministic baseline for the equality gate"
```

---

## Task 6: Resource slots

**Files:**
- Create: `backend/app/services/ai_pipeline/scheduling.py`
- Create: `backend/tests/test_scheduling.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `scheduling.cpu_slots() -> int`, `net_slots() -> int`, `tts_slots() -> int`, `ffmpeg_threads() -> int`
  - async context managers `cpu_slot()`, `net_slot()`, `tts_slot()`
  - `reset_slots() -> None` for tests
  - Settings `FLOW_CPU_SLOTS: int = 0`, `FLOW_NET_SLOTS: int = 8`, `FLOW_TTS_SLOTS: int = 4` (`0` on `FLOW_CPU_SLOTS` means auto).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scheduling.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_scheduling.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ai_pipeline.scheduling'`

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`, next to the other Flow/clip settings:

```python
    # --- Flow pipeline resource slots -----------------------------------
    # Work is split by the resource it actually consumes. Before this, a job
    # waiting on the edge-TTS endpoint held the whole pipeline, and so did an
    # ffmpeg burn — one sequential lane for three different kinds of waiting.
    FLOW_CPU_SLOTS: int = 0             # 0 = auto: cores - 1
    FLOW_NET_SLOTS: int = 8
    FLOW_TTS_SLOTS: int = 4             # edge-tts is unofficial; stay polite
```

Add the same three keys with their defaults to `.env.example` under a `# Flow pipeline` comment.

- [ ] **Step 4: Write the implementation**

Create `backend/app/services/ai_pipeline/scheduling.py`:

```python
"""Concurrency slots, one per kind of resource.

Three kinds of work with three different limits:
- CPU: whisper, x264, OpenCV. More of these than cores makes everything slower.
- Network: yt-dlp, stock photo fetches. Bound by latency, not by cores.
- TTS: also network, but against an unofficial endpoint that must not be
  hammered, so it gets a smaller allowance of its own.

Semaphores are created lazily and torn down by `reset_slots()` because an
`asyncio.Semaphore` binds to the running loop, and the tests (and the worker's
restart path) do not share one loop.
"""
from __future__ import annotations

import asyncio
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.config import settings

_CPU: asyncio.Semaphore | None = None
_NET: asyncio.Semaphore | None = None
_TTS: asyncio.Semaphore | None = None


def cpu_slots() -> int:
    configured = int(settings.FLOW_CPU_SLOTS)
    if configured > 0:
        return configured
    # Leave one core for the event loop, the DB driver and the OS.
    return max(1, (os.cpu_count() or 2) - 1)


def net_slots() -> int:
    return max(1, int(settings.FLOW_NET_SLOTS))


def tts_slots() -> int:
    return max(1, int(settings.FLOW_TTS_SLOTS))


def ffmpeg_threads() -> int:
    """Threads for one ffmpeg process.

    Without this, N concurrent encodes each grab every core and spend their
    time fighting each other — concurrency that is slower than running them
    one at a time.
    """
    return max(1, math.floor((os.cpu_count() or 2) / cpu_slots()))


def reset_slots() -> None:
    """Drop the cached semaphores (tests, worker restart)."""
    global _CPU, _NET, _TTS
    _CPU = _NET = _TTS = None


@asynccontextmanager
async def cpu_slot() -> AsyncIterator[None]:
    global _CPU
    if _CPU is None:
        _CPU = asyncio.Semaphore(cpu_slots())
    async with _CPU:
        yield


@asynccontextmanager
async def net_slot() -> AsyncIterator[None]:
    global _NET
    if _NET is None:
        _NET = asyncio.Semaphore(net_slots())
    async with _NET:
        yield


@asynccontextmanager
async def tts_slot() -> AsyncIterator[None]:
    global _TTS
    if _TTS is None:
        _TTS = asyncio.Semaphore(tts_slots())
    async with _TTS:
        yield
```

`async with semaphore` releases on cancellation and on exceptions, which is exactly what the two release tests check.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_scheduling.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai_pipeline/scheduling.py backend/tests/test_scheduling.py backend/app/config.py .env.example
git commit -m "feat(flow-studio): CPU, network and TTS concurrency slots"
```

---

## Task 7: Pin ffmpeg thread counts

**Files:**
- Modify: `backend/app/services/ai_pipeline/renderer.py`
- Modify: `backend/app/services/ai_pipeline/slideshow.py`
- Modify: `backend/tests/test_renderer.py`
- Modify: `backend/tests/test_gen_pipeline.py`

**Interfaces:**
- Consumes: `scheduling.ffmpeg_threads()`.
- Produces: `build_render_command` and `build_slideshow_command` emit `-threads <n>` before the output path. Signatures unchanged.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_renderer.py`:

```python
def test_build_render_command_pins_the_thread_count(monkeypatch):
    # Concurrent encodes that each take every core are slower than sequential
    # ones. The slot count decides how many threads each process may use.
    from app.services.ai_pipeline import scheduling

    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 4)
    monkeypatch.setattr(scheduling.os, "cpu_count", lambda: 8)

    cmd = build_render_command(
        "in.mp4", "out.mp4", crop=CROP, ass_path="s.ass", font_dir="/fonts"
    )
    assert "-threads" in cmd
    assert cmd[cmd.index("-threads") + 1] == "2"
```

Use the `CROP` constant already defined in that test file; if it is not defined there, copy the one from `tests/test_tts_engine.py`.

Add to `backend/tests/test_gen_pipeline.py`:

```python
def test_build_slideshow_command_pins_the_thread_count(monkeypatch):
    from app.services.ai_pipeline import scheduling
    from app.services.ai_pipeline.slideshow import build_slideshow_command

    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 2)
    monkeypatch.setattr(scheduling.os, "cpu_count", lambda: 8)

    cmd = build_slideshow_command(
        [("a.jpg", 3.0)],
        "out.mp4",
        audio_path=None,
        ass_path="s.ass",
        font_dir="/fonts",
        escape_path=lambda p: p,
    )
    assert cmd[cmd.index("-threads") + 1] == "4"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_renderer.py::test_build_render_command_pins_the_thread_count tests/test_gen_pipeline.py::test_build_slideshow_command_pins_the_thread_count -v`
Expected: FAIL with `ValueError: '-threads' is not in list`

- [ ] **Step 3: Add the flag to both commands**

In `renderer.py`, import `from app.services.ai_pipeline.scheduling import ffmpeg_threads` and add to the returned list in `build_render_command`, right before `"-movflags", "+faststart"`:

```python
        "-threads", str(ffmpeg_threads()),
```

In `slideshow.py`, import the same helper and add the identical pair to the returned list in `build_slideshow_command`, right before `"-movflags", "+faststart"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_renderer.py tests/test_gen_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_pipeline/renderer.py backend/app/services/ai_pipeline/slideshow.py backend/tests/test_renderer.py backend/tests/test_gen_pipeline.py
git commit -m "perf(flow-studio): pin ffmpeg thread counts to the CPU slot budget"
```

---

## Task 8: Speak TTS cues concurrently

**Files:**
- Modify: `backend/app/services/ai_pipeline/tts_engine.py`
- Modify: `backend/tests/test_tts_engine.py`

**Interfaces:**
- Consumes: `scheduling.tts_slot()`.
- Produces: `build_voice_track` and `synthesize_scene_tracks` keep their exact signatures and return values. Only the internal scheduling changes; the returned `parts` and `tracks` must stay in cue/scene order.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_tts_engine.py`:

```python
import asyncio
from pathlib import Path

import pytest

from app.services.ai_pipeline import scheduling, tts_engine


@pytest.fixture()
def concurrent_tts(monkeypatch, tmp_path: Path):
    """Records how many syntheses were in flight at once."""
    state = {"live": 0, "peak": 0, "order": []}

    async def fake_synthesize_cue(text, out_path, *, voice):
        state["live"] += 1
        state["peak"] = max(state["peak"], state["live"])
        state["order"].append(text)
        await asyncio.sleep(0.02)
        Path(out_path).write_bytes(b"mp3")
        state["live"] -= 1
        return True

    async def fake_probe_duration(path):
        return 1.0

    async def fake_mix_tracks(parts, out_path, *, total_sec):
        state["parts"] = list(parts)
        Path(out_path).write_bytes(b"m4a")
        return out_path

    monkeypatch.setattr(tts_engine, "synthesize_cue", fake_synthesize_cue)
    monkeypatch.setattr(tts_engine, "probe_duration", fake_probe_duration)
    monkeypatch.setattr(tts_engine, "mix_tracks", fake_mix_tracks)
    monkeypatch.setattr(scheduling.settings, "FLOW_TTS_SLOTS", 4)
    scheduling.reset_slots()
    return state


async def test_build_voice_track_speaks_cues_concurrently(concurrent_tts, tmp_path: Path):
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(8)]
    out = await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=8.0, work_dir=tmp_path, base="job",
    )
    assert out is not None
    assert concurrent_tts["peak"] > 1


async def test_build_voice_track_keeps_cue_order(concurrent_tts, tmp_path: Path):
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(8)]
    await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=8.0, work_dir=tmp_path, base="job",
    )
    # Concurrency must not reorder the mix: part i starts at cue i's timestamp.
    starts = [start for _path, start, _tempo in concurrent_tts["parts"]]
    assert starts == sorted(starts)
    assert starts == [float(i) for i in range(8)]


async def test_build_voice_track_respects_the_tts_slot_limit(monkeypatch, concurrent_tts, tmp_path: Path):
    monkeypatch.setattr(scheduling.settings, "FLOW_TTS_SLOTS", 2)
    scheduling.reset_slots()
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(8)]
    await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=8.0, work_dir=tmp_path, base="job",
    )
    assert concurrent_tts["peak"] == 2


async def test_build_voice_track_skips_a_failing_cue(monkeypatch, concurrent_tts, tmp_path: Path):
    async def flaky(text, out_path, *, voice):
        if text == "cue 2":
            return False
        Path(out_path).write_bytes(b"mp3")
        return True

    monkeypatch.setattr(tts_engine, "synthesize_cue", flaky)
    cues = [(float(i), float(i) + 1.0, f"cue {i}") for i in range(4)]
    await tts_engine.build_voice_track(
        cues, str(tmp_path / "voice.m4a"),
        voice_id="vi-female", total_sec=4.0, work_dir=tmp_path, base="job",
    )
    starts = [start for _path, start, _tempo in concurrent_tts["parts"]]
    assert starts == [0.0, 1.0, 3.0]


async def test_synthesize_scene_tracks_runs_scenes_concurrently(concurrent_tts, tmp_path: Path):
    tracks = await tts_engine.synthesize_scene_tracks(
        [f"scene {i}" for i in range(6)],
        voice_id="vi-female", work_dir=tmp_path, base="gen",
    )
    assert len(tracks) == 6
    assert concurrent_tts["peak"] > 1
    assert all(duration == 1.0 for _path, duration in tracks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_tts_engine.py -k concurrent -v`
Expected: FAIL — `concurrent_tts["peak"]` is `1`, because the current implementation awaits one cue at a time.

- [ ] **Step 3: Rewrite `build_voice_track`'s loop as a gather**

Replace the body of the `try:` block in `build_voice_track` with:

```python
        async def speak(index: int, cue: tuple[float, float, str]):
            start, end, text = cue
            spoken_path = str(work_dir / f"{base}_tts_{index}.mp3")
            async with tts_slot():
                if not await synthesize_cue(text, spoken_path, voice=voice):
                    return None
            spoken = await probe_duration(spoken_path)
            if spoken <= 0:
                return spoken_path, None
            window = max(0.1, float(end) - float(start))
            tempo = tempo_for(spoken, window, cap=settings.TTS_MAX_TEMPO)
            return spoken_path, (spoken_path, float(start), tempo)

        results = await asyncio.gather(
            *(speak(i, cue) for i, cue in enumerate(cues))
        )

        # gather preserves input order, so the mix keeps cue order without
        # sorting — a cue that failed simply contributes nothing.
        for result in results:
            if result is None:
                continue
            path, part = result
            temp_files.append(path)
            if part is not None:
                parts.append(part)

        if not parts:
            logger.warning("voice-over produced no audio; keeping the source track")
            return None
        ...
```

Keep the `mix_tracks` call, the logging and the `finally:` cleanup exactly as they are. Add `from app.services.ai_pipeline.scheduling import tts_slot` to the imports.

- [ ] **Step 4: Rewrite `synthesize_scene_tracks` as a gather**

```python
async def synthesize_scene_tracks(
    texts: list[str], *, voice_id: str | None, work_dir: Path, base: str
) -> list[tuple[str, float]]:
    """Speak each scene and report how long it took.

    Gen video works the other way round from reup: the narration decides how
    long its scene lasts, so the caller needs the measured durations before it
    can lay out the timeline. Order is load-bearing — `lay_out_scenes` zips
    these against the script's scenes — and `gather` preserves it.
    """
    voice = resolve_voice(voice_id)

    async def speak(index: int, text: str) -> tuple[str, float]:
        path = str(work_dir / f"{base}_scene_{index}.mp3")
        async with tts_slot():
            if not await synthesize_cue(text, path, voice=voice):
                return ("", 0.0)
        return (path, await probe_duration(path))

    return list(await asyncio.gather(*(speak(i, text) for i, text in enumerate(texts))))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_tts_engine.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai_pipeline/tts_engine.py backend/tests/test_tts_engine.py
git commit -m "perf(flow-studio): speak TTS cues and scenes concurrently"
```

---

## Task 9: Render clips concurrently, fetch backdrops concurrently

**Files:**
- Modify: `backend/app/services/clip_runner.py`
- Modify: `backend/app/services/gen_runner.py`
- Modify: `backend/app/services/ai_pipeline/stock_media.py`
- Modify: `backend/tests/test_clip_runner.py`
- Modify: `backend/tests/test_gen_pipeline.py`

**Interfaces:**
- Consumes: `scheduling.cpu_slot()`, `scheduling.net_slot()`.
- Produces: `ClipRunner._render_one` unchanged in signature and return shape. `_process` gathers them. Row order (and therefore `rank` order) must still match `segments` order.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_clip_runner.py` (the fixture `fake_pipeline` and the helpers `_make_job` already exist — reuse them):

```python
async def test_clips_render_concurrently(fake_pipeline, session, monkeypatch, tmp_path):
    from app.services.ai_pipeline import scheduling

    monkeypatch.setattr(scheduling.settings, "FLOW_CPU_SLOTS", 4)
    scheduling.reset_slots()

    live = {"now": 0, "peak": 0}

    async def slow_burn(input_path, output_path, **kwargs):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.03)
        Path(output_path).write_bytes(b"rendered")
        live["now"] -= 1
        return True

    monkeypatch.setattr(runner_mod, "burn_vertical", slow_burn)

    # ...create the job and run the runner exactly as the existing tests do...
    assert live["peak"] == 2  # the fixture's fake_select_clips returns 2 segments


async def test_clip_rows_keep_rank_order(fake_pipeline, session):
    # Concurrency must not shuffle the gallery: rank 1 is the top clip.
    # ...run the runner...
    clips = (await session.execute(select(Clip).order_by(Clip.rank))).scalars().all()
    assert [clip.rank for clip in clips] == [1, 2]


async def test_one_failing_clip_does_not_fail_the_job(fake_pipeline, session, monkeypatch):
    async def burn_one_bad(input_path, output_path, **kwargs):
        if output_path.endswith("_clip_2.mp4"):
            return False
        Path(output_path).write_bytes(b"rendered")
        return True

    monkeypatch.setattr(runner_mod, "burn_vertical", burn_one_bad)
    # ...run the runner...
    job = (await session.execute(select(ClipJob))).scalar_one()
    assert job.status == ClipJobStatus.DONE
    statuses = {c.rank: c.status for c in (await session.execute(select(Clip))).scalars()}
    assert statuses[1] == ClipStatus.READY
    assert statuses[2] == ClipStatus.ERROR
```

Fill the `# ...` lines by copying the job-creation and run block from the existing tests in that file (they build a `ClipJob`, construct `ClipRunner(session_factory, publish)` and `await runner.run(str(job.id))`). Add `import asyncio` at the top of the test file if it is not already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_clip_runner.py -k "concurrently or rank_order or failing_clip" -v`
Expected: `test_clips_render_concurrently` FAILS with `assert 1 == 2`. The other two may already pass — that is fine, they are regression guards for this change.

- [ ] **Step 3: Gather the clip renders**

In `clip_runner._process`, replace the render loop:

```python
            # ---- RENDERING ----
            self._abort_point(ctx)
            await self._set_phase(ctx, ClipJobStatus.RENDERING, "rendering")
            font_name = resolve_font_name(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)
            with self._timer.stage("render"):
                # gather, not a loop: the clips are independent, and the loop
                # left every core but one idle while one clip encoded.
                # `gather` preserves order, so rows stay in rank order.
                rows = list(
                    await asyncio.gather(
                        *(
                            self._render_one(
                                ctx, segment, local_source, work_dir,
                                silences, font_name, temp_paths,
                            )
                            for segment in segments
                        )
                    )
                )
            await self._save_clips(ctx, rows)
```

`_render_one` already catches every exception and returns an ERROR row, so `gather` cannot raise here and `return_exceptions` is not needed.

- [ ] **Step 4: Hold a CPU slot only around the CPU-bound calls**

Inside `_render_one`, wrap the two expensive calls, leaving the network-bound TTS outside the slot:

```python
            async with cpu_slot():
                crop = await compute_crop_path(raw_path, 0.0, end - start)
```

and

```python
            async with cpu_slot():
                burned = await burn_vertical(
                    raw_path,
                    final_path,
                    crop=crop,
                    ass_path=ass_path,
                    font_dir=settings.CLIP_FONT_DIR,
                    audio_path=voice_path,
                )
            if not burned:
                raise RuntimeError("ffmpeg subtitle burn failed")
```

Holding a CPU slot across the TTS wait would idle a core for the whole network round trip — that is the exact mistake this task exists to remove.

Add `from app.services.ai_pipeline.scheduling import cpu_slot` to the imports. Keep `self._abort_point(ctx)` at the top of `_render_one` so a cancelled job stops the clips that have not started.

- [ ] **Step 5: Run backdrop fetches concurrently in `gen_runner`**

Replace the `for i, scene in enumerate(script.scenes):` block in `gen_runner._process` with a gather over a helper that keeps the existing per-scene logic verbatim:

```python
            async def prepare_scene(i: int, scene) -> tuple[str, str]:
                image = uploaded_image_for_scene(ctx.image_paths, i, len(script.scenes))
                visual_source = "uploaded" if image else ""
                if image and not os.path.isfile(image):
                    raise RuntimeError(f"uploaded image is missing for scene {i + 1}")
                if image is None:
                    image = await resolve_backdrop(scene.image_query, work_dir, base, i)
                    visual_source = backdrop_source(image) if image else ""
                if image is None:
                    raise RuntimeError(f"could not obtain a backdrop for scene {i + 1}")
                return image, visual_source

            with self._timer.stage("backdrops"):
                prepared = await asyncio.gather(
                    *(prepare_scene(i, scene) for i, scene in enumerate(script.scenes))
                )

            backdrops: list[tuple[str, float]] = []
            visual_sources: list[str] = []
            for i, (image, visual_source) in enumerate(prepared):
                if visual_source != "uploaded":
                    temp_paths.append(image)
                backdrops.append((image, timeline.durations[i]))
                visual_sources.append(visual_source)
```

A missing backdrop still raises and still fails the job, exactly as before — `gather` propagates the first exception.

- [ ] **Step 6: Put the stock fetches behind the network slot**

In `stock_media.py`, wrap the two HTTP fetchers. In `fetch_stock_image` and `fetch_commons_image`, put `async with net_slot():` immediately inside the `try:` around the `httpx.AsyncClient` block. Import `from app.services.ai_pipeline.scheduling import net_slot`.

- [ ] **Step 7: Wrap the gen slideshow encode in a CPU slot**

In `gen_runner._render`, wrap the `spawn`/`communicate` pair for the slideshow command in `async with cpu_slot():` and import the helper.

- [ ] **Step 8: Run the affected suites**

Run: `cd backend && python -m pytest tests/test_clip_runner.py tests/test_gen_pipeline.py tests/test_scheduling.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 10: Run the equality gate**

Repeat Task 5 Step 1–2 against `eval_out/BASELINE-heuristic.json`. Expected: `exit=0`, and the `render` stage noticeably lower.

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/clip_runner.py backend/app/services/gen_runner.py backend/app/services/ai_pipeline/stock_media.py backend/tests/
git commit -m "perf(flow-studio): render clips and fetch backdrops concurrently"
```

---

## Task 10: Batched ASR (verification first)

**Files:**
- Modify: `backend/app/services/ai_pipeline/asr_engine.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_asr_engine.py`
- Possibly modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: the Task 3 `transcribe_regions(track, regions, *, language=None)`.
- Produces: no signature change. New setting `ASR_BATCH_SIZE: int = 8` where `0` means "use the sequential path".

- [ ] **Step 1: Verify the pinned library can do this at all**

`backend/requirements.txt` pins `faster-whisper==1.0.3`. The batched API and, critically, whether it returns **word timestamps** in batched mode, differ between releases. The pipeline cannot work without word timestamps — `scorer.clamp_to_words`, `cutter.resegment` and `subtitle_gen` all depend on them.

Run: `cd backend && python -c "import faster_whisper, inspect; print(faster_whisper.__version__); print(hasattr(faster_whisper, 'BatchedInferencePipeline')); print(inspect.signature(faster_whisper.BatchedInferencePipeline.transcribe) if hasattr(faster_whisper,'BatchedInferencePipeline') else 'n/a')"`

Three outcomes:

- **`BatchedInferencePipeline` exists and its `transcribe` accepts `word_timestamps`** → continue to Step 2.
- **It does not exist, or it rejects `word_timestamps`** → bump `faster-whisper` to `>=1.1.0` in `requirements.txt`, reinstall, and run the check again.
- **Still unavailable after the bump** → **stop and report.** Do not implement a batched path that drops word timestamps. Record the finding in the commit message, skip to Task 11, and leave `ASR_BATCH_SIZE` unimplemented.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/test_asr_engine.py`:

```python
class FakeBatchedPipeline:
    """Stands in for faster_whisper.BatchedInferencePipeline."""

    def __init__(self, model):
        self.model = model
        self.calls = 0
        self.batch_sizes: list[int] = []

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        self.batch_sizes.append(kwargs.get("batch_size"))
        assert kwargs.get("word_timestamps") is True
        segments = [
            FakeSegment(" hello world", [FakeWord(0.0, 0.4, " hello"), FakeWord(0.5, 1.0, " world")])
        ]
        return iter(segments), FakeInfo()


async def test_batched_path_still_offsets_word_timestamps(monkeypatch, wav_path: str):
    from app.services.ai_pipeline.audio import load_track

    pipeline = FakeBatchedPipeline(FakeModel())
    monkeypatch.setattr(asr_engine, "_get_batched_pipeline", lambda: pipeline)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 4)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=30.0, end_sec=35.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)

    assert pipeline.batch_sizes == [4, 4]
    assert transcript.regions[1].words[0].start == pytest.approx(30.0)


async def test_batch_size_zero_uses_the_sequential_model(monkeypatch, wav_path: str):
    from app.services.ai_pipeline.audio import load_track

    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)

    regions = [HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0)]
    await asr_engine.transcribe_regions(load_track(wav_path), regions)

    assert model.calls == 1


async def test_a_failing_region_is_still_skipped_in_batched_mode(monkeypatch, wav_path: str):
    from app.services.ai_pipeline.audio import load_track

    class ExplodingPipeline(FakeBatchedPipeline):
        def transcribe(self, audio, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("ctranslate2 blew up")
            return super().transcribe(audio, **kwargs)

    pipeline = ExplodingPipeline(FakeModel())
    monkeypatch.setattr(asr_engine, "_get_batched_pipeline", lambda: pipeline)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 4)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=10.0, end_sec=15.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(load_track(wav_path), regions)
    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.index == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_asr_engine.py -k "batch" -v`
Expected: FAIL with `AttributeError: ... has no attribute '_get_batched_pipeline'`

- [ ] **Step 4: Add the setting**

In `backend/app/config.py`, next to the other ASR settings:

```python
    # 0 disables batching and restores the one-region-at-a-time path. Batched
    # decoding can shift word timestamps slightly, so it must be switchable
    # off without a code change.
    ASR_BATCH_SIZE: int = 8
```

Add it to `.env.example`.

- [ ] **Step 5: Implement the batched path**

In `asr_engine.py`, add the lazy pipeline next to `_get_model`:

```python
_BATCHED = None


def _get_batched_pipeline():
    global _BATCHED
    if _BATCHED is None:
        from faster_whisper import BatchedInferencePipeline

        logger.info("loading batched whisper pipeline (batch_size=%d)", settings.ASR_BATCH_SIZE)
        _BATCHED = BatchedInferencePipeline(model=_get_model())
    return _BATCHED
```

Extend `reset_model_cache()` to also clear `_BATCHED`.

Change `_transcribe_slice` to choose the engine:

```python
def _transcribe_slice(audio: np.ndarray, language: str | None) -> tuple[str, list[Word], str]:
    batch_size = int(settings.ASR_BATCH_SIZE)
    kwargs = dict(
        beam_size=settings.ASR_BEAM_SIZE,
        vad_filter=True,
        word_timestamps=True,
        language=language,
    )
    if batch_size > 0:
        engine = _get_batched_pipeline()
        kwargs["batch_size"] = batch_size
    else:
        engine = _get_model()
    segments, info = engine.transcribe(audio, **kwargs)
    ...  # the rest of the function is unchanged
```

Everything else — the per-region loop, the exception skip, the timestamp shift — stays exactly as it is.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_asr_engine.py -v`
Expected: PASS

- [ ] **Step 7: Run the quality gate (not the equality gate)**

Batched decoding may move word timestamps, so the "byte-identical clips" gate does **not** apply here. Run the harness against the sample video and compare `metrics` in the new report to `eval_out/BASELINE-heuristic.json`:

```bash
cd backend && SCORING_BACKEND=heuristic python scripts/eval_pipeline.py --video samples/baseline.mp4
```

Pass condition, both required:
- **mid-word-cut rate** is not higher than the baseline.
- **hot-region recall** is not lower than the baseline.

If either regresses, set `ASR_BATCH_SIZE=0` as the shipped default, record the measured numbers in the commit message, and keep the code — the switch is the deliverable either way.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/ai_pipeline/asr_engine.py backend/app/config.py backend/tests/test_asr_engine.py .env.example backend/requirements.txt
git commit -m "perf(flow-studio): batched ASR decoding behind ASR_BATCH_SIZE"
```

---

## Task 11: Audio-first source resolution for links

**Files:**
- Modify: `backend/app/services/ai_pipeline/source.py`
- Modify: `backend/app/services/clip_runner.py`
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_source.py`
- Modify: `backend/tests/test_clip_runner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:

```python
@dataclass
class ResolvedSource:
    analysis_media: str          # file the 16 kHz WAV is extracted from
    analysis_is_temp: bool
    video_path: str | None       # None while the download is still running
    video_task: asyncio.Task | None
    video_is_temp: bool

async def resolve_source_audio_first(
    source_type: ClipSourceType, source_ref: str, work_dir: Path, job_id: str
) -> ResolvedSource: ...

async def await_video(resolved: ResolvedSource) -> str: ...

def build_audio_download_command(url: str, output_path: str) -> list[str]: ...
```

`resolve_source` keeps its current signature and behaviour — it is the fallback path and the tests for it stay valid.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_source.py`:

```python
import asyncio
from pathlib import Path

from app.models.clip_models import ClipSourceType
from app.services.ai_pipeline import source as source_mod
from app.services.ai_pipeline.source import (
    build_audio_download_command,
    resolve_source_audio_first,
    await_video,
)


def test_build_audio_download_command_asks_for_audio_only():
    cmd = build_audio_download_command("https://youtu.be/x", "/tmp/a.m4a")
    assert "-f" in cmd
    assert cmd[cmd.index("-f") + 1] == "ba"
    assert "/tmp/a.m4a" in cmd


async def test_upload_source_needs_no_download(tmp_path: Path):
    upload = tmp_path / "upload.mp4"
    upload.write_bytes(b"video")
    resolved = await resolve_source_audio_first(
        ClipSourceType.UPLOAD, str(upload), tmp_path, "job-1"
    )
    assert resolved.analysis_media == str(upload)
    assert resolved.video_path == str(upload)
    assert resolved.video_task is None
    assert await await_video(resolved) == str(upload)


async def test_link_source_returns_audio_before_the_video_lands(monkeypatch, tmp_path: Path):
    """The point of the whole task: analysis starts while the video downloads."""
    video_started = asyncio.Event()

    async def fake_run(cmd):
        out = cmd[cmd.index("-o") + 1]
        if cmd[cmd.index("-f") + 1] == "ba":
            Path(out).write_bytes(b"audio")
            return 0, ""
        video_started.set()
        await asyncio.sleep(0.05)
        Path(out).write_bytes(b"video")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)
    resolved = await resolve_source_audio_first(
        ClipSourceType.LINK, "https://youtu.be/x", tmp_path, "job-2"
    )

    assert Path(resolved.analysis_media).read_bytes() == b"audio"
    assert resolved.analysis_is_temp is True
    assert resolved.video_path is None          # still downloading
    assert resolved.video_task is not None

    video = await await_video(resolved)
    assert Path(video).read_bytes() == b"video"
    assert video_started.is_set()


async def test_link_falls_back_to_a_plain_video_download(monkeypatch, tmp_path: Path):
    async def fake_run(cmd):
        out = cmd[cmd.index("-o") + 1]
        if cmd[cmd.index("-f") + 1] == "ba":
            return 1, "audio-only format not available"
        Path(out).write_bytes(b"video")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)
    resolved = await resolve_source_audio_first(
        ClipSourceType.LINK, "https://youtu.be/x", tmp_path, "job-3"
    )
    # No audio track: analysis reads the video itself, exactly as before.
    assert Path(resolved.analysis_media).read_bytes() == b"video"
    assert await await_video(resolved) == resolved.analysis_media


async def test_audio_first_can_be_switched_off(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(source_mod.settings, "CLIP_SOURCE_AUDIO_FIRST", False)
    calls: list[str] = []

    async def fake_run(cmd):
        calls.append(cmd[cmd.index("-f") + 1])
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"video")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)
    resolved = await resolve_source_audio_first(
        ClipSourceType.LINK, "https://youtu.be/x", tmp_path, "job-4"
    )
    assert "ba" not in calls
    assert resolved.video_task is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_source.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_audio_download_command'`

- [ ] **Step 3: Add the setting**

In `backend/app/config.py`:

```python
    # Analysis only needs audio. Fetching ~50 MB of audio first lets ASR run
    # while the multi-GB video is still downloading. Off = one download, as before.
    CLIP_SOURCE_AUDIO_FIRST: bool = True
```

Add it to `.env.example`.

- [ ] **Step 4: Implement it**

Add to `backend/app/services/ai_pipeline/source.py`:

```python
@dataclass
class ResolvedSource:
    """What the pipeline can start on, and what is still on its way.

    Analysis only ever reads audio, so it does not have to wait for a 1080p
    download to finish. The video is awaited immediately before the cut.
    """

    analysis_media: str
    analysis_is_temp: bool
    video_path: str | None
    video_task: "asyncio.Task[str] | None"
    video_is_temp: bool


def build_audio_download_command(url: str, output_path: str) -> list[str]:
    return [
        settings.YTDLP_BIN,
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "-f", "ba",
        "-o", output_path,
        url,
    ]


async def _download_video(url: str, output_path: str) -> str:
    code, stderr = await _run(build_download_command(url, output_path))
    if code != 0 or not Path(output_path).is_file():
        raise SourceUnavailable(
            f"download failed: {stderr.strip()[-500:] or 'unknown error'}"
        )
    return output_path


async def resolve_source_audio_first(
    source_type: ClipSourceType,
    source_ref: str,
    work_dir: Path,
    job_id: str,
) -> ResolvedSource:
    work_dir.mkdir(parents=True, exist_ok=True)

    if source_type == ClipSourceType.UPLOAD:
        if not Path(source_ref).is_file():
            raise SourceUnavailable(f"uploaded source is missing: {source_ref}")
        return ResolvedSource(
            analysis_media=source_ref, analysis_is_temp=False,
            video_path=source_ref, video_task=None, video_is_temp=False,
        )

    video_path = str(work_dir / f"{job_id}_source.mp4")

    if settings.CLIP_SOURCE_AUDIO_FIRST:
        audio_path = str(work_dir / f"{job_id}_source_audio.m4a")
        code, stderr = await _run(build_audio_download_command(source_ref, audio_path))
        if code == 0 and Path(audio_path).is_file():
            logger.info("audio ready for job %s; video downloads in the background", job_id)
            return ResolvedSource(
                analysis_media=audio_path, analysis_is_temp=True,
                video_path=None,
                video_task=asyncio.create_task(_download_video(source_ref, video_path)),
                video_is_temp=True,
            )
        # Some sites have no audio-only format, some rate-limit the second
        # request. Either way the old single-download path still works.
        logger.info(
            "audio-only download unavailable for job %s (%s); falling back",
            job_id, stderr.strip()[-200:] or "no output",
        )

    path = await _download_video(source_ref, video_path)
    return ResolvedSource(
        analysis_media=path, analysis_is_temp=True,
        video_path=path, video_task=None, video_is_temp=True,
    )


async def await_video(resolved: ResolvedSource) -> str:
    """Block until the video file exists. Cheap when it already does."""
    if resolved.video_path is not None:
        return resolved.video_path
    if resolved.video_task is None:
        raise SourceUnavailable("no video source was resolved")
    resolved.video_path = await resolved.video_task
    return resolved.video_path
```

Add `from dataclasses import dataclass` to the imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_source.py -v`
Expected: PASS

- [ ] **Step 6: Wire it into `ClipRunner._process`**

Replace the `resolve_source(...)` call:

```python
            with self._timer.stage("resolve_source"):
                resolved = await resolve_source_audio_first(
                    ctx.source_type, ctx.source_ref, work_dir, ctx.job_id
                )
            if resolved.analysis_is_temp:
                temp_paths.append(resolved.analysis_media)
```

Point `extract_audio` at `resolved.analysis_media`. Then, immediately before the RENDERING phase:

```python
            # The cut needs real video. By now ASR and scoring have run, so the
            # download has had the whole analysis to finish.
            with self._timer.stage("await_video"):
                local_source = await await_video(resolved)
            if resolved.video_is_temp and local_source not in temp_paths:
                temp_paths.append(local_source)
            self._abort_point(ctx)
            await self._record_source(ctx, sha256_file(local_source))
```

Move the existing `_record_source` call down to here — it hashes the video, and for a link the video does not exist yet at the old call site. Replace the `resolve_source` import with `resolve_source_audio_first, await_video, ResolvedSource`.

- [ ] **Step 7: Update the runner test fixture**

In `tests/test_clip_runner.py`, replace the `fake_resolve_source` stub:

```python
    async def fake_resolve(source_type, source_ref, work_dir, job_id):
        path = tmp_path / "source.mp4"
        path.write_bytes(b"video-bytes")
        return runner_mod.ResolvedSource(
            analysis_media=str(path), analysis_is_temp=False,
            video_path=str(path), video_task=None, video_is_temp=False,
        )

    monkeypatch.setattr(runner_mod, "resolve_source_audio_first", fake_resolve)
```

Leave `await_video` un-stubbed — with `video_path` already set it returns immediately.

- [ ] **Step 8: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/ai_pipeline/source.py backend/app/services/clip_runner.py backend/app/config.py backend/tests/ .env.example
git commit -m "perf(flow-studio): start analysis on link audio while the video downloads"
```

---

## Task 12: `clip_analysis` model and migration

**Files:**
- Modify: `backend/app/models/clip_models.py`
- Create: `backend/alembic/versions/20260810_0010_clip_analysis.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_clip_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ClipAnalysis` with columns `id: UUID`, `cache_key: str` (unique), `owner_id: UUID` (FK `users.id`, NOT NULL), `payload: JSONB`, `created_at`, `last_used_at`, `hit_count: int`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_clip_models.py`:

```python
async def test_clip_analysis_round_trips(session, user_id):
    from app.models.clip_models import ClipAnalysis

    row = ClipAnalysis(
        cache_key="abc123",
        owner_id=user_id,
        payload={"version": 1, "language": "vi", "regions": [], "words": [], "silences": []},
    )
    session.add(row)
    await session.commit()

    found = (
        await session.execute(select(ClipAnalysis).where(ClipAnalysis.cache_key == "abc123"))
    ).scalar_one()
    assert found.payload["language"] == "vi"
    assert found.hit_count == 0
    assert found.created_at is not None
    assert found.last_used_at is not None


async def test_clip_analysis_cache_key_is_unique(session, user_id):
    from app.models.clip_models import ClipAnalysis
    from sqlalchemy.exc import IntegrityError

    session.add(ClipAnalysis(cache_key="dup", owner_id=user_id, payload={"version": 1}))
    await session.commit()
    session.add(ClipAnalysis(cache_key="dup", owner_id=user_id, payload={"version": 1}))
    with pytest.raises(IntegrityError):
        await session.commit()
```

Use the same `session` and `user_id` fixtures the other tests in that file use; if `user_id` does not exist there, create a `User` the way the neighbouring tests do.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_clip_models.py -k analysis -v`
Expected: FAIL with `ImportError: cannot import name 'ClipAnalysis'`

- [ ] **Step 3: Add the model**

In `backend/app/models/clip_models.py`, following the style of the models already there:

```python
class ClipAnalysis(Base):
    """Cached transcript for one audio track, for one user.

    The transcript depends only on the audio and the ASR/prefilter settings —
    not on top_n, the length band, the editing instructions, the voice or the
    LLM backend. Re-running the same source with different instructions used to
    pay the full ASR bill again, and that is the most common thing a user does.

    Scoped per user on purpose: two accounts uploading byte-identical files do
    not share a transcript.
    """

    __tablename__ = "clip_analysis"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
```

Match the exact import names and column-type aliases already used in that file (`PGUUID`, `JSONB`, `Mapped`, `mapped_column`); do not introduce new ones.

- [ ] **Step 4: Register the table for tests**

In `backend/tests/conftest.py`, add `ClipAnalysis` to the `from app.models.clip_models import ...` line and to the tuple of tables created in the `session` fixture. Without this the new tests fail with `no such table: clip_analysis` — the fixture creates tables explicitly, it does not use `create_all`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_clip_models.py -v`
Expected: PASS

- [ ] **Step 6: Write the migration**

Read `backend/alembic/versions/20260729_0009_clip_retention.py` first and copy its structure. Create `backend/alembic/versions/20260810_0010_clip_analysis.py`:

```python
"""clip analysis cache

Revision ID: 20260810_0010
Revises: 20260729_0009
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260810_0010"
down_revision = "20260729_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clip_analysis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_clip_analysis_cache_key", "clip_analysis", ["cache_key"], unique=True)
    op.create_index("ix_clip_analysis_owner_id", "clip_analysis", ["owner_id"])
    op.create_index("ix_clip_analysis_last_used_at", "clip_analysis", ["last_used_at"])


def downgrade() -> None:
    op.drop_index("ix_clip_analysis_last_used_at", table_name="clip_analysis")
    op.drop_index("ix_clip_analysis_owner_id", table_name="clip_analysis")
    op.drop_index("ix_clip_analysis_cache_key", table_name="clip_analysis")
    op.drop_table("clip_analysis")
```

Check the real revision id of `20260729_0009_clip_retention.py` and use it verbatim for `down_revision`.

- [ ] **Step 7: Verify the migration chain**

Run: `cd backend && python -m alembic heads`
Expected: exactly one head, `20260810_0010`. Two heads means `down_revision` is wrong.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/clip_models.py backend/alembic/versions/20260810_0010_clip_analysis.py backend/tests/conftest.py backend/tests/test_clip_models.py
git commit -m "feat(flow-studio): clip_analysis table for cached transcripts"
```

---

## Task 13: Analysis cache service

**Files:**
- Create: `backend/app/services/ai_pipeline/analysis_cache.py`
- Create: `backend/tests/test_analysis_cache.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Consumes: `ClipAnalysis` (Task 12), `Transcript` / `RegionTranscript` / `HotRegion` / `Word` from `ai_pipeline.types`.
- Produces:

```python
PAYLOAD_VERSION = 1

def build_cache_key(*, owner_id: str, audio_sha256: str, prefilter: dict) -> str
def encode_analysis(transcript: Transcript, silences: list[tuple[float, float]]) -> dict
def decode_analysis(payload: dict) -> tuple[Transcript, list[tuple[float, float]]] | None
async def get_analysis(session_factory, cache_key: str) -> tuple[Transcript, list[tuple[float, float]]] | None
async def put_analysis(session_factory, *, cache_key: str, owner_id: str, transcript: Transcript, silences: list[tuple[float, float]]) -> None
async def purge_expired(session_factory, ttl_days: int) -> int
```

New settings: `CLIP_ANALYSIS_CACHE_ENABLED: bool = True`, `CLIP_ANALYSIS_TTL_DAYS: int = 14`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_analysis_cache.py`:

```python
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


async def test_put_then_get_returns_the_transcript(session_factory, user_id):
    await analysis_cache.put_analysis(
        session_factory, cache_key="k1", owner_id=str(user_id),
        transcript=_transcript(), silences=[(1.0, 2.0)],
    )
    got = await analysis_cache.get_analysis(session_factory, "k1")
    assert got is not None
    assert got[0].regions[0].text == "xin chào"


async def test_get_counts_the_hit(session_factory, user_id):
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


async def test_put_twice_updates_instead_of_colliding(session_factory, user_id):
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


async def test_purge_expired_removes_only_stale_rows(session_factory, user_id):
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
```

This test needs a `session_factory` fixture (an async callable returning a session context manager) and a `user_id`. `backend/tests/test_clip_retention.py` already exercises services that take a `session_factory` — copy its fixture setup into `conftest.py` if it is local to that file, or reuse it as-is if it is already shared. Do not invent a second pattern.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_analysis_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ai_pipeline.analysis_cache'`

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`:

```python
    CLIP_ANALYSIS_CACHE_ENABLED: bool = True
    CLIP_ANALYSIS_TTL_DAYS: int = 14
```

Add both to `.env.example`.

- [ ] **Step 4: Write the implementation**

Create `backend/app/services/ai_pipeline/analysis_cache.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_analysis_cache.py -v`
Expected: PASS (13 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai_pipeline/analysis_cache.py backend/tests/test_analysis_cache.py backend/app/config.py .env.example
git commit -m "feat(flow-studio): per-user transcript cache service"
```

---

## Task 14: Use the cache in the runner and sweep it

**Files:**
- Modify: `backend/app/services/clip_runner.py`
- Modify: `backend/app/services/clip_retention.py`
- Modify: `backend/app/modules/flow_video/runtime.py`
- Modify: `backend/tests/test_clip_runner.py`
- Modify: `backend/tests/test_clip_retention.py`

**Interfaces:**
- Consumes: `analysis_cache.*` (Task 13), `ResolvedSource` (Task 11).
- Produces: no new public interface. `sweep_once` gains a `"analysis_purged"` key in its summary dict.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_clip_runner.py`:

```python
async def test_a_cache_hit_skips_extract_prefilter_and_asr(fake_pipeline, session, monkeypatch):
    """The payoff: re-running a source with new instructions costs no ASR."""
    calls = {"extract": 0, "asr": 0}

    async def counting_extract(video_path, audio_path):
        calls["extract"] += 1
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(b"wav")
        return True

    async def counting_asr(track, regions, **kwargs):
        calls["asr"] += 1
        return Transcript(language="en", regions=(
            RegionTranscript(region=regions[0], text="hello", words=(Word(0.0, 0.5, "hello"),)),
        ))

    monkeypatch.setattr(runner_mod, "extract_audio", counting_extract)
    monkeypatch.setattr(runner_mod, "transcribe_regions", counting_asr)

    # ...run the runner twice against two jobs with the same source...

    assert calls["extract"] == 1
    assert calls["asr"] == 1


async def test_the_cache_is_bypassed_when_disabled(fake_pipeline, session, monkeypatch):
    monkeypatch.setattr(runner_mod.settings, "CLIP_ANALYSIS_CACHE_ENABLED", False)
    # ...run twice as above...
    assert calls["asr"] == 2
```

Add to `backend/tests/test_clip_retention.py`:

```python
async def test_sweep_purges_expired_analysis_rows(session_factory, user_id, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.models.clip_models import ClipAnalysis
    from app.services.ai_pipeline import analysis_cache

    await analysis_cache.put_analysis(
        session_factory, cache_key="old", owner_id=str(user_id),
        transcript=_transcript(), silences=[],
    )
    async with session_factory() as s:
        row = (await s.execute(select(ClipAnalysis))).scalar_one()
        row.last_used_at = datetime.now(timezone.utc) - timedelta(days=90)
        await s.commit()

    summary = await sweep_once(session_factory)
    assert summary["analysis_purged"] == 1
```

Reuse `_transcript()` by importing it from `tests/test_analysis_cache.py`, or copy the six-line helper into this file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_clip_runner.py -k cache tests/test_clip_retention.py -k analysis -v`
Expected: FAIL — ASR runs twice, and `summary` has no `"analysis_purged"` key.

- [ ] **Step 3: Wire the cache into `_process`**

Replace the ANALYZING block in `clip_runner._process`:

```python
            prefilter_params = {
                "min_region_sec": settings.CLIP_PREFILTER_MIN_REGION_SEC,
                "max_region_sec": settings.CLIP_PREFILTER_MAX_REGION_SEC,
                "max_regions": min(
                    settings.CLIP_PREFILTER_MAX_REGIONS, max(8, ctx.top_n * 4)
                ),
            }
            # Hashing the media the ANALYSIS reads, not the video: for a link the
            # video is still downloading, and the transcript depends on the audio
            # anyway.
            with self._timer.stage("hash_source"):
                cache_key = build_cache_key(
                    owner_id=ctx.user_id,
                    audio_sha256=sha256_file(resolved.analysis_media),
                    prefilter=prefilter_params,
                )

            await self._set_phase(ctx, ClipJobStatus.ANALYZING, "analyzing")
            cached = await get_analysis(self._session_factory, cache_key)
            if cached is not None:
                transcript, silences = cached
            else:
                if not await extract_audio(resolved.analysis_media, audio_path):
                    raise RuntimeError("failed to extract audio from the source video")
                with self._timer.stage("decode_audio"):
                    track = load_track(audio_path)
                with self._timer.stage("prefilter"):
                    regions = detect_hot_regions(track, **prefilter_params)
                with self._timer.stage("silences"):
                    silences = detect_silences(track)
                self._abort_point(ctx)
                with self._timer.stage("asr"):
                    transcript = await transcribe_regions(track, regions)
                if not transcript.regions:
                    raise RuntimeError("ASR produced no usable speech regions")
                await put_analysis(
                    self._session_factory,
                    cache_key=cache_key,
                    owner_id=ctx.user_id,
                    transcript=transcript,
                    silences=silences,
                )

            if not transcript.regions:
                raise RuntimeError("ASR produced no usable speech regions")
```

`detect_hot_regions` now takes the same dict that feeds the cache key, so the two can never drift. Wrap `extract_audio` in `with self._timer.stage("extract_audio"):`. Import `build_cache_key, get_analysis, put_analysis` from `app.services.ai_pipeline.analysis_cache`.

- [ ] **Step 4: Purge the cache in the retention sweeper**

In `backend/app/services/clip_retention.py`, inside `sweep_once`, after the existing purge work:

```python
    analysis_purged = await purge_expired(
        session_factory, settings.CLIP_ANALYSIS_TTL_DAYS
    )
```

and add `"analysis_purged": analysis_purged` to the returned summary dict. Import `from app.services.ai_pipeline.analysis_cache import purge_expired`.

- [ ] **Step 5: Extend the worker log line**

In `backend/app/flow_worker.py`, the sweeper logs `cancelled` and `purged`. Add the new counter so an operator can see the cache being swept:

```python
        if summary["cancelled"] or summary["purged"] or summary["analysis_purged"]:
            logger.info(
                "retention sweep: cancelled=%d purged=%d files=%d bytes=%d analysis=%d",
                summary["cancelled"], summary["purged"], summary["files"],
                summary["bytes"], summary["analysis_purged"],
            )
```

- [ ] **Step 6: Re-export from the module runtime if needed**

`app/modules/flow_video/runtime.py` re-exports `sweep_once`. Read it; if it re-exports named symbols rather than the module, no change is needed. Only add an export if something new is imported from it.

- [ ] **Step 7: Run the affected suites**

Run: `cd backend && python -m pytest tests/test_clip_runner.py tests/test_clip_retention.py tests/test_analysis_cache.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS

- [ ] **Step 9: Run the equality gate twice**

```bash
cd backend && SCORING_BACKEND=heuristic python scripts/eval_pipeline.py --video samples/baseline.mp4
cd backend && SCORING_BACKEND=heuristic python scripts/eval_pipeline.py --video samples/baseline.mp4
```

Expected: both reports' `clips` match `eval_out/BASELINE-heuristic.json`, and the second run's `stages` shows `extract_audio`, `prefilter`, `silences` and `asr` at or near zero. Note: the harness calls the pipeline stages directly, so if it does not go through `ClipRunner` the cache will not engage there — in that case verify the hit by running the same source through the real worker twice and reading `params["timings"]` on both jobs.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/clip_runner.py backend/app/services/clip_retention.py backend/app/flow_worker.py backend/tests/
git commit -m "perf(flow-studio): reuse cached transcripts and sweep them on TTL"
```

---

## Task 15: Progress inside a phase

**Files:**
- Modify: `backend/app/services/ai_pipeline/asr_engine.py`
- Modify: `backend/app/services/ai_pipeline/source.py`
- Modify: `backend/app/services/clip_runner.py`
- Modify: `backend/tests/test_asr_engine.py`
- Modify: `backend/tests/test_clip_runner.py`
- Modify: `frontend/src/components/flow-studio/useFlowJobStream.ts`
- Modify: `frontend/src/components/flow-studio/JobProgress.tsx`

**Interfaces:**
- Consumes: the existing `publish("clip", "phase", {...})` event.
- Produces:
  - `transcribe_regions(track, regions, *, language=None, on_progress: Callable[[int, int], Awaitable[None]] | None = None)`
  - `resolve_source_audio_first(..., on_progress: Callable[[float], Awaitable[None]] | None = None)`
  - The `phase` SSE event may carry `progress: number` in `[0, 1]`.

**Why the callbacks are async:** both are called from inside an async loop, so
they can simply be awaited. A sync callback would force the runner to
`asyncio.create_task(...)` and drop the reference — an unreferenced task can be
garbage-collected mid-flight, so progress events would go missing at random.

- [ ] **Step 1: Write the failing backend test**

Add to `backend/tests/test_asr_engine.py`:

```python
async def test_transcribe_regions_reports_progress(monkeypatch, wav_path: str):
    from app.services.ai_pipeline.audio import load_track

    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)
    monkeypatch.setattr(asr_engine.settings, "ASR_BATCH_SIZE", 0)

    seen: list[tuple[int, int]] = []

    async def record(done: int, total: int) -> None:
        seen.append((done, total))

    regions = [
        HotRegion(index=i, start_sec=i * 10.0, end_sec=i * 10.0 + 5.0, energy=-10.0)
        for i in range(3)
    ]
    await asr_engine.transcribe_regions(load_track(wav_path), regions, on_progress=record)
    assert seen == [(1, 3), (2, 3), (3, 3)]
```

Add to `backend/tests/test_clip_runner.py`:

```python
async def test_phase_events_carry_progress(fake_pipeline, session):
    # A 15-minute job with a bar that never moves reads as a hung job.
    # ...run the runner, collecting published events...
    phase_events = [e for e in published if e[1] == "phase"]
    assert any("progress" in e[2] for e in phase_events)
    for _channel, _kind, body in phase_events:
        if "progress" in body:
            assert 0.0 <= body["progress"] <= 1.0
```

The fixture already records published events in `state["published"]`; use that list rather than adding a second capture mechanism.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_asr_engine.py -k progress tests/test_clip_runner.py -k progress -v`
Expected: FAIL with `TypeError: transcribe_regions() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 3: Add the ASR callback**

In `transcribe_regions`, add the parameter and call it after each region is appended (including regions that were skipped, so the count still reaches the total):

```python
async def transcribe_regions(
    track: "AudioTrack",
    regions: Sequence[HotRegion],
    *,
    language: str | None = None,
    on_progress: "Callable[[int, int], Awaitable[None]] | None" = None,
) -> Transcript:
```

and at the end of each loop iteration:

```python
        if on_progress is not None:
            await on_progress(index + 1, len(targets))
```

Use `for index, region in enumerate(targets):` and make sure the callback fires on the `continue` paths too — restructure the `continue`s into a single `if`/`else` so the callback is the last statement of the loop body. A region that failed still finished; skipping the tick would freeze the bar on exactly the run that went wrong.

Add `from collections.abc import Awaitable, Callable, Sequence` to the imports.

- [ ] **Step 4: Add the download progress callback**

In `source.py`, add `on_progress: "Callable[[float], Awaitable[None]] | None" = None` to `resolve_source_audio_first` (it passes the callback straight through to `_download_video`) and parse yt-dlp's output for the video download. Replace `_download_video` with a streaming version:

```python
async def _download_video(
    url: str, output_path: str, on_progress=None
) -> str:
    if on_progress is None:
        # No listener, no reason to parse output: keep the plain `_run` path,
        # which is also the one tests/test_source.py stubs.
        code, stderr = await _run(build_download_command(url, output_path))
        if code != 0 or not Path(output_path).is_file():
            raise SourceUnavailable(
                f"download failed: {stderr.strip()[-500:] or 'unknown error'}"
            )
        return output_path

    # --no-progress suppresses the percentage entirely; --newline makes each
    # update its own line so it can be read without a terminal.
    cmd = [arg for arg in build_download_command(url, output_path) if arg != "--no-progress"]
    cmd += ["--newline"]
    process = await procs.spawn(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    if on_progress is not None and process.stdout is not None:
        pattern = re.compile(r"\[download\]\s+([\d.]+)%")
        async for raw in process.stdout:
            match = pattern.search(raw.decode(errors="replace"))
            if match:
                await on_progress(min(1.0, float(match.group(1)) / 100.0))
    _, stderr = await procs.communicate(process)
    if process.returncode != 0 or not Path(output_path).is_file():
        raise SourceUnavailable(
            f"download failed: {stderr.decode(errors='replace').strip()[-500:] or 'unknown error'}"
        )
    return output_path
```

Add `import re` and keep `_run` untouched — the audio download and the fallback still use it, and `tests/test_source.py` stubs it.

- [ ] **Step 5: Publish the progress from the runner**

In `clip_runner`, extend `_set_phase` with an optional fraction and add a lightweight publisher:

```python
    async def _publish_progress(self, ctx: JobContext, phase: str, progress: float) -> None:
        """Intra-phase tick. No DB write — the status has not changed."""
        await self._publish(
            "clip",
            "phase",
            {
                "user_id": ctx.user_id,
                "job_id": ctx.job_id,
                "phase": phase,
                "progress": round(max(0.0, min(1.0, progress)), 3),
            },
        )
```

Wire it in three places:

```python
                async def tick_asr(done: int, total: int) -> None:
                    await self._publish_progress(ctx, "analyzing", done / max(1, total))

                transcript = await transcribe_regions(track, regions, on_progress=tick_asr)
```

This sits inside the cache-miss branch added in Task 14 — a cache hit has no ASR to report on, and jumps straight to 100% of the analyzing phase.

For the render phase, replace the plain `gather` with one that ticks as each clip lands:

```python
                done = 0

                async def render_and_tick(segment):
                    nonlocal done
                    row = await self._render_one(
                        ctx, segment, local_source, work_dir, silences, font_name, temp_paths
                    )
                    done += 1
                    await self._publish_progress(ctx, "rendering", done / len(segments))
                    return row

                rows = list(await asyncio.gather(*(render_and_tick(s) for s in segments)))
```

And for the download, define the same shape of helper before the `resolve_source_audio_first` call and pass it in:

```python
            async def tick_download(fraction: float) -> None:
                await self._publish_progress(ctx, "queued", fraction)
```

- [ ] **Step 6: Run the backend tests**

Run: `cd backend && python -m pytest tests/test_asr_engine.py tests/test_clip_runner.py tests/test_source.py -v`
Expected: PASS

- [ ] **Step 7: Read the Next.js docs before touching the frontend**

`frontend/AGENTS.md` requires it: this Next.js version differs from what you may expect. Read the relevant guide under `frontend/node_modules/next/dist/docs/` before editing.

- [ ] **Step 8: Add `progress` to the stream event type**

In `frontend/src/components/flow-studio/useFlowJobStream.ts`, add `progress?: number` to the phase variant of the event union. Do not change anything else in that file.

- [ ] **Step 9: Interpolate the bar in `JobProgress.tsx`**

Keep the existing `PERCENT` map as the phase *floor* and interpolate towards the next phase:

```tsx
// Where each phase ends, so an in-phase fraction can be interpolated instead of
// leaving the bar frozen for the ten minutes a long job spends in ASR.
const PHASE_END: Record<string, number> = {
  queued: 30,
  analyzing: 60,
  scripting: 55,
  scoring: 85,
  gathering: 85,
  rendering: 100,
};

const [progress, setProgress] = useState(0);
```

In the stream handler:

```tsx
    if (event.type === "phase") {
      setPhase(event.phase);
      setProgress(typeof event.progress === "number" ? event.progress : 0);
    }
```

Reset `progress` to `0` in the polling effect's `setPhase(phaseFromStatus(job.status))` branch, and compute:

```tsx
  const floor = PERCENT[phase] ?? 5;
  const ceiling = PHASE_END[phase] ?? floor;
  const percent = Math.round(floor + (ceiling - floor) * progress);
```

- [ ] **Step 10: Verify the frontend builds**

Run: `cd frontend && npm run lint && npm run build`
Expected: both succeed with no new errors. There is no frontend test runner in this repo — lint and build are the checks.

- [ ] **Step 11: Verify by eye**

Start the stack and run one real job on the sample video. Expected: the bar advances inside "Đang bóc băng video…" as regions complete and inside "Đang cắt và render…" as clips land, instead of jumping only at phase boundaries.

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/ai_pipeline/asr_engine.py backend/app/services/ai_pipeline/source.py backend/app/services/clip_runner.py backend/tests/ frontend/src/components/flow-studio/
git commit -m "feat(flow-studio): report progress inside a phase, not only at its edges"
```

---

## Final verification

- [ ] **Full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS, no skips that were not skipped before.

- [ ] **Migration chain**

Run: `cd backend && python -m alembic heads`
Expected: one head, `20260810_0010`.

- [ ] **Equality gate**

Run the harness once more with `SCORING_BACKEND=heuristic` and diff `clips` against `eval_out/BASELINE-heuristic.json`. Expected: identical.

- [ ] **Speed report**

Compare the final report's `stages` and `total_sec` against `eval_out/BASELINE.json` and write the before/after table into the PR description: per stage, and the total. State the machine's core count — the numbers mean nothing without it.

- [ ] **Cancellation smoke test**

Start a real job, cancel it mid-render, then start another job. Expected: the second job runs. If it hangs, a semaphore leaked (see Task 6, risk 2) — that failure is silent and this is the only check that catches it.
