# Flow Studio AI Pipeline (Real Runner) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ad-hoc v0 clip pipeline with a real CPU-only long-to-short pipeline: audio prefilter → region-scoped Whisper ASR → LLM rubric scoring + Vietnamese translation → keyframe-snapped ffmpeg cut → 9:16 crop → ASS subtitle burn-in, driven by a runner that keeps DB sessions short and isolates per-clip failure.

**Architecture:** Every stage lives in its own module under `backend/app/services/ai_pipeline/` and communicates through frozen dataclasses defined in `types.py`. Stages are pure-ish functions over file paths + dataclasses so each is unit-testable without a DB, without ffmpeg where possible, and without network. `ClipRunner` is the only stateful piece: it resolves the source, calls the stages in order, opens a short DB session per phase boundary, and publishes SSE events. Pluggable backends (`ASR_BACKEND`, `SCORING_BACKEND`) are resolved from settings at call time, never at import time, so tests can monkeypatch.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (`MappedAsDataclass`), pytest + pytest-asyncio (`asyncio_mode = auto`), faster-whisper (CTranslate2, int8, CPU), numpy, OpenCV (headless), ffmpeg/ffprobe subprocesses, yt-dlp, httpx, `anthropic` SDK (optional Claude scoring backend).

## Global Constraints

- **CPU only.** No CUDA, no NVENC, no GPU-only libraries. Whisper runs `device="cpu"`, `compute_type="int8"`.
- **Source language is arbitrary; output language is Vietnamese.** Whisper runs multilingual (auto language detect). The LLM translates the selected segments into natural Vietnamese. Do NOT assume Vietnamese-source or use PhoWhisper.
- **Subtitles are burned server-side** as ASS with `libx264 -preset veryfast`, using the Be Vietnam Pro font so Vietnamese diacritics render correctly.
- **Default scoring backend is `gemini`** (`GEMINI_API_KEY` already exists in config). `ollama`, `claude`, and `heuristic` are alternates.
- **Only `ffmpeg`, `ffprobe`, and `yt-dlp` may be shelled out to.** Always via `asyncio.create_subprocess_exec` with an argument list — never `shell=True`, never string interpolation into a shell.
- **No new DB columns and no new Alembic revision.** The migration chain is shared with the Face module. Anything extra goes inside the existing `ClipJob.params` / `Clip.clipspec` JSONB.
- **Face module stays untouched.** Do not edit `app/main.py`, `app/face_app.py`, or anything under Face routers/services.
- **Tests must not require ffmpeg, network, a model download, or a GPU.** Anything that would is marked `@pytest.mark.integration` and skipped by default.
- **All new modules start with `from __future__ import annotations`** and use the existing logger convention `logging.getLogger("flowmeta.ai_pipeline.<module>")`.
- **Anthropic API usage:** model id `claude-opus-5`, via the official `anthropic` Python SDK (never raw httpx). No `temperature`/`top_p`/`top_k` (rejected with 400), no `budget_tokens`.
- **Progress reporting is required** (project CLAUDE.md): after each task report what changed, which files, what tests ran, what remains.

## File Structure

**New files**

| Path | Responsibility |
|---|---|
| `backend/app/services/ai_pipeline/types.py` | Frozen dataclasses shared by every stage: `Word`, `HotRegion`, `RegionTranscript`, `Transcript`, `ScoredSegment`. No logic beyond `to_dict`. |
| `backend/app/services/ai_pipeline/prefilter.py` | WAV reading (stdlib `wave` + numpy), frame RMS, silence map, hot-region detection. The tier-1 CPU saver. |
| `backend/app/services/ai_pipeline/crop.py` | 9:16 crop-window computation over a time range (OpenCV face track when available, centre otherwise) + smoothing. |
| `backend/app/services/ai_pipeline/renderer.py` | ffmpeg re-encode pass: crop → scale 1080×1920 → burn ASS. Filter-path escaping. |
| `backend/app/services/ai_pipeline/source.py` | Turns `(source_type, source_ref)` into a local file path (upload passthrough / yt-dlp download) + sha256. |
| `backend/assets/fonts/` | Vendored Be Vietnam Pro TTFs (binary, committed). |
| `backend/tests/test_ai_types.py`, `test_prefilter.py`, `test_asr_engine.py`, `test_llm_clients.py`, `test_scorer.py`, `test_cutter.py`, `test_crop.py`, `test_subtitle_gen.py`, `test_renderer.py`, `test_source.py` | One test module per stage. |

**Modified files**

| Path | Change |
|---|---|
| `backend/app/config.py` | ASR / scoring / font / binary / pipeline-version settings. |
| `backend/requirements.txt` | `numpy`, `faster-whisper`, `opencv-python-headless`, `yt-dlp`, `anthropic`. |
| `backend/Dockerfile` | `apt-get install ffmpeg`, copy `assets/`. |
| `backend/app/services/ai_pipeline/vad_filter.py` | Audio extraction only; add explicit duration probe. |
| `backend/app/services/ai_pipeline/asr_engine.py` | Region-scoped transcription, configurable model, per-region failure isolation. |
| `backend/app/services/ai_pipeline/llm_clients.py` | Backend registry, robust JSON extraction, timeouts, `LLMUnavailable`. |
| `backend/app/services/ai_pipeline/scorer.py` | Rubric prompt, region-index mapping, dedupe + topN, heuristic fallback. |
| `backend/app/services/ai_pipeline/cutter.py` | `-ss` before `-i`, keyframe ∩ silence snapping. |
| `backend/app/services/ai_pipeline/subtitle_gen.py` | ASS generation + clipspec v2. |
| `backend/app/services/clip_runner.py` | Full rewire: short sessions, per-clip isolation, cache, cleanup. |
| `backend/app/routers/clip_jobs.py` | Default `scoring_backend` from settings (fixes the `ollama` vs `gemini` mismatch). |
| `backend/tests/test_clip_runner.py` | Rewritten against fakes. |
| `backend/scripts/eval_pipeline.py` | Golden-set metrics harness. |

**Out of scope (deliberate):** OpenCut editor round-trip UI, frontend rendering, `ClipEdit` write paths, multi-worker scaling. The clipspec produced here is the contract those will consume later.

---

### Task 1: Dependencies, settings, and shared pipeline types

**Files:**
- Create: `backend/app/services/ai_pipeline/types.py`
- Create: `backend/tests/test_ai_types.py`
- Create: `backend/assets/fonts/.gitkeep`
- Modify: `backend/app/config.py:63-74`
- Modify: `backend/requirements.txt`
- Modify: `backend/Dockerfile`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `Word(start: float, end: float, text: str)` with `.to_dict() -> dict[str, Any]`
  - `HotRegion(index: int, start_sec: float, end_sec: float, energy: float)` with `.duration -> float`
  - `RegionTranscript(region: HotRegion, text: str, words: tuple[Word, ...])`
  - `Transcript(language: str, regions: tuple[RegionTranscript, ...])` with `.all_words -> tuple[Word, ...]`, `.total_text -> str`
  - `ScoredSegment(rank, score, region_index, start_sec, end_sec, hook_text, subtitle_text, words)` with `.duration -> float`
  - Settings: `ASR_BACKEND`, `ASR_WHISPER_MODEL`, `ASR_COMPUTE_TYPE`, `ASR_CPU_THREADS`, `SCORING_BACKEND`, `GEMINI_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `LLM_TIMEOUT_SECONDS`, `CLIP_FONT_DIR`, `CLIP_SUBTITLE_FONT`, `CLIP_PREFILTER_MAX_REGIONS`, `CLIP_PIPELINE_VERSION`, `FFMPEG_BIN`, `FFPROBE_BIN`, `YTDLP_BIN`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ai_types.py`:

```python
from __future__ import annotations

from app.config import settings
from app.services.ai_pipeline.types import (
    HotRegion,
    RegionTranscript,
    ScoredSegment,
    Transcript,
    Word,
)


def test_word_to_dict_uses_word_key():
    assert Word(1.0, 1.5, "xin").to_dict() == {"start": 1.0, "end": 1.5, "word": "xin"}


def test_hot_region_duration():
    assert HotRegion(index=0, start_sec=10.0, end_sec=40.0, energy=-18.0).duration == 30.0


def test_transcript_all_words_and_text_are_ordered():
    r0 = HotRegion(index=0, start_sec=0.0, end_sec=2.0, energy=-20.0)
    r1 = HotRegion(index=1, start_sec=10.0, end_sec=12.0, energy=-15.0)
    transcript = Transcript(
        language="en",
        regions=(
            RegionTranscript(region=r0, text="hello there", words=(Word(0.0, 0.5, "hello"), Word(0.6, 1.0, "there"))),
            RegionTranscript(region=r1, text="second bit", words=(Word(10.0, 10.4, "second"), Word(10.5, 11.0, "bit"))),
        ),
    )
    assert [w.text for w in transcript.all_words] == ["hello", "there", "second", "bit"]
    assert transcript.total_text == "hello there second bit"


def test_scored_segment_duration():
    seg = ScoredSegment(
        rank=1,
        score=91.0,
        region_index=1,
        start_sec=10.0,
        end_sec=45.0,
        hook_text="Đừng bỏ lỡ",
        subtitle_text="Xin chào các bạn",
        words=(),
    )
    assert seg.duration == 35.0


def test_new_settings_have_expected_defaults():
    assert settings.SCORING_BACKEND == "gemini"
    assert settings.ASR_BACKEND == "local"
    assert settings.ASR_WHISPER_MODEL == "medium"
    assert settings.ASR_COMPUTE_TYPE == "int8"
    assert settings.CLIP_SUBTITLE_FONT == "Be Vietnam Pro"
    assert settings.CLIP_PIPELINE_VERSION == "ai-v1"
    assert settings.FFMPEG_BIN == "ffmpeg"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ai_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai_pipeline.types'`

- [ ] **Step 3: Create the types module**

Create `backend/app/services/ai_pipeline/types.py`:

```python
"""Shared value types for the Flow Studio AI pipeline.

Every stage exchanges these frozen dataclasses instead of loose dicts so a
misspelled key fails at import/attribute time rather than deep in ffmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Word:
    """One ASR word with absolute (whole-source) timestamps in seconds."""

    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        # Key is "word" (not "text") to stay compatible with the clipspec the
        # frontend already reads.
        return {"start": self.start, "end": self.end, "word": self.text}


@dataclass(frozen=True)
class HotRegion:
    """A candidate span found by the tier-1 audio prefilter."""

    index: int
    start_sec: float
    end_sec: float
    energy: float  # mean dBFS over the region; higher = louder

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


@dataclass(frozen=True)
class RegionTranscript:
    region: HotRegion
    text: str
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Transcript:
    language: str
    regions: tuple[RegionTranscript, ...]

    @property
    def all_words(self) -> tuple[Word, ...]:
        return tuple(w for r in self.regions for w in r.words)

    @property
    def total_text(self) -> str:
        return " ".join(r.text for r in self.regions if r.text)


@dataclass(frozen=True)
class ScoredSegment:
    """A clip the scorer selected, with Vietnamese copy attached."""

    rank: int
    score: float
    region_index: int
    start_sec: float
    end_sec: float
    hook_text: str
    subtitle_text: str
    words: tuple[Word, ...]

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "score": self.score,
            "region_index": self.region_index,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "hook_text": self.hook_text,
            "subtitle_text": self.subtitle_text,
            "words": [w.to_dict() for w in self.words],
        }
```

- [ ] **Step 4: Add the settings**

In `backend/app/config.py`, replace the `# AI APIs` block (currently just `GEMINI_API_KEY`) with:

```python
    # AI APIs
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-5"
    LLM_TIMEOUT_SECONDS: float = 120.0
```

Then, immediately after the existing `FLOW_PORT: int = 8001` line inside the `# Flow Studio (clip module)` block, add:

```python
    # Flow Studio AI pipeline
    ASR_BACKEND: str = "local"          # local | cloud
    ASR_WHISPER_MODEL: str = "medium"   # faster-whisper model size or local path
    ASR_COMPUTE_TYPE: str = "int8"
    ASR_CPU_THREADS: int = 4
    SCORING_BACKEND: str = "gemini"     # gemini | ollama | claude | heuristic
    CLIP_PREFILTER_MAX_REGIONS: int = 30
    CLIP_PREFILTER_MIN_REGION_SEC: float = 20.0
    CLIP_PREFILTER_MAX_REGION_SEC: float = 90.0
    CLIP_FONT_DIR: str = "/app/assets/fonts"
    CLIP_SUBTITLE_FONT: str = "Be Vietnam Pro"
    CLIP_PIPELINE_VERSION: str = "ai-v1"
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"
    YTDLP_BIN: str = "yt-dlp"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ai_types.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Add runtime dependencies**

Append to `backend/requirements.txt`:

```
numpy==1.26.4
faster-whisper==1.0.3
opencv-python-headless==4.10.0.84
yt-dlp>=2024.12.13
anthropic>=0.69.0
```

Then install them locally: `cd backend && pip install -r requirements.txt`

- [ ] **Step 7: Add ffmpeg and fonts to the image**

Replace `backend/Dockerfile` with:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# ffmpeg/ffprobe for cut+render, fontconfig so libass can resolve font names,
# fonts-dejavu-core as the diacritic-safe fallback when Be Vietnam Pro is absent.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY assets ./assets

RUN fc-cache -f /app/assets/fonts || true

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

> If your current Dockerfile has extra `COPY` lines beyond `app`/`alembic`, keep them — only the `apt-get`, `COPY assets`, and `fc-cache` lines are new.

- [ ] **Step 8: Vendor the Vietnamese font**

Create the directory and placeholder so git tracks it:

```bash
mkdir -p backend/assets/fonts
printf '' > backend/assets/fonts/.gitkeep
```

Then download **Be Vietnam Pro** from Google Fonts (https://fonts.google.com/specimen/Be+Vietnam+Pro) and copy exactly these two files into `backend/assets/fonts/`:

- `BeVietnamPro-Regular.ttf`
- `BeVietnamPro-Bold.ttf`

Verify: `ls backend/assets/fonts/` shows both `.ttf` files.
If you cannot obtain them, leave the directory empty — Task 8 implements a DejaVu Sans fallback and its tests cover the empty-directory case.

- [ ] **Step 9: Run the full suite to confirm nothing regressed**

Run: `cd backend && python -m pytest -q`
Expected: existing tests pass; `tests/test_clip_runner.py` may already be failing from the earlier stub-era assertions — note it, it is rewritten in Task 9.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/ai_pipeline/types.py backend/tests/test_ai_types.py backend/app/config.py backend/requirements.txt backend/Dockerfile backend/assets
git commit -m "feat(flow-studio): add AI pipeline types, settings, and CPU runtime deps"
```

---

### Task 2: Tier-1 audio prefilter (hot regions + silence map)

**Files:**
- Create: `backend/app/services/ai_pipeline/prefilter.py`
- Create: `backend/tests/test_prefilter.py`
- Modify: `backend/app/services/ai_pipeline/vad_filter.py`

**Interfaces:**
- Consumes: `HotRegion` from Task 1.
- Produces:
  - `read_pcm16_mono(wav_path: str) -> tuple[np.ndarray, int]` — float32 samples in [-1, 1] and sample rate
  - `frame_db(samples: np.ndarray, sample_rate: int, frame_sec: float = 0.5) -> np.ndarray` — per-frame dBFS
  - `detect_silences(wav_path: str, *, threshold_db: float = -35.0, min_silence_sec: float = 0.3) -> list[tuple[float, float]]`
  - `detect_hot_regions(wav_path: str, *, min_region_sec: float, max_region_sec: float, max_regions: int) -> list[HotRegion]`
  - `probe_duration(media_path: str) -> float` (async, in `vad_filter.py`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prefilter.py`:

```python
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.ai_pipeline.prefilter import (
    detect_hot_regions,
    detect_silences,
    frame_db,
    read_pcm16_mono,
)

SAMPLE_RATE = 16000


def _write_wav(path: Path, segments: list[tuple[float, float]]) -> None:
    """segments = [(duration_sec, amplitude 0..1)] rendered as a 220 Hz tone."""
    chunks = []
    for duration, amplitude in segments:
        n = int(duration * SAMPLE_RATE)
        t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
        chunks.append((amplitude * np.sin(2 * math.pi * 220.0 * t)).astype(np.float32))
    samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


@pytest.fixture()
def loud_middle_wav(tmp_path: Path) -> str:
    # 10s quiet, 20s loud, 10s quiet
    path = tmp_path / "sample.wav"
    _write_wav(path, [(10.0, 0.002), (20.0, 0.8), (10.0, 0.002)])
    return str(path)


def test_read_pcm16_mono_returns_normalised_samples(loud_middle_wav: str):
    samples, sr = read_pcm16_mono(loud_middle_wav)
    assert sr == SAMPLE_RATE
    assert samples.dtype == np.float32
    assert len(samples) == 40 * SAMPLE_RATE
    assert float(np.max(np.abs(samples))) <= 1.0


def test_frame_db_is_louder_in_the_middle(loud_middle_wav: str):
    samples, sr = read_pcm16_mono(loud_middle_wav)
    db = frame_db(samples, sr, frame_sec=0.5)
    assert len(db) == 80
    assert db[30] > db[5] + 20.0  # middle is far louder than the quiet head


def test_detect_silences_finds_head_and_tail(loud_middle_wav: str):
    silences = detect_silences(loud_middle_wav, threshold_db=-35.0, min_silence_sec=1.0)
    assert len(silences) == 2
    head, tail = silences
    assert head[0] == pytest.approx(0.0, abs=0.6)
    assert head[1] == pytest.approx(10.0, abs=0.6)
    assert tail[0] == pytest.approx(30.0, abs=0.6)


def test_detect_hot_regions_covers_the_loud_span(loud_middle_wav: str):
    regions = detect_hot_regions(
        loud_middle_wav, min_region_sec=5.0, max_region_sec=30.0, max_regions=5
    )
    assert len(regions) == 1
    region = regions[0]
    assert region.index == 0
    assert region.start_sec <= 11.0
    assert region.end_sec >= 29.0
    assert region.duration <= 30.0


def test_detect_hot_regions_respects_max_regions(tmp_path: Path):
    path = tmp_path / "many.wav"
    segments: list[tuple[float, float]] = []
    for _ in range(6):
        segments.append((4.0, 0.9))
        segments.append((4.0, 0.002))
    _write_wav(path, segments)
    regions = detect_hot_regions(
        str(path), min_region_sec=3.0, max_region_sec=10.0, max_regions=2
    )
    assert len(regions) == 2
    assert [r.index for r in regions] == [0, 1]
    assert regions[0].start_sec < regions[1].start_sec


def test_detect_hot_regions_on_silent_audio_returns_empty(tmp_path: Path):
    path = tmp_path / "silent.wav"
    _write_wav(path, [(20.0, 0.0)])
    assert detect_hot_regions(str(path), min_region_sec=5.0, max_region_sec=30.0, max_regions=5) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_prefilter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai_pipeline.prefilter'`

- [ ] **Step 3: Implement the prefilter**

Create `backend/app/services/ai_pipeline/prefilter.py`:

```python
"""Tier-1 audio prefilter.

Whisper on a 2-hour source is the single most expensive CPU step in the
pipeline. This module narrows the source down to a handful of "hot" regions
using cheap signal statistics (frame energy) so ASR only runs where something
interesting is actually happening. It also produces the silence map that the
cutter uses to avoid cutting mid-word.

Deliberately numpy-only: no librosa, no torch, no model download.
"""
from __future__ import annotations

import logging
import wave

import numpy as np

from app.services.ai_pipeline.types import HotRegion

logger = logging.getLogger("flowmeta.ai_pipeline.prefilter")

_EPS = 1e-10
_DEFAULT_FRAME_SEC = 0.5


def read_pcm16_mono(wav_path: str) -> tuple[np.ndarray, int]:
    """Read a 16-bit PCM WAV into float32 samples in [-1, 1], downmixed to mono."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM, got {wf.getsampwidth() * 8}-bit: {wav_path}")
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        usable = (len(samples) // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(samples), sample_rate


def frame_db(
    samples: np.ndarray, sample_rate: int, frame_sec: float = _DEFAULT_FRAME_SEC
) -> np.ndarray:
    """Per-frame RMS expressed in dBFS. Frames are non-overlapping."""
    frame_len = max(1, int(sample_rate * frame_sec))
    usable = (len(samples) // frame_len) * frame_len
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[:usable].reshape(-1, frame_len)
    rms = np.sqrt(np.mean(np.square(frames), axis=1) + _EPS)
    return (20.0 * np.log10(rms + _EPS)).astype(np.float32)


def detect_silences(
    wav_path: str,
    *,
    threshold_db: float = -35.0,
    min_silence_sec: float = 0.3,
    frame_sec: float = 0.1,
) -> list[tuple[float, float]]:
    """Return [(start_sec, end_sec)] spans quieter than `threshold_db`."""
    samples, sample_rate = read_pcm16_mono(wav_path)
    db = frame_db(samples, sample_rate, frame_sec=frame_sec)
    quiet = db < threshold_db

    spans: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, is_quiet in enumerate(quiet):
        if is_quiet and run_start is None:
            run_start = i
        elif not is_quiet and run_start is not None:
            spans.append((run_start, i))
            run_start = None
    if run_start is not None:
        spans.append((run_start, len(quiet)))

    out: list[tuple[float, float]] = []
    for start_idx, end_idx in spans:
        start = start_idx * frame_sec
        end = end_idx * frame_sec
        if end - start >= min_silence_sec:
            out.append((round(start, 3), round(end, 3)))
    return out


def _merge(spans: list[list[float]], gap_sec: float) -> list[list[float]]:
    merged: list[list[float]] = []
    for span in sorted(spans, key=lambda s: s[0]):
        if merged and span[0] - merged[-1][1] <= gap_sec:
            merged[-1][1] = max(merged[-1][1], span[1])
        else:
            merged.append([span[0], span[1]])
    return merged


def detect_hot_regions(
    wav_path: str,
    *,
    min_region_sec: float,
    max_region_sec: float,
    max_regions: int,
    frame_sec: float = _DEFAULT_FRAME_SEC,
) -> list[HotRegion]:
    """Find the loudest, most dynamic spans of the audio.

    Frames above the 70th percentile of *speech* energy are marked hot,
    contiguous runs are merged (bridging gaps up to 2s), each run is padded
    out to `min_region_sec` and truncated to `max_region_sec` around its
    loudest frame, and the top `max_regions` by mean energy are returned in
    chronological order with fresh indices.
    """
    samples, sample_rate = read_pcm16_mono(wav_path)
    db = frame_db(samples, sample_rate, frame_sec=frame_sec)
    if len(db) == 0:
        return []

    total_sec = len(db) * frame_sec
    floor_db = -55.0
    speech = db[db > floor_db]
    if speech.size == 0:
        logger.info("prefilter: no frame above %.0f dBFS in %s", floor_db, wav_path)
        return []

    threshold = float(np.percentile(speech, 70.0))
    hot = db >= threshold

    runs: list[list[float]] = []
    run_start: int | None = None
    for i, is_hot in enumerate(hot):
        if is_hot and run_start is None:
            run_start = i
        elif not is_hot and run_start is not None:
            runs.append([run_start * frame_sec, i * frame_sec])
            run_start = None
    if run_start is not None:
        runs.append([run_start * frame_sec, len(hot) * frame_sec])
    if not runs:
        return []

    runs = _merge(runs, gap_sec=2.0)

    candidates: list[tuple[float, float, float]] = []  # (start, end, energy)
    for start, end in runs:
        if end - start < min_region_sec:
            pad = (min_region_sec - (end - start)) / 2.0
            start = max(0.0, start - pad)
            end = min(total_sec, start + min_region_sec)
            start = max(0.0, end - min_region_sec)
        if end - start > max_region_sec:
            lo = int(start / frame_sec)
            hi = min(len(db), int(end / frame_sec))
            peak = lo + int(np.argmax(db[lo:hi]))
            centre = peak * frame_sec
            start = max(0.0, centre - max_region_sec / 2.0)
            end = min(total_sec, start + max_region_sec)
            start = max(0.0, end - max_region_sec)
        lo = int(start / frame_sec)
        hi = max(lo + 1, int(end / frame_sec))
        candidates.append((round(start, 3), round(end, 3), float(np.mean(db[lo:hi]))))

    merged_final = _merge([[c[0], c[1]] for c in candidates], gap_sec=0.0)
    scored: list[tuple[float, float, float]] = []
    for start, end in merged_final:
        lo = int(start / frame_sec)
        hi = max(lo + 1, int(end / frame_sec))
        scored.append((start, end, float(np.mean(db[lo:hi]))))

    scored.sort(key=lambda c: c[2], reverse=True)
    kept = scored[:max_regions]
    kept.sort(key=lambda c: c[0])

    regions = [
        HotRegion(index=i, start_sec=start, end_sec=end, energy=round(energy, 2))
        for i, (start, end, energy) in enumerate(kept)
    ]
    logger.info(
        "prefilter: %s -> %d region(s), %.1fs of %.1fs (%.0f%%)",
        wav_path,
        len(regions),
        sum(r.duration for r in regions),
        total_sec,
        100.0 * sum(r.duration for r in regions) / max(total_sec, 1.0),
    )
    return regions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_prefilter.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Add a duration probe to the audio extractor**

In `backend/app/services/ai_pipeline/vad_filter.py`, replace the whole file with:

```python
"""Audio extraction for the AI pipeline.

Real VAD is *not* done here. faster-whisper runs Silero VAD internally
(`vad_filter=True`), and the coarse region selection lives in
`prefilter.detect_hot_regions`. This module only owns ffmpeg audio extraction
and duration probing.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.vad")


async def extract_audio(video_path: str, output_audio_path: str) -> bool:
    """Extract 16 kHz mono 16-bit PCM WAV — the format every later stage assumes."""
    Path(output_audio_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_BIN, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_audio_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error("ffmpeg audio extraction failed: %s", stderr.decode(errors="replace")[-2000:])
        return False
    return True


async def probe_duration(media_path: str) -> float:
    """Return media duration in seconds, or 0.0 when ffprobe cannot tell."""
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        media_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return 0.0
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
```

- [ ] **Step 6: Run the pipeline tests again**

Run: `cd backend && python -m pytest tests/test_prefilter.py tests/test_ai_types.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai_pipeline/prefilter.py backend/app/services/ai_pipeline/vad_filter.py backend/tests/test_prefilter.py
git commit -m "feat(flow-studio): add tier-1 audio prefilter and duration probe"
```

---

### Task 3: Region-scoped ASR with per-region failure isolation

**Files:**
- Modify: `backend/app/services/ai_pipeline/asr_engine.py`
- Create: `backend/tests/test_asr_engine.py`

**Interfaces:**
- Consumes: `read_pcm16_mono` (Task 2), `HotRegion`/`Transcript`/`RegionTranscript`/`Word` (Task 1), `settings.ASR_*`.
- Produces:
  - `transcribe_regions(audio_path: str, regions: Sequence[HotRegion], *, language: str | None = None) -> Transcript` (async)
  - `slice_samples(samples: np.ndarray, sample_rate: int, region: HotRegion) -> np.ndarray`
  - `reset_model_cache() -> None` (test hook)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_asr_engine.py`:

```python
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.ai_pipeline import asr_engine
from app.services.ai_pipeline.types import HotRegion

SAMPLE_RATE = 16000


@pytest.fixture()
def wav_path(tmp_path: Path) -> str:
    path = tmp_path / "audio.wav"
    n = 60 * SAMPLE_RATE
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    pcm = (0.5 * np.sin(2 * math.pi * 220.0 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return str(path)


class FakeSegment:
    def __init__(self, text, words):
        self.text = text
        self.words = words


class FakeWord:
    def __init__(self, start, end, word):
        self.start = start
        self.end = end
        self.word = word


class FakeInfo:
    language = "en"
    language_probability = 0.98


class FakeModel:
    """Returns one segment whose word timings are region-relative."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        segments = [
            FakeSegment(" hello world", [FakeWord(0.0, 0.4, " hello"), FakeWord(0.5, 1.0, " world")])
        ]
        return iter(segments), FakeInfo()


class ExplodingModel(FakeModel):
    def transcribe(self, audio, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("ctranslate2 blew up")
        return super().transcribe(audio, **kwargs)


def test_slice_samples_extracts_the_region(wav_path: str):
    from app.services.ai_pipeline.prefilter import read_pcm16_mono

    samples, sr = read_pcm16_mono(wav_path)
    region = HotRegion(index=0, start_sec=10.0, end_sec=20.0, energy=-12.0)
    sliced = asr_engine.slice_samples(samples, sr, region)
    assert len(sliced) == 10 * SAMPLE_RATE


async def test_transcribe_regions_offsets_word_timestamps(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=30.0, end_sec=35.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(wav_path, regions)

    assert model.calls == 2
    assert transcript.language == "en"
    assert len(transcript.regions) == 2
    assert transcript.regions[0].text == "hello world"
    # Region 1 starts at 30s, so its words must be shifted by 30s.
    assert transcript.regions[1].words[0].start == pytest.approx(30.0)
    assert transcript.regions[1].words[1].end == pytest.approx(31.0)


async def test_transcribe_regions_skips_a_failing_region(monkeypatch, wav_path: str):
    model = ExplodingModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)

    regions = [
        HotRegion(index=0, start_sec=0.0, end_sec=5.0, energy=-10.0),
        HotRegion(index=1, start_sec=10.0, end_sec=15.0, energy=-11.0),
    ]
    transcript = await asr_engine.transcribe_regions(wav_path, regions)

    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.index == 1


async def test_transcribe_regions_with_no_regions_uses_whole_file(monkeypatch, wav_path: str):
    model = FakeModel()
    monkeypatch.setattr(asr_engine, "_get_model", lambda: model)

    transcript = await asr_engine.transcribe_regions(wav_path, [])

    assert model.calls == 1
    assert len(transcript.regions) == 1
    assert transcript.regions[0].region.start_sec == 0.0
    assert transcript.regions[0].region.end_sec == pytest.approx(60.0, abs=0.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_asr_engine.py -v`
Expected: FAIL — `AttributeError: module 'app.services.ai_pipeline.asr_engine' has no attribute 'slice_samples'`

- [ ] **Step 3: Rewrite the ASR engine**

Replace `backend/app/services/ai_pipeline/asr_engine.py` with:

```python
"""Region-scoped CPU ASR (faster-whisper / CTranslate2, int8).

Only the hot regions found by the prefilter are transcribed, and each region is
transcribed independently so one bad slice cannot fail the whole job. Word
timestamps come back region-relative and are shifted to absolute source time
before leaving this module — every downstream stage assumes absolute seconds.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import numpy as np

from app.config import settings
from app.services.ai_pipeline.prefilter import read_pcm16_mono
from app.services.ai_pipeline.types import HotRegion, RegionTranscript, Transcript, Word

logger = logging.getLogger("flowmeta.ai_pipeline.asr")

_MODEL = None


def _get_model():
    """Lazily construct the shared WhisperModel. Import is deferred so importing
    this module (in tests, in the router) does not pull in CTranslate2."""
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        logger.info(
            "loading whisper model=%s compute_type=%s threads=%d",
            settings.ASR_WHISPER_MODEL,
            settings.ASR_COMPUTE_TYPE,
            settings.ASR_CPU_THREADS,
        )
        _MODEL = WhisperModel(
            settings.ASR_WHISPER_MODEL,
            device="cpu",
            compute_type=settings.ASR_COMPUTE_TYPE,
            cpu_threads=settings.ASR_CPU_THREADS,
        )
    return _MODEL


def reset_model_cache() -> None:
    """Drop the cached model (used by tests and by long-lived worker restarts)."""
    global _MODEL
    _MODEL = None


def slice_samples(samples: np.ndarray, sample_rate: int, region: HotRegion) -> np.ndarray:
    lo = max(0, int(region.start_sec * sample_rate))
    hi = min(len(samples), int(region.end_sec * sample_rate))
    return np.ascontiguousarray(samples[lo:hi])


def _transcribe_slice(audio: np.ndarray, language: str | None) -> tuple[str, list[Word], str]:
    model = _get_model()
    segments, info = model.transcribe(
        audio,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
        language=language,
    )
    words: list[Word] = []
    texts: list[str] = []
    for segment in segments:
        texts.append(segment.text.strip())
        for w in getattr(segment, "words", None) or []:
            token = (w.word or "").strip()
            if token:
                words.append(Word(start=float(w.start), end=float(w.end), text=token))
    detected = getattr(info, "language", None) or language or "unknown"
    return " ".join(t for t in texts if t).strip(), words, detected


async def transcribe_regions(
    audio_path: str,
    regions: Sequence[HotRegion],
    *,
    language: str | None = None,
) -> Transcript:
    """Transcribe each hot region. When `regions` is empty the whole file is
    treated as a single region (prefilter found nothing — better slow than empty)."""
    loop = asyncio.get_running_loop()
    samples, sample_rate = await loop.run_in_executor(None, read_pcm16_mono, audio_path)
    total_sec = len(samples) / float(sample_rate)

    targets = list(regions)
    if not targets:
        logger.warning("no hot regions for %s; transcribing full %.1fs", audio_path, total_sec)
        targets = [HotRegion(index=0, start_sec=0.0, end_sec=total_sec, energy=0.0)]

    detected_language = language or "unknown"
    out: list[RegionTranscript] = []
    for region in targets:
        audio = slice_samples(samples, sample_rate, region)
        if audio.size == 0:
            logger.warning("region %d is empty, skipping", region.index)
            continue
        try:
            text, words, region_language = await loop.run_in_executor(
                None, _transcribe_slice, audio, language
            )
        except Exception:
            logger.exception("ASR failed on region %d (%.1fs-%.1fs); skipping",
                             region.index, region.start_sec, region.end_sec)
            continue

        if detected_language == "unknown":
            detected_language = region_language
        shifted = tuple(
            Word(
                start=round(w.start + region.start_sec, 3),
                end=round(w.end + region.start_sec, 3),
                text=w.text,
            )
            for w in words
        )
        if not text and not shifted:
            continue
        out.append(RegionTranscript(region=region, text=text, words=shifted))

    logger.info("ASR produced %d/%d usable regions (language=%s)",
                len(out), len(targets), detected_language)
    return Transcript(language=detected_language, regions=tuple(out))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_asr_engine.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_pipeline/asr_engine.py backend/tests/test_asr_engine.py
git commit -m "feat(flow-studio): region-scoped whisper ASR with per-region isolation"
```

---

### Task 4: LLM client hardening (gemini / ollama / claude + JSON extraction)

**Files:**
- Modify: `backend/app/services/ai_pipeline/llm_clients.py`
- Create: `backend/tests/test_llm_clients.py`

**Interfaces:**
- Consumes: `settings.GEMINI_*`, `settings.OLLAMA_*`, `settings.ANTHROPIC_*`, `settings.LLM_TIMEOUT_SECONDS`.
- Produces:
  - `class LLMUnavailable(RuntimeError)`
  - `extract_json(text: str) -> Any`
  - `call_gemini(prompt: str) -> str` (async), `call_ollama(prompt: str) -> str` (async), `call_claude(prompt: str) -> str` (async)
  - `query_llm(prompt: str, *, backend: str) -> Any` (async) — returns parsed JSON, raises `LLMUnavailable`
  - `SUPPORTED_BACKENDS: frozenset[str]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_clients.py`:

```python
from __future__ import annotations

import json

import httpx
import pytest

from app.config import settings
from app.services.ai_pipeline import llm_clients
from app.services.ai_pipeline.llm_clients import LLMUnavailable, extract_json, query_llm


def test_extract_json_plain_array():
    assert extract_json('[{"a": 1}]') == [{"a": 1}]


def test_extract_json_strips_markdown_fence():
    raw = 'Sure, here you go:\n```json\n[{"rank": 1, "score": 90}]\n```\nHope that helps!'
    assert extract_json(raw) == [{"rank": 1, "score": 90}]


def test_extract_json_finds_embedded_object():
    assert extract_json('noise {"ok": true} trailing') == {"ok": True}


def test_extract_json_raises_on_garbage():
    with pytest.raises(LLMUnavailable):
        extract_json("no json at all")


async def test_query_llm_rejects_unknown_backend():
    with pytest.raises(LLMUnavailable) as exc:
        await query_llm("prompt", backend="nope")
    assert "nope" in str(exc.value)


async def test_query_llm_gemini_parses_response(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps([{"region_index": 0, "score": 88}])}]}}
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "generativelanguage.googleapis.com" in str(request.url)
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    assert await query_llm("prompt", backend="gemini") == [{"region_index": 0, "score": 88}]


async def test_query_llm_gemini_without_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(LLMUnavailable):
        await query_llm("prompt", backend="gemini")


async def test_query_llm_wraps_transport_errors(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    with pytest.raises(LLMUnavailable):
        await query_llm("prompt", backend="gemini")


async def test_query_llm_ollama_parses_response(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama.test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://ollama.test/api/generate"
        return httpx.Response(200, json={"response": '{"ok": 1}'})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    assert await query_llm("prompt", backend="ollama") == {"ok": 1}


async def test_query_llm_claude_without_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(LLMUnavailable):
        await query_llm("prompt", backend="claude")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_clients.py -v`
Expected: FAIL — `ImportError: cannot import name 'LLMUnavailable'`

- [ ] **Step 3: Rewrite the LLM clients**

Replace `backend/app/services/ai_pipeline/llm_clients.py` with:

```python
"""LLM backends for clip scoring.

Every backend returns raw text; `query_llm` is the only public entry point and
always returns parsed JSON or raises `LLMUnavailable`. Callers (the scorer)
catch that one exception and fall back to the heuristic tier.

Gemini and Ollama are plain HTTP services (httpx). Claude goes through the
official `anthropic` SDK — never raw HTTP.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.llm")

SUPPORTED_BACKENDS = frozenset({"gemini", "ollama", "claude"})

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMUnavailable(RuntimeError):
    """The chosen backend could not produce usable JSON."""


def _build_client() -> httpx.AsyncClient:
    """Seam so tests can inject an httpx.MockTransport."""
    return httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS)


def extract_json(text: str) -> Any:
    """Pull the first complete JSON value out of an LLM response.

    Handles bare JSON, ```json fences, and JSON surrounded by prose.
    """
    if not text or not text.strip():
        raise LLMUnavailable("empty LLM response")

    candidate = text.strip()
    if "```" in candidate:
        chunks = candidate.split("```")
        for chunk in chunks[1:]:
            body = chunk
            if body.lower().startswith("json"):
                body = body[4:]
            body = body.strip()
            if body.startswith("[") or body.startswith("{"):
                candidate = body
                break

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    open_idx = min(
        (i for i in (candidate.find("["), candidate.find("{")) if i != -1),
        default=-1,
    )
    if open_idx == -1:
        raise LLMUnavailable(f"no JSON found in LLM response: {text[:200]!r}")

    opener = candidate[open_idx]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for i in range(open_idx, len(candidate)):
        ch = candidate[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[open_idx : i + 1])
                except json.JSONDecodeError as exc:
                    raise LLMUnavailable(f"malformed JSON in LLM response: {exc}") from exc
    raise LLMUnavailable(f"unterminated JSON in LLM response: {text[:200]!r}")


async def call_gemini(prompt: str) -> str:
    if not settings.GEMINI_API_KEY:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    url = _GEMINI_URL.format(model=settings.GEMINI_MODEL)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    async with _build_client() as client:
        try:
            response = await client.post(
                url, params={"key": settings.GEMINI_API_KEY}, json=payload
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"gemini request failed: {exc}") from exc
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f"unexpected gemini payload: {str(data)[:200]}") from exc


async def call_ollama(prompt: str) -> str:
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    async with _build_client() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"ollama request failed: {exc}") from exc
    text = data.get("response")
    if not text:
        raise LLMUnavailable(f"unexpected ollama payload: {str(data)[:200]}")
    return text


async def call_claude(prompt: str) -> str:
    if not settings.ANTHROPIC_API_KEY:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise LLMUnavailable("anthropic SDK is not installed") from exc

    client = AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS
    )
    try:
        message = await client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=8000,
            system="You return only JSON. No prose, no markdown fences.",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise LLMUnavailable(f"claude request failed: {exc}") from exc

    if getattr(message, "stop_reason", None) == "refusal":
        raise LLMUnavailable("claude declined the request")
    parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    if not parts:
        raise LLMUnavailable("claude returned no text content")
    return "".join(parts)


async def query_llm(prompt: str, *, backend: str) -> Any:
    """Call `backend` and return parsed JSON. Raises `LLMUnavailable` on any failure."""
    normalised = (backend or "").strip().lower()
    if normalised not in SUPPORTED_BACKENDS:
        raise LLMUnavailable(f"unsupported scoring backend: {backend!r}")

    caller = {"gemini": call_gemini, "ollama": call_ollama, "claude": call_claude}[normalised]
    logger.info("querying LLM backend=%s prompt_chars=%d", normalised, len(prompt))
    text = await caller(prompt)
    return extract_json(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_llm_clients.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_pipeline/llm_clients.py backend/tests/test_llm_clients.py
git commit -m "feat(flow-studio): harden LLM clients with JSON extraction and typed failures"
```

---

### Task 5: Scorer — rubric prompt, region mapping, dedupe, heuristic fallback

**Files:**
- Modify: `backend/app/services/ai_pipeline/scorer.py`
- Create: `backend/tests/test_scorer.py`

**Interfaces:**
- Consumes: `Transcript`/`RegionTranscript`/`ScoredSegment`/`Word` (Task 1), `query_llm`/`LLMUnavailable` (Task 4).
- Produces:
  - `build_prompt(transcript: Transcript, *, top_n: int, min_sec: float, max_sec: float) -> str`
  - `clamp_to_words(words, start, end, *, min_sec, max_sec, region) -> tuple[float, float, tuple[Word, ...]]`
  - `overlap_ratio(a: ScoredSegment, b: ScoredSegment) -> float`
  - `dedupe_and_rank(candidates: list[ScoredSegment], top_n: int) -> list[ScoredSegment]`
  - `heuristic_select(transcript, *, top_n, min_sec, max_sec) -> list[ScoredSegment]`
  - `select_clips(transcript, *, top_n, min_sec, max_sec, backend) -> list[ScoredSegment]` (async)

> The old `score_and_translate_clips` is removed. Task 9 updates the runner and Task 10 updates the eval script; nothing else imports it.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scorer.py`:

```python
from __future__ import annotations

import pytest

from app.services.ai_pipeline import scorer
from app.services.ai_pipeline.llm_clients import LLMUnavailable
from app.services.ai_pipeline.types import HotRegion, RegionTranscript, ScoredSegment, Transcript, Word


def _region_transcript(index: int, start: float, n_words: int = 120) -> RegionTranscript:
    region = HotRegion(index=index, start_sec=start, end_sec=start + n_words * 0.5, energy=-12.0)
    words = tuple(
        Word(start=start + i * 0.5, end=start + i * 0.5 + 0.4, text=f"w{index}_{i}")
        for i in range(n_words)
    )
    return RegionTranscript(region=region, text=" ".join(w.text for w in words), words=words)


@pytest.fixture()
def transcript() -> Transcript:
    return Transcript(language="en", regions=(_region_transcript(0, 0.0), _region_transcript(1, 300.0)))


def test_build_prompt_lists_regions_and_demands_vietnamese(transcript: Transcript):
    prompt = scorer.build_prompt(transcript, top_n=3, min_sec=30, max_sec=60)
    assert "region_index" in prompt
    assert "[REGION 0]" in prompt and "[REGION 1]" in prompt
    assert "Vietnamese" in prompt
    assert "30" in prompt and "60" in prompt


def test_clamp_to_words_snaps_to_word_boundaries(transcript: Transcript):
    region_transcript = transcript.regions[0]
    start, end, words = scorer.clamp_to_words(
        region_transcript.words, 10.3, 41.9, min_sec=30, max_sec=60,
        region=region_transcript.region,
    )
    assert start == pytest.approx(10.0)          # snapped down to a word start
    assert end == pytest.approx(41.9, abs=0.6)   # snapped to the last word end <= 41.9
    assert 30.0 <= end - start <= 60.0
    assert words[0].start >= start and words[-1].end <= end


def test_clamp_to_words_extends_a_too_short_window(transcript: Transcript):
    rt = transcript.regions[0]
    start, end, _ = scorer.clamp_to_words(
        rt.words, 5.0, 12.0, min_sec=30, max_sec=60, region=rt.region
    )
    assert end - start >= 30.0


def test_overlap_ratio_and_dedupe_drops_the_lower_score():
    a = ScoredSegment(0, 90.0, 0, 10.0, 50.0, "hook a", "vi a", ())
    b = ScoredSegment(0, 70.0, 0, 20.0, 60.0, "hook b", "vi b", ())  # 30/40 = 75% overlap
    c = ScoredSegment(0, 80.0, 1, 300.0, 340.0, "hook c", "vi c", ())

    assert scorer.overlap_ratio(a, b) == pytest.approx(0.75)
    ranked = scorer.dedupe_and_rank([a, b, c], top_n=5)
    assert [seg.score for seg in ranked] == [90.0, 80.0]
    assert [seg.rank for seg in ranked] == [1, 2]


def test_dedupe_and_rank_respects_top_n():
    segs = [
        ScoredSegment(0, float(90 - i), 0, i * 100.0, i * 100.0 + 40.0, "h", "v", ())
        for i in range(5)
    ]
    assert len(scorer.dedupe_and_rank(segs, top_n=2)) == 2


async def test_select_clips_maps_llm_output_back_to_timestamps(monkeypatch, transcript: Transcript):
    async def fake_query_llm(prompt, *, backend):
        assert backend == "gemini"
        return [
            {
                "region_index": 1,
                "score": 93,
                "hook_text": "Bạn sẽ bất ngờ",
                "subtitle_text": "Đây là nội dung tiếng Việt.",
                "start_sec": 310.0,
                "end_sec": 350.0,
            }
        ]

    monkeypatch.setattr(scorer, "query_llm", fake_query_llm)
    clips = await scorer.select_clips(transcript, top_n=3, min_sec=30, max_sec=60, backend="gemini")

    assert len(clips) == 1
    clip = clips[0]
    assert clip.rank == 1
    assert clip.region_index == 1
    assert 300.0 <= clip.start_sec < clip.end_sec <= 360.0
    assert 30.0 <= clip.duration <= 60.0
    assert clip.subtitle_text == "Đây là nội dung tiếng Việt."
    assert clip.words and clip.words[0].start >= clip.start_sec


async def test_select_clips_ignores_unknown_region_index(monkeypatch, transcript: Transcript):
    async def fake_query_llm(prompt, *, backend):
        return [
            {"region_index": 99, "score": 99, "hook_text": "x", "subtitle_text": "y",
             "start_sec": 0.0, "end_sec": 40.0},
            {"region_index": 0, "score": 80, "hook_text": "ok", "subtitle_text": "vi",
             "start_sec": 0.0, "end_sec": 40.0},
        ]

    monkeypatch.setattr(scorer, "query_llm", fake_query_llm)
    clips = await scorer.select_clips(transcript, top_n=3, min_sec=30, max_sec=60, backend="gemini")
    assert [c.region_index for c in clips] == [0]


async def test_select_clips_falls_back_to_heuristic(monkeypatch, transcript: Transcript):
    async def failing_query_llm(prompt, *, backend):
        raise LLMUnavailable("no key")

    monkeypatch.setattr(scorer, "query_llm", failing_query_llm)
    clips = await scorer.select_clips(transcript, top_n=2, min_sec=30, max_sec=60, backend="gemini")

    assert len(clips) == 2
    assert all(30.0 <= c.duration <= 60.0 for c in clips)
    assert all(c.subtitle_text for c in clips)


async def test_select_clips_heuristic_backend_skips_llm(monkeypatch, transcript: Transcript):
    async def boom(prompt, *, backend):
        raise AssertionError("LLM must not be called for backend=heuristic")

    monkeypatch.setattr(scorer, "query_llm", boom)
    clips = await scorer.select_clips(transcript, top_n=1, min_sec=30, max_sec=60, backend="heuristic")
    assert len(clips) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_scorer.py -v`
Expected: FAIL — `AttributeError: module 'app.services.ai_pipeline.scorer' has no attribute 'build_prompt'`

- [ ] **Step 3: Rewrite the scorer**

Replace `backend/app/services/ai_pipeline/scorer.py` with:

```python
"""Clip selection: rubric scoring + Vietnamese translation.

The LLM never sees raw timestamps to echo back verbatim. It is given numbered
regions and returns `region_index` plus a rough start/end; this module snaps
those to real word boundaries inside that region. That removes the fragile
"find the snippet's first word anywhere in the transcript" mapping the v0 code
used, which could silently match a repeated word in a different part of the video.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.ai_pipeline.llm_clients import LLMUnavailable, query_llm
from app.services.ai_pipeline.types import HotRegion, ScoredSegment, Transcript, Word

logger = logging.getLogger("flowmeta.ai_pipeline.scorer")

OVERLAP_DROP_RATIO = 0.5

_RUBRIC = """You are a short-form video editor. Score candidate segments of a longer video.

Rubric (0-100, weighted):
- Hook strength in the first 3 seconds (30)
- Self-contained: understandable without the rest of the video (25)
- Emotional intensity or surprise (20)
- Clear payoff or conclusion inside the segment (15)
- Quotability / shareability (10)

Rules:
- Pick at most {top_n} segments, each from a DIFFERENT region when possible.
- Each segment must last between {min_sec} and {max_sec} seconds.
- start_sec and end_sec are ABSOLUTE seconds and must fall inside the region you name.
- The source audio may be in ANY language. `hook_text` and `subtitle_text` MUST be
  natural, idiomatic Vietnamese - translate, do not transliterate, and do not copy
  the source language.
- `hook_text`: at most 8 Vietnamese words, an on-screen title.
- `subtitle_text`: the full Vietnamese spoken content of the segment, punctuated.

Return ONLY a JSON array, no prose, no markdown fences. Each item:
{{"region_index": int, "score": number, "hook_text": string, "subtitle_text": string,
  "start_sec": number, "end_sec": number}}
"""


def build_prompt(transcript: Transcript, *, top_n: int, min_sec: float, max_sec: float) -> str:
    header = _RUBRIC.format(top_n=top_n, min_sec=int(min_sec), max_sec=int(max_sec))
    blocks = []
    for rt in transcript.regions:
        blocks.append(
            f"[REGION {rt.region.index}] {rt.region.start_sec:.1f}s - {rt.region.end_sec:.1f}s\n{rt.text}"
        )
    return f"{header}\nSource language: {transcript.language}\n\n" + "\n\n".join(blocks)


def clamp_to_words(
    words: tuple[Word, ...],
    start: float,
    end: float,
    *,
    min_sec: float,
    max_sec: float,
    region: HotRegion,
) -> tuple[float, float, tuple[Word, ...]]:
    """Snap [start, end] to word boundaries inside `region` and enforce the length band."""
    start = max(region.start_sec, min(float(start), region.end_sec))
    end = max(region.start_sec, min(float(end), region.end_sec))
    if end <= start:
        end = min(region.end_sec, start + min_sec)

    if end - start < min_sec:
        end = min(region.end_sec, start + min_sec)
        start = max(region.start_sec, end - min_sec)
    if end - start > max_sec:
        end = start + max_sec

    if words:
        starts = [w.start for w in words if w.start <= start]
        start = max(starts) if starts else words[0].start
        ends = [w.end for w in words if w.end <= end]
        end = max(ends) if ends else min(region.end_sec, start + min_sec)
        if end - start < min_sec:
            later = [w.end for w in words if w.end >= start + min_sec]
            end = later[0] if later else min(region.end_sec, start + min_sec)
        if end - start > max_sec:
            capped = [w.end for w in words if start < w.end <= start + max_sec]
            end = capped[-1] if capped else start + max_sec

    selected = tuple(w for w in words if w.start >= start - 1e-6 and w.end <= end + 1e-6)
    return round(start, 3), round(end, 3), selected


def overlap_ratio(a: ScoredSegment, b: ScoredSegment) -> float:
    """Intersection over the *shorter* segment. 1.0 means fully contained."""
    intersection = min(a.end_sec, b.end_sec) - max(a.start_sec, b.start_sec)
    if intersection <= 0:
        return 0.0
    shortest = min(a.duration, b.duration)
    return intersection / shortest if shortest > 0 else 0.0


def dedupe_and_rank(candidates: list[ScoredSegment], top_n: int) -> list[ScoredSegment]:
    """Highest score wins; anything overlapping a kept segment by >50% is dropped."""
    kept: list[ScoredSegment] = []
    for candidate in sorted(candidates, key=lambda s: s.score, reverse=True):
        if any(overlap_ratio(candidate, k) > OVERLAP_DROP_RATIO for k in kept):
            continue
        kept.append(candidate)
        if len(kept) >= top_n:
            break
    return [
        ScoredSegment(
            rank=i + 1,
            score=seg.score,
            region_index=seg.region_index,
            start_sec=seg.start_sec,
            end_sec=seg.end_sec,
            hook_text=seg.hook_text,
            subtitle_text=seg.subtitle_text,
            words=seg.words,
        )
        for i, seg in enumerate(kept)
    ]


def heuristic_select(
    transcript: Transcript, *, top_n: int, min_sec: float, max_sec: float
) -> list[ScoredSegment]:
    """Tier-2 fallback: no LLM, no network. Ranks regions by audio energy and
    word density and takes the densest window. Text stays in the source
    language - flag it so the UI can show 'translation unavailable'."""
    candidates: list[ScoredSegment] = []
    for rt in transcript.regions:
        if not rt.words:
            continue
        density = len(rt.words) / max(rt.region.duration, 1.0)
        score = max(0.0, min(100.0, 50.0 + rt.region.energy + density * 10.0))
        start, end, words = clamp_to_words(
            rt.words,
            rt.region.start_sec,
            rt.region.start_sec + max_sec,
            min_sec=min_sec,
            max_sec=max_sec,
            region=rt.region,
        )
        text = " ".join(w.text for w in words) or rt.text
        candidates.append(
            ScoredSegment(
                rank=0,
                score=round(score, 2),
                region_index=rt.region.index,
                start_sec=start,
                end_sec=end,
                hook_text=text[:60],
                subtitle_text=text,
                words=words,
            )
        )
    return dedupe_and_rank(candidates, top_n)


def _coerce_item(item: Any, by_index: dict[int, Any], min_sec: float, max_sec: float):
    if not isinstance(item, dict):
        return None
    try:
        region_index = int(item["region_index"])
    except (KeyError, TypeError, ValueError):
        return None
    rt = by_index.get(region_index)
    if rt is None:
        logger.warning("LLM referenced unknown region_index=%s, dropping", region_index)
        return None

    try:
        score = float(item.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    start, end, words = clamp_to_words(
        rt.words,
        item.get("start_sec", rt.region.start_sec),
        item.get("end_sec", rt.region.start_sec + max_sec),
        min_sec=min_sec,
        max_sec=max_sec,
        region=rt.region,
    )
    subtitle = str(item.get("subtitle_text") or "").strip() or rt.text
    hook = str(item.get("hook_text") or "").strip() or subtitle[:60]
    return ScoredSegment(
        rank=0,
        score=round(score, 2),
        region_index=region_index,
        start_sec=start,
        end_sec=end,
        hook_text=hook,
        subtitle_text=subtitle,
        words=words,
    )


async def select_clips(
    transcript: Transcript,
    *,
    top_n: int,
    min_sec: float,
    max_sec: float,
    backend: str,
) -> list[ScoredSegment]:
    """Pick the best `top_n` clips. Falls back to the heuristic tier whenever the
    LLM is unavailable or returns nothing usable."""
    if not transcript.regions:
        logger.warning("scorer received an empty transcript")
        return []

    if (backend or "").strip().lower() == "heuristic":
        return heuristic_select(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)

    prompt = build_prompt(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)
    try:
        payload = await query_llm(prompt, backend=backend)
    except LLMUnavailable as exc:
        logger.warning("scoring backend %s unavailable (%s); using heuristic tier", backend, exc)
        return heuristic_select(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)

    items = payload if isinstance(payload, list) else payload.get("clips", []) if isinstance(payload, dict) else []
    by_index = {rt.region.index: rt for rt in transcript.regions}
    candidates = [c for c in (_coerce_item(i, by_index, min_sec, max_sec) for i in items) if c]

    if not candidates:
        logger.warning("LLM returned no usable candidates; using heuristic tier")
        return heuristic_select(transcript, top_n=top_n, min_sec=min_sec, max_sec=max_sec)

    return dedupe_and_rank(candidates, top_n)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_scorer.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_pipeline/scorer.py backend/tests/test_scorer.py
git commit -m "feat(flow-studio): rubric scorer with region mapping, dedupe and heuristic fallback"
```

---

### Task 6: Cutter — correct seek order, keyframe ∩ silence snapping

**Files:**
- Modify: `backend/app/services/ai_pipeline/cutter.py`
- Create: `backend/tests/test_cutter.py`

**Interfaces:**
- Consumes: `settings.FFMPEG_BIN`/`FFPROBE_BIN`, `detect_silences` (Task 2).
- Produces:
  - `probe_keyframes(video_path: str, start_sec: float, end_sec: float, *, window_sec: float = 5.0) -> list[float]` (async)
  - `snap_cut_points(start, end, keyframes, silences, *, max_shift=2.0, min_sec, max_sec) -> tuple[float, float]`
  - `build_cut_command(input_path, output_path, start_sec, end_sec) -> list[str]`
  - `cut_video_stream(input_path, output_path, start_sec, end_sec) -> bool` (async)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_cutter.py`:

```python
from __future__ import annotations

import pytest

from app.services.ai_pipeline.cutter import build_cut_command, snap_cut_points


def test_build_cut_command_seeks_before_input():
    cmd = build_cut_command("in.mp4", "out.mp4", 12.0, 52.0)
    assert cmd[0] == "ffmpeg"
    ss = cmd.index("-ss")
    i = cmd.index("-i")
    assert ss < i, "-ss must precede -i for fast seeking"
    assert cmd[ss + 1] == "12.000"
    assert cmd[cmd.index("-t") + 1] == "40.000"
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "out.mp4"


def test_snap_cut_points_prefers_a_keyframe_inside_a_silence():
    keyframes = [0.0, 8.0, 10.0, 12.0, 50.0, 52.0]
    silences = [(9.5, 10.5), (51.5, 53.0)]
    start, end = snap_cut_points(
        11.0, 52.2, keyframes, silences, max_shift=2.0, min_sec=30, max_sec=60
    )
    assert start == pytest.approx(10.0)   # keyframe at 10.0 sits inside the 9.5-10.5 silence
    assert end == pytest.approx(51.5)     # end pulled back to the start of the next silence


def test_snap_cut_points_falls_back_to_nearest_keyframe():
    keyframes = [0.0, 9.0, 45.0]
    start, end = snap_cut_points(
        10.0, 45.5, keyframes, [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert start == pytest.approx(9.0)
    assert end == pytest.approx(45.5)


def test_snap_cut_points_ignores_keyframes_beyond_max_shift():
    keyframes = [0.0, 4.0]
    start, end = snap_cut_points(
        20.0, 60.0, keyframes, [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert start == pytest.approx(20.0)


def test_snap_cut_points_enforces_the_length_band():
    start, end = snap_cut_points(
        10.0, 200.0, [10.0], [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert end - start == pytest.approx(60.0)

    start, end = snap_cut_points(
        10.0, 15.0, [10.0], [], max_shift=2.0, min_sec=30, max_sec=60
    )
    assert end - start == pytest.approx(30.0)


def test_snap_cut_points_never_goes_negative():
    start, _ = snap_cut_points(0.5, 40.0, [], [], max_shift=2.0, min_sec=30, max_sec=60)
    assert start >= 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cutter.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_cut_command'`

- [ ] **Step 3: Rewrite the cutter**

Replace `backend/app/services/ai_pipeline/cutter.py` with:

```python
"""Fast stream-copy cutting with keyframe-aware boundaries.

Two fixes over the v0 implementation:
1. `-ss` goes BEFORE `-i` so ffmpeg seeks instead of decoding from frame 0
   (the difference is minutes on a long source).
2. Cut points are snapped to a keyframe that also sits inside a silence, so
   clips do not start on a black half-GOP or mid-word.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.cutter")


async def probe_keyframes(
    video_path: str, start_sec: float, end_sec: float, *, window_sec: float = 5.0
) -> list[float]:
    """Keyframe PTS around the requested cut points (two narrow read intervals)."""
    lo = max(0.0, start_sec - window_sec)
    hi = end_sec + window_sec
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-skip_frame", "nokey",
        "-select_streams", "v:0",
        "-show_entries", "frame=pts_time",
        "-of", "csv=print_section=0",
        "-read_intervals", f"{lo:.3f}%{hi:.3f}",
        video_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        logger.warning("ffprobe keyframe scan failed: %s", stderr.decode(errors="replace")[-500:])
        return []

    keyframes: list[float] = []
    for line in stdout.decode(errors="replace").splitlines():
        token = line.strip().rstrip(",")
        if not token:
            continue
        try:
            keyframes.append(float(token))
        except ValueError:
            continue
    keyframes.sort()
    return keyframes


def _in_silence(t: float, silences: list[tuple[float, float]]) -> bool:
    return any(s <= t <= e for s, e in silences)


def snap_cut_points(
    start_sec: float,
    end_sec: float,
    keyframes: list[float],
    silences: list[tuple[float, float]],
    *,
    max_shift: float = 2.0,
    min_sec: float,
    max_sec: float,
) -> tuple[float, float]:
    """Move the cut points onto safe boundaries, then re-enforce the length band."""
    start = max(0.0, float(start_sec))
    end = float(end_sec)

    # START: prefer a keyframe at or before `start` that is inside a silence.
    reachable = [k for k in keyframes if start - max_shift <= k <= start]
    if reachable:
        quiet = [k for k in reachable if _in_silence(k, silences)]
        start = max(quiet) if quiet else max(reachable)

    # END: prefer the beginning of a silence just after `end` (never mid-word).
    quiet_ends = [s for s, _ in silences if end - max_shift <= s <= end + max_shift]
    if quiet_ends:
        end = min(quiet_ends, key=lambda s: abs(s - end))

    start = max(0.0, start)
    if end - start > max_sec:
        end = start + max_sec
    if end - start < min_sec:
        end = start + min_sec
    return round(start, 3), round(end, 3)


def build_cut_command(
    input_path: str, output_path: str, start_sec: float, end_sec: float
) -> list[str]:
    duration = max(0.0, float(end_sec) - float(start_sec))
    return [
        settings.FFMPEG_BIN, "-y",
        "-ss", f"{float(start_sec):.3f}",
        "-i", input_path,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ]


async def cut_video_stream(
    input_path: str, output_path: str, start_sec: float, end_sec: float
) -> bool:
    """Stream copy — no re-encode. Returns False on ffmpeg failure."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = build_cut_command(input_path, output_path, start_sec, end_sec)
    logger.info("cutting %.3fs-%.3fs -> %s", start_sec, end_sec, output_path)
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error("ffmpeg cut failed: %s", stderr.decode(errors="replace")[-2000:])
        return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cutter.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_pipeline/cutter.py backend/tests/test_cutter.py
git commit -m "fix(flow-studio): seek before input and snap cuts to keyframe-in-silence"
```

---

### Task 7: 9:16 crop window computation

**Files:**
- Create: `backend/app/services/ai_pipeline/crop.py`
- Create: `backend/tests/test_crop.py`

**Interfaces:**
- Consumes: `settings.FFPROBE_BIN`.
- Produces:
  - `probe_video_size(video_path: str) -> tuple[int, int]` (async)
  - `smooth_positions(positions: list[float], *, alpha: float = 0.3) -> list[float]`
  - `compute_crop(source_w: int, source_h: int, centres: list[tuple[float, float]]) -> dict[str, Any]`
  - `compute_crop_path(video_path, start_sec, end_sec, *, sample_fps=1.0) -> dict[str, Any]` (async)

  The returned crop dict is `{"source_w", "source_h", "crop_w", "crop_h", "x", "y", "path": [{"t": float, "x": int}], "tracker": "face"|"center"}`. `x` is the **static** crop x used by the renderer (median of the path); the full `path` is preserved in the clipspec so the OpenCut editor can animate it later.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_crop.py`:

```python
from __future__ import annotations

import pytest

from app.services.ai_pipeline.crop import compute_crop, smooth_positions


def test_smooth_positions_damps_a_spike():
    raw = [100.0, 100.0, 800.0, 100.0, 100.0]
    smoothed = smooth_positions(raw, alpha=0.3)
    assert len(smoothed) == len(raw)
    assert smoothed[0] == pytest.approx(100.0)
    assert smoothed[2] < 400.0            # the 800 spike is heavily damped
    assert max(smoothed) <= max(raw)


def test_compute_crop_centres_when_there_are_no_detections():
    crop = compute_crop(1920, 1080, [])
    assert crop["crop_h"] == 1080
    assert crop["crop_w"] == 608          # round(1080 * 9 / 16) == 608, already even
    assert crop["x"] == 656               # (1920 - 608) // 2
    assert crop["tracker"] == "center"
    assert crop["y"] == 0


def test_compute_crop_follows_detections_and_clamps_to_frame():
    crop = compute_crop(1920, 1080, [(0.0, 1900.0), (1.0, 1900.0), (2.0, 1900.0)])
    assert crop["x"] + crop["crop_w"] <= 1920
    assert crop["x"] >= 0
    assert crop["tracker"] == "face"
    assert len(crop["path"]) == 3
    assert all(p["x"] >= 0 for p in crop["path"])


def test_compute_crop_on_portrait_source_uses_full_width():
    crop = compute_crop(1080, 1920, [])
    assert crop["crop_w"] == 1080
    assert crop["x"] == 0


def test_compute_crop_path_entries_carry_timestamps():
    crop = compute_crop(1920, 1080, [(0.0, 500.0), (1.5, 700.0)])
    assert [p["t"] for p in crop["path"]] == [0.0, 1.5]
```

> Note on `crop_w`: `round(1080 * 9 / 16) == 608`, which is already even, so the even-width guard in the implementation is a no-op for a 1920×1080 source. It matters for odd-height sources (e.g. 1918×1078 → 606 after the guard).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_crop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai_pipeline.crop'`

- [ ] **Step 3: Implement the crop module**

Create `backend/app/services/ai_pipeline/crop.py`:

```python
"""9:16 crop-window computation.

Samples frames at a low rate, finds the dominant face (OpenCV Haar cascade,
CPU, no model download beyond what ships with opencv), smooths the horizontal
centre with an EMA, and returns both a static crop rect for this render pass
and the full per-sample path for the editor to animate later.

If OpenCV is unavailable or no face is found, it degrades to a centre crop -
never an error.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.crop")

TARGET_RATIO = 9.0 / 16.0


async def probe_video_size(video_path: str) -> tuple[int, int]:
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=print_section=0:s=x",
        video_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return 0, 0
    try:
        w, h = stdout.decode().strip().split(",")[0].split("x")
        return int(w), int(h)
    except (ValueError, IndexError):
        return 0, 0


def smooth_positions(positions: list[float], *, alpha: float = 0.3) -> list[float]:
    """Exponential moving average — stops the crop jittering frame to frame."""
    out: list[float] = []
    state: float | None = None
    for value in positions:
        state = value if state is None else alpha * value + (1.0 - alpha) * state
        out.append(state)
    return out


def compute_crop(
    source_w: int, source_h: int, centres: list[tuple[float, float]]
) -> dict[str, Any]:
    """Build the crop rect from `[(t, centre_x)]` samples."""
    source_w = max(2, int(source_w))
    source_h = max(2, int(source_h))

    crop_h = source_h
    crop_w = int(round(source_h * TARGET_RATIO))
    crop_w -= crop_w % 2  # x264 requires even dimensions
    if crop_w >= source_w:
        crop_w = source_w - (source_w % 2)

    max_x = max(0, source_w - crop_w)
    default_x = max_x // 2

    if not centres:
        return {
            "source_w": source_w,
            "source_h": source_h,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "x": default_x,
            "y": 0,
            "path": [],
            "tracker": "center",
        }

    times = [t for t, _ in centres]
    smoothed = smooth_positions([c for _, c in centres], alpha=0.3)
    xs = [int(min(max_x, max(0, round(c - crop_w / 2.0)))) for c in smoothed]
    path = [{"t": round(t, 3), "x": x} for t, x in zip(times, xs)]
    ordered = sorted(xs)
    static_x = ordered[len(ordered) // 2]

    return {
        "source_w": source_w,
        "source_h": source_h,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "x": int(static_x),
        "y": 0,
        "path": path,
        "tracker": "face",
    }


def _sample_face_centres(
    video_path: str, start_sec: float, end_sec: float, sample_fps: float
) -> list[tuple[float, float]]:
    try:
        import cv2
    except ImportError:
        logger.info("opencv unavailable; falling back to centre crop")
        return []

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        logger.warning("opencv could not open %s", video_path)
        return []

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    step = 1.0 / max(sample_fps, 0.1)
    centres: list[tuple[float, float]] = []
    t = start_sec
    try:
        while t < end_sec:
            capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                centres.append((round(t - start_sec, 3), float(x) + float(w) / 2.0))
            t += step
    finally:
        capture.release()
    return centres


async def compute_crop_path(
    video_path: str, start_sec: float, end_sec: float, *, sample_fps: float = 1.0
) -> dict[str, Any]:
    """Full pipeline entry point: probe size, sample faces, build the crop rect."""
    source_w, source_h = await probe_video_size(video_path)
    if source_w <= 0 or source_h <= 0:
        logger.warning("could not probe size for %s; assuming 1920x1080", video_path)
        source_w, source_h = 1920, 1080

    if source_w <= int(round(source_h * TARGET_RATIO)):
        # Already portrait or narrower than 9:16 — nothing to track.
        return compute_crop(source_w, source_h, [])

    loop = asyncio.get_running_loop()
    centres = await loop.run_in_executor(
        None, _sample_face_centres, video_path, start_sec, end_sec, sample_fps
    )
    return compute_crop(source_w, source_h, centres)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_crop.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_pipeline/crop.py backend/tests/test_crop.py
git commit -m "feat(flow-studio): 9:16 crop window with face tracking and centre fallback"
```

---

### Task 8: ASS subtitle generation, clipspec v2, and the burn-in render pass

**Files:**
- Modify: `backend/app/services/ai_pipeline/subtitle_gen.py`
- Create: `backend/app/services/ai_pipeline/renderer.py`
- Create: `backend/tests/test_subtitle_gen.py`
- Create: `backend/tests/test_renderer.py`

**Interfaces:**
- Consumes: `ScoredSegment`/`Word` (Task 1), crop dict (Task 7), `settings.CLIP_FONT_DIR`/`CLIP_SUBTITLE_FONT`/`FFMPEG_BIN`.
- Produces:
  - `subtitle_gen.ass_time(seconds: float) -> str`
  - `subtitle_gen.split_cues(text: str, start_sec: float, end_sec: float, *, max_chars: int = 42, max_cue_sec: float = 3.5) -> list[tuple[float, float, str]]`
  - `subtitle_gen.build_ass(segment: ScoredSegment, *, font_name: str, video_w: int = 1080, video_h: int = 1920) -> str`
  - `subtitle_gen.generate_clipspec(segment, *, video_url, crop, ass_relative_path) -> dict[str, Any]`
  - `renderer.resolve_font_name(font_dir: str, preferred: str) -> str`
  - `renderer.escape_filter_path(path: str) -> str`
  - `renderer.build_render_command(input_path, output_path, *, crop, ass_path, font_dir) -> list[str]`
  - `renderer.burn_vertical(input_path, output_path, *, crop, ass_path, font_dir) -> bool` (async)

- [ ] **Step 1: Write the failing subtitle test**

Create `backend/tests/test_subtitle_gen.py`:

```python
from __future__ import annotations

import pytest

from app.services.ai_pipeline.subtitle_gen import (
    ass_time,
    build_ass,
    generate_clipspec,
    split_cues,
)
from app.services.ai_pipeline.types import ScoredSegment, Word


@pytest.fixture()
def segment() -> ScoredSegment:
    words = tuple(Word(10.0 + i * 0.5, 10.4 + i * 0.5, f"w{i}") for i in range(20))
    return ScoredSegment(
        rank=1,
        score=92.0,
        region_index=0,
        start_sec=10.0,
        end_sec=40.0,
        hook_text="Đừng bỏ lỡ điều này",
        subtitle_text=(
            "Xin chào các bạn, hôm nay chúng ta sẽ nói về một chủ đề rất thú vị. "
            "Hãy cùng tìm hiểu ngay bây giờ nhé."
        ),
        words=words,
    )


def test_ass_time_formats_centiseconds():
    assert ass_time(0.0) == "0:00:00.00"
    assert ass_time(3661.25) == "1:01:01.25"
    assert ass_time(9.999) == "0:00:09.99"


def test_split_cues_respects_char_and_duration_limits(segment: ScoredSegment):
    cues = split_cues(segment.subtitle_text, 0.0, 30.0, max_chars=42, max_cue_sec=3.5)
    assert len(cues) >= 3
    assert all(len(text) <= 42 for _, _, text in cues)
    assert all(end - start <= 3.5 + 1e-6 for start, end, _ in cues)
    assert cues[0][0] == pytest.approx(0.0)
    assert cues[-1][1] <= 30.0 + 1e-6
    # Cues must be strictly ordered and non-overlapping.
    for prev, curr in zip(cues, cues[1:]):
        assert prev[1] <= curr[0] + 1e-6


def test_split_cues_on_empty_text_returns_nothing():
    assert split_cues("   ", 0.0, 10.0) == []


def test_build_ass_has_header_style_and_relative_timings(segment: ScoredSegment):
    ass = build_ass(segment, font_name="Be Vietnam Pro", video_w=1080, video_h=1920)
    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Be Vietnam Pro" in ass
    assert "Style: Hook," in ass
    assert "Style: Body," in ass
    assert "Đừng bỏ lỡ điều này" in ass
    # Timings are clip-relative (the burn runs on the already-cut file).
    assert "Dialogue: 0,0:00:00.00" in ass
    assert "0:00:10." not in ass.split("[Events]")[1]


def test_generate_clipspec_v2_shape(segment: ScoredSegment):
    crop = {
        "source_w": 1920, "source_h": 1080, "crop_w": 608, "crop_h": 1080,
        "x": 656, "y": 0, "path": [{"t": 0.0, "x": 656}], "tracker": "face",
    }
    spec = generate_clipspec(
        segment,
        video_url="/uploads/clips/u1/job_clip_1.mp4",
        crop=crop,
        ass_relative_path="/uploads/clips/u1/job_clip_1.ass",
    )
    assert spec["version"] == 2
    assert spec["video_url"] == "/uploads/clips/u1/job_clip_1.mp4"
    assert spec["subtitle_url"] == "/uploads/clips/u1/job_clip_1.ass"
    assert spec["duration"] == pytest.approx(30.0)
    assert spec["hook_text"] == "Đừng bỏ lỡ điều này"
    assert spec["crop"]["tracker"] == "face"
    assert spec["style"]["font"] == "Be Vietnam Pro"
    assert spec["words"][0] == {"start": 0.0, "end": pytest.approx(0.4), "word": "w0"}
    assert spec["cues"] and spec["cues"][0]["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_subtitle_gen.py -v`
Expected: FAIL — `ImportError: cannot import name 'ass_time'`

- [ ] **Step 3: Rewrite subtitle_gen**

Replace `backend/app/services/ai_pipeline/subtitle_gen.py` with:

```python
"""ASS subtitle generation + clipspec v2.

Two outputs, one source of truth:
- `build_ass` produces the file libass burns into the video (server-side, so
  Vietnamese diacritics are guaranteed regardless of the viewer's fonts).
- `generate_clipspec` produces the JSON the OpenCut editor round-trips.

Both use clip-RELATIVE timings, because the burn happens on the already-cut
file where t=0 is the clip start.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.ai_pipeline.types import ScoredSegment

logger = logging.getLogger("flowmeta.ai_pipeline.subtitle")

MAX_CUE_CHARS = 42
MAX_CUE_SEC = 3.5
MIN_CUE_SEC = 0.8

_ASS_TEMPLATE = """[Script Info]
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {video_w}
PlayResY: {video_h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},{hook_size},&H0000D7FF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,8,60,60,180,1
Style: Body,{font},{body_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""


def ass_time(seconds: float) -> str:
    """ASS timestamp: H:MM:SS.cc (centiseconds, truncated)."""
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    centis = int((total - int(total)) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def split_cues(
    text: str,
    start_sec: float,
    end_sec: float,
    *,
    max_chars: int = MAX_CUE_CHARS,
    max_cue_sec: float = MAX_CUE_SEC,
) -> list[tuple[float, float, str]]:
    """Split subtitle text into readable cues and distribute them across the clip.

    Timing is proportional to character count — the translated Vietnamese text
    does not align 1:1 with source-language word timestamps, so per-character
    interpolation is the honest approximation.
    """
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    duration = max(0.0, float(end_sec) - float(start_sec))
    total_chars = sum(len(line) for line in lines) or 1
    cues: list[tuple[float, float, str]] = []
    cursor = float(start_sec)
    for i, line in enumerate(lines):
        share = duration * (len(line) / total_chars)
        cue_len = max(MIN_CUE_SEC, min(max_cue_sec, share))
        cue_end = min(float(end_sec), cursor + cue_len)
        if i == len(lines) - 1:
            cue_end = min(float(end_sec), max(cue_end, cursor + MIN_CUE_SEC))
        if cue_end <= cursor:
            break
        cues.append((round(cursor, 3), round(cue_end, 3), line))
        cursor = cue_end
    return cues


def build_ass(
    segment: ScoredSegment,
    *,
    font_name: str,
    video_w: int = 1080,
    video_h: int = 1920,
) -> str:
    """Render the ASS file for one clip. Timings are clip-relative."""
    duration = segment.duration
    events: list[str] = []

    hook = _escape_ass_text(segment.hook_text.strip())
    if hook:
        hook_end = min(duration, 3.0)
        events.append(
            f"Dialogue: 0,{ass_time(0.0)},{ass_time(hook_end)},Hook,,0,0,0,,{hook}"
        )

    for start, end, line in split_cues(segment.subtitle_text, 0.0, duration):
        events.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Body,,0,0,0,,{_escape_ass_text(line)}"
        )

    return _ASS_TEMPLATE.format(
        video_w=video_w,
        video_h=video_h,
        font=font_name,
        hook_size=int(video_h * 0.045),
        body_size=int(video_h * 0.035),
        events="\n".join(events),
    )


def generate_clipspec(
    segment: ScoredSegment,
    *,
    video_url: str,
    crop: dict[str, Any],
    ass_relative_path: str,
) -> dict[str, Any]:
    """The editor-facing contract. Version 2 = burned server-side + crop path."""
    duration = segment.duration
    return {
        "version": 2,
        "video_url": video_url,
        "subtitle_url": ass_relative_path,
        "duration": round(duration, 3),
        "source_start_sec": segment.start_sec,
        "source_end_sec": segment.end_sec,
        "rank": segment.rank,
        "score": segment.score,
        "hook_text": segment.hook_text,
        "subtitle_text": segment.subtitle_text,
        # Relative to the clip, so the editor can scrub without re-deriving offsets.
        "words": [
            {
                "start": round(w.start - segment.start_sec, 3),
                "end": round(w.end - segment.start_sec, 3),
                "word": w.text,
            }
            for w in segment.words
        ],
        "cues": [
            {"start": start, "end": end, "text": text}
            for start, end, text in split_cues(segment.subtitle_text, 0.0, duration)
        ],
        "crop": crop,
        "style": {
            "font": "Be Vietnam Pro",
            "fontSize": 48,
            "color": "#FFFFFF",
            "highlightColor": "#FFD700",
            "stroke": "#000000",
        },
    }
```

- [ ] **Step 4: Run the subtitle test**

Run: `cd backend && python -m pytest tests/test_subtitle_gen.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Write the failing renderer test**

Create `backend/tests/test_renderer.py`:

```python
from __future__ import annotations

from pathlib import Path

from app.services.ai_pipeline.renderer import (
    build_render_command,
    escape_filter_path,
    resolve_font_name,
)

CROP = {
    "source_w": 1920, "source_h": 1080, "crop_w": 608, "crop_h": 1080,
    "x": 656, "y": 0, "path": [], "tracker": "center",
}


def test_escape_filter_path_handles_windows_drive_letters():
    assert escape_filter_path(r"E:\clips\job.ass") == r"E\:/clips/job.ass"


def test_escape_filter_path_leaves_posix_paths_intact():
    assert escape_filter_path("/app/uploads/clips/job.ass") == "/app/uploads/clips/job.ass"


def test_escape_filter_path_escapes_single_quotes():
    assert escape_filter_path("/tmp/it's.ass") == "/tmp/it\\'s.ass"


def test_resolve_font_name_prefers_the_vendored_font(tmp_path: Path):
    (tmp_path / "BeVietnamPro-Bold.ttf").write_bytes(b"\x00")
    assert resolve_font_name(str(tmp_path), "Be Vietnam Pro") == "Be Vietnam Pro"


def test_resolve_font_name_falls_back_when_dir_is_empty(tmp_path: Path):
    assert resolve_font_name(str(tmp_path), "Be Vietnam Pro") == "DejaVu Sans"


def test_resolve_font_name_falls_back_when_dir_is_missing():
    assert resolve_font_name("/definitely/not/here", "Be Vietnam Pro") == "DejaVu Sans"


def test_build_render_command_chains_crop_scale_and_subtitles():
    cmd = build_render_command(
        "in.mp4", "out.mp4", crop=CROP, ass_path="/app/x.ass", font_dir="/app/assets/fonts"
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("crop=608:1080:656:0,")
    assert "scale=1080:1920" in vf
    assert "subtitles='/app/x.ass'" in vf
    assert "fontsdir='/app/assets/fonts'" in vf
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-preset") + 1] == "veryfast"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[-1] == "out.mp4"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai_pipeline.renderer'`

- [ ] **Step 7: Implement the renderer**

Create `backend/app/services/ai_pipeline/renderer.py`:

```python
"""Vertical render pass: crop to 9:16, scale to 1080x1920, burn the ASS.

This is the only re-encode in the pipeline (libx264 veryfast). Burning is done
server-side so Vietnamese diacritics render identically everywhere, which is
the whole reason for shipping the font with the image.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.renderer")

FALLBACK_FONT = "DejaVu Sans"
OUTPUT_W = 1080
OUTPUT_H = 1920


def resolve_font_name(font_dir: str, preferred: str) -> str:
    """Use the vendored font only if a TTF/OTF is actually present."""
    directory = Path(font_dir)
    if directory.is_dir():
        for pattern in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
            if any(directory.glob(pattern)):
                return preferred
    logger.warning("no font files in %s; falling back to %s", font_dir, FALLBACK_FONT)
    return FALLBACK_FONT


def escape_filter_path(path: str) -> str:
    """Escape a path for use inside an ffmpeg filtergraph argument.

    ffmpeg parses `:` as an option separator inside filters, so a Windows drive
    letter has to be escaped; backslashes become forward slashes.
    """
    escaped = str(path).replace("\\", "/")
    escaped = escaped.replace(":", "\\:")
    escaped = escaped.replace("'", "\\'")
    return escaped


def build_render_command(
    input_path: str,
    output_path: str,
    *,
    crop: dict[str, Any],
    ass_path: str,
    font_dir: str,
) -> list[str]:
    vf = (
        f"crop={int(crop['crop_w'])}:{int(crop['crop_h'])}:{int(crop['x'])}:{int(crop['y'])},"
        f"scale={OUTPUT_W}:{OUTPUT_H}:flags=bicubic,"
        f"subtitles='{escape_filter_path(ass_path)}':fontsdir='{escape_filter_path(font_dir)}'"
    )
    return [
        settings.FFMPEG_BIN, "-y",
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]


async def burn_vertical(
    input_path: str,
    output_path: str,
    *,
    crop: dict[str, Any],
    ass_path: str,
    font_dir: str,
) -> bool:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = build_render_command(
        input_path, output_path, crop=crop, ass_path=ass_path, font_dir=font_dir
    )
    logger.info("rendering vertical clip -> %s", output_path)
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error("ffmpeg render failed: %s", stderr.decode(errors="replace")[-2000:])
        return False
    return True
```

- [ ] **Step 8: Run both test modules**

Run: `cd backend && python -m pytest tests/test_renderer.py tests/test_subtitle_gen.py -v`
Expected: PASS (12 passed)

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/ai_pipeline/subtitle_gen.py backend/app/services/ai_pipeline/renderer.py backend/tests/test_subtitle_gen.py backend/tests/test_renderer.py
git commit -m "feat(flow-studio): ASS subtitles, clipspec v2, and server-side burn-in render"
```

---

### Task 9: Source resolution (upload / link download + sha256)

**Files:**
- Create: `backend/app/services/ai_pipeline/source.py`
- Create: `backend/tests/test_source.py`

**Interfaces:**
- Consumes: `settings.YTDLP_BIN`, `ClipSourceType` from `app.models.clip_models`.
- Produces:
  - `class SourceUnavailable(RuntimeError)`
  - `sha256_file(path: str, *, chunk_size: int = 1 << 20) -> str`
  - `build_download_command(url: str, output_path: str) -> list[str]`
  - `resolve_source(source_type, source_ref: str, work_dir: Path, job_id: str) -> tuple[str, bool]` (async) — returns `(local_path, is_temporary)`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_source.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.models.clip_models import ClipSourceType
from app.services.ai_pipeline import source as source_mod
from app.services.ai_pipeline.source import (
    SourceUnavailable,
    build_download_command,
    resolve_source,
    sha256_file,
)


def test_sha256_file_matches_hashlib(tmp_path: Path):
    path = tmp_path / "blob.bin"
    payload = b"flowmeta" * 5000
    path.write_bytes(payload)
    assert sha256_file(str(path)) == hashlib.sha256(payload).hexdigest()


def test_build_download_command_is_argument_list_not_shell():
    cmd = build_download_command("https://youtu.be/abc", "/tmp/out.mp4")
    assert cmd[0] == "yt-dlp"
    assert "--no-playlist" in cmd
    assert cmd[cmd.index("-o") + 1] == "/tmp/out.mp4"
    assert cmd[-1] == "https://youtu.be/abc"
    assert all(isinstance(part, str) for part in cmd)


async def test_resolve_source_upload_returns_the_path_untouched(tmp_path: Path):
    src = tmp_path / "uploaded.mp4"
    src.write_bytes(b"video")
    path, is_temp = await resolve_source(
        ClipSourceType.UPLOAD, str(src), tmp_path, "job-1"
    )
    assert path == str(src)
    assert is_temp is False


async def test_resolve_source_upload_missing_file_raises(tmp_path: Path):
    with pytest.raises(SourceUnavailable):
        await resolve_source(ClipSourceType.UPLOAD, str(tmp_path / "nope.mp4"), tmp_path, "job-1")


async def test_resolve_source_link_downloads_and_marks_temporary(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    async def fake_run(cmd: list[str]) -> tuple[int, str]:
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"downloaded")
        return 0, ""

    monkeypatch.setattr(source_mod, "_run", fake_run)

    path, is_temp = await resolve_source(
        ClipSourceType.LINK, "https://youtu.be/abc", tmp_path, "job-1"
    )
    assert is_temp is True
    assert Path(path).exists()
    assert len(calls) == 1


async def test_resolve_source_link_failure_raises(monkeypatch, tmp_path: Path):
    async def fake_run(cmd: list[str]) -> tuple[int, str]:
        return 1, "ERROR: Video unavailable"

    monkeypatch.setattr(source_mod, "_run", fake_run)

    with pytest.raises(SourceUnavailable) as exc:
        await resolve_source(ClipSourceType.LINK, "https://youtu.be/abc", tmp_path, "job-1")
    assert "unavailable" in str(exc.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai_pipeline.source'`

- [ ] **Step 3: Implement source resolution**

Create `backend/app/services/ai_pipeline/source.py`:

```python
"""Turn a ClipJob source into a local file the pipeline can read.

Uploads are already on disk. Links go through yt-dlp — never through ffmpeg
directly, which would re-download the stream once per ffmpeg invocation.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from app.config import settings
from app.models.clip_models import ClipSourceType

logger = logging.getLogger("flowmeta.ai_pipeline.source")


class SourceUnavailable(RuntimeError):
    """The source video could not be obtained."""


def sha256_file(path: str, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_download_command(url: str, output_path: str) -> list[str]:
    return [
        settings.YTDLP_BIN,
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url,
    ]


async def _run(cmd: list[str]) -> tuple[int, str]:
    """Seam so tests can stub subprocess execution."""
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise SourceUnavailable(f"{cmd[0]} is not installed on this host") from exc
    _, stderr = await process.communicate()
    return process.returncode, stderr.decode(errors="replace")


async def resolve_source(
    source_type: ClipSourceType,
    source_ref: str,
    work_dir: Path,
    job_id: str,
) -> tuple[str, bool]:
    """Return `(local_path, is_temporary)`. Temporary files are the caller's to delete."""
    work_dir.mkdir(parents=True, exist_ok=True)

    if source_type == ClipSourceType.UPLOAD:
        if not Path(source_ref).is_file():
            raise SourceUnavailable(f"uploaded source is missing: {source_ref}")
        return source_ref, False

    output_path = str(work_dir / f"{job_id}_source.mp4")
    logger.info("downloading link source for job %s", job_id)
    code, stderr = await _run(build_download_command(source_ref, output_path))
    if code != 0 or not Path(output_path).is_file():
        raise SourceUnavailable(f"download failed: {stderr.strip()[-500:] or 'unknown error'}")
    return output_path, True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_source.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_pipeline/source.py backend/tests/test_source.py
git commit -m "feat(flow-studio): resolve upload/link sources via yt-dlp with sha256"
```

---

### Task 10: Runner rewire — short sessions, per-clip isolation, cache, cleanup

**Files:**
- Modify: `backend/app/services/clip_runner.py` (full rewrite)
- Modify: `backend/app/routers/clip_jobs.py:30-45` (the `POST /api/clip-jobs` form defaults)
- Modify: `backend/tests/test_clip_runner.py` (full rewrite)

**Interfaces:**
- Consumes: every stage from Tasks 2–9, `ClipJob`/`Clip`/`ClipJobStatus`/`ClipStatus`/`ClipSourceType`, `event_bus.publish`.
- Produces:
  - `JobContext` dataclass: `job_id, user_id, source_type, source_ref, top_n, min_sec, max_sec, scoring_backend`
  - `ClipRunner(session_factory, publish)` with `run(job_id) -> None`
  - `ClipRunner.PIPELINE_VERSION` sourced from `settings.CLIP_PIPELINE_VERSION`

- [ ] **Step 1: Write the failing test**

Replace `backend/tests/test_clip_runner.py` with:

```python
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus
from app.services import clip_runner as runner_mod
from app.services.ai_pipeline.types import HotRegion, RegionTranscript, ScoredSegment, Transcript, Word


def _segment(rank: int, start: float) -> ScoredSegment:
    words = tuple(Word(start + i, start + i + 0.5, f"w{i}") for i in range(4))
    return ScoredSegment(
        rank=rank,
        score=90.0 - rank,
        region_index=0,
        start_sec=start,
        end_sec=start + 40.0,
        hook_text=f"hook {rank}",
        subtitle_text=f"Nội dung {rank}",
        words=words,
    )


@pytest.fixture()
def fake_pipeline(monkeypatch, tmp_path: Path):
    """Stub every external process so the runner can be exercised without
    ffmpeg, whisper, yt-dlp or network."""
    state: dict[str, list] = {"cuts": [], "renders": [], "published": []}

    async def fake_resolve_source(source_type, source_ref, work_dir, job_id):
        path = tmp_path / "source.mp4"
        path.write_bytes(b"video-bytes")
        return str(path), False

    async def fake_extract_audio(video_path, audio_path):
        Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
        Path(audio_path).write_bytes(b"wav")
        return True

    def fake_detect_hot_regions(wav_path, **kwargs):
        return [HotRegion(index=0, start_sec=0.0, end_sec=120.0, energy=-12.0)]

    def fake_detect_silences(wav_path, **kwargs):
        return [(39.0, 40.5)]

    async def fake_transcribe_regions(audio_path, regions, **kwargs):
        region = regions[0]
        words = tuple(Word(i * 1.0, i * 1.0 + 0.5, f"w{i}") for i in range(10))
        return Transcript(
            language="en",
            regions=(RegionTranscript(region=region, text="hello world", words=words),),
        )

    async def fake_select_clips(transcript, *, top_n, min_sec, max_sec, backend):
        return [_segment(1, 10.0), _segment(2, 60.0)]

    async def fake_probe_keyframes(video_path, start, end, **kwargs):
        return [0.0, 10.0, 60.0]

    async def fake_cut(input_path, output_path, start, end):
        state["cuts"].append((output_path, start, end))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"cut")
        return True

    async def fake_crop_path(video_path, start, end, **kwargs):
        return {"source_w": 1920, "source_h": 1080, "crop_w": 608, "crop_h": 1080,
                "x": 656, "y": 0, "path": [], "tracker": "center"}

    async def fake_burn(input_path, output_path, **kwargs):
        state["renders"].append(output_path)
        Path(output_path).write_bytes(b"rendered")
        return True

    monkeypatch.setattr(runner_mod, "resolve_source", fake_resolve_source)
    monkeypatch.setattr(runner_mod, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(runner_mod, "detect_hot_regions", fake_detect_hot_regions)
    monkeypatch.setattr(runner_mod, "detect_silences", fake_detect_silences)
    monkeypatch.setattr(runner_mod, "transcribe_regions", fake_transcribe_regions)
    monkeypatch.setattr(runner_mod, "select_clips", fake_select_clips)
    monkeypatch.setattr(runner_mod, "probe_keyframes", fake_probe_keyframes)
    monkeypatch.setattr(runner_mod, "cut_video_stream", fake_cut)
    monkeypatch.setattr(runner_mod, "compute_crop_path", fake_crop_path)
    monkeypatch.setattr(runner_mod, "burn_vertical", fake_burn)
    monkeypatch.setattr(runner_mod.settings, "CLIP_UPLOAD_DIR", str(tmp_path / "clips"))
    return state


async def _make_job(session, user_id) -> ClipJob:
    job = ClipJob(
        user_id=user_id,
        source_type=ClipSourceType.LINK,
        source_ref="https://youtu.be/x",
        params={"top_n": 2, "clip_min_sec": 30, "clip_max_sec": 60, "scoring_backend": "gemini"},
    )
    session.add(job)
    await session.commit()
    return job


async def test_runner_completes_and_persists_clips(session, session_factory, user_id, fake_pipeline):
    published = []

    async def publish(channel, event_type, data):
        published.append((channel, event_type, data))

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.DONE
    assert job.finished_at is not None
    assert job.error is None

    clips = (await session.execute(select(Clip).where(Clip.job_id == job.id))).scalars().all()
    assert len(clips) == 2
    assert {c.rank for c in clips} == {1, 2}
    assert all(c.status == ClipStatus.READY for c in clips)
    assert all(c.clipspec["version"] == 2 for c in clips)
    assert all(Path(c.output_ref).exists() for c in clips)

    phases = [d["phase"] for ch, et, d in published if et == "phase"]
    assert phases == ["analyzing", "scoring", "rendering"]
    assert any(et == "done" for _, et, _ in published)


async def test_runner_records_source_sha_and_pipeline_version(session, session_factory, user_id, fake_pipeline):
    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.source_sha256 and len(job.source_sha256) == 64
    assert job.params["pipeline_version"] == runner_mod.settings.CLIP_PIPELINE_VERSION


async def test_runner_isolates_a_single_failing_clip(session, session_factory, user_id, fake_pipeline, monkeypatch):
    async def flaky_cut(input_path, output_path, start, end):
        if "clip_1" in output_path:
            return False
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"cut")
        return True

    monkeypatch.setattr(runner_mod, "cut_video_stream", flaky_cut)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.DONE  # the job still finishes
    clips = (await session.execute(select(Clip).where(Clip.job_id == job.id))).scalars().all()
    statuses = sorted(c.status for c in clips, key=lambda s: s.value)
    assert ClipStatus.ERROR in statuses
    assert ClipStatus.READY in statuses


async def test_runner_marks_error_when_source_cannot_be_resolved(session, session_factory, user_id, fake_pipeline, monkeypatch):
    from app.services.ai_pipeline.source import SourceUnavailable

    async def failing_resolve(source_type, source_ref, work_dir, job_id):
        raise SourceUnavailable("download failed: private video")

    monkeypatch.setattr(runner_mod, "resolve_source", failing_resolve)

    published = []

    async def publish(channel, event_type, data):
        published.append((channel, event_type, data))

    job = await _make_job(session, user_id)
    with pytest.raises(SourceUnavailable):
        await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.ERROR
    assert "private video" in job.error
    assert any(et == "error" for _, et, _ in published)


async def test_runner_marks_error_when_no_clips_selected(session, session_factory, user_id, fake_pipeline, monkeypatch):
    async def empty_select(transcript, *, top_n, min_sec, max_sec, backend):
        return []

    monkeypatch.setattr(runner_mod, "select_clips", empty_select)

    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    with pytest.raises(RuntimeError):
        await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    await session.refresh(job)
    assert job.status == ClipJobStatus.ERROR


async def test_runner_deletes_the_temp_audio(session, session_factory, user_id, fake_pipeline, tmp_path):
    async def publish(channel, event_type, data):
        return None

    job = await _make_job(session, user_id)
    await runner_mod.ClipRunner(session_factory=session_factory, publish=publish).run(str(job.id))

    leftovers = list((tmp_path / "clips").rglob("*.wav"))
    assert leftovers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_clip_runner.py -v`
Expected: FAIL — `AttributeError: module 'app.services.clip_runner' has no attribute 'resolve_source'`

- [ ] **Step 3: Rewrite the runner**

Replace `backend/app/services/clip_runner.py` with:

```python
"""Flow Studio clip pipeline runner.

Orchestration only — every algorithm lives in `app.services.ai_pipeline.*`.

Two structural rules the v0 runner broke:
1. A DB session is opened per phase boundary and closed immediately. The
   pipeline itself runs with NO session held, because a single job can occupy
   the CPU for many minutes and a pinned connection starves the pool.
2. A failure rendering clip 3 marks clip 3 ERROR; it does not fail the job.
   Only source resolution, ASR, and "zero clips selected" are fatal.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models.clip_models import Clip, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus
from app.services.ai_pipeline.asr_engine import transcribe_regions
from app.services.ai_pipeline.crop import compute_crop_path
from app.services.ai_pipeline.cutter import cut_video_stream, probe_keyframes, snap_cut_points
from app.services.ai_pipeline.prefilter import detect_hot_regions, detect_silences
from app.services.ai_pipeline.renderer import burn_vertical, resolve_font_name
from app.services.ai_pipeline.scorer import select_clips
from app.services.ai_pipeline.source import resolve_source, sha256_file
from app.services.ai_pipeline.subtitle_gen import build_ass, generate_clipspec
from app.services.ai_pipeline.vad_filter import extract_audio

logger = logging.getLogger("flowmeta.clip_runner")


@dataclass(frozen=True)
class JobContext:
    job_id: str
    job_uuid: uuid.UUID
    user_id: str
    source_type: ClipSourceType
    source_ref: str
    top_n: int
    min_sec: float
    max_sec: float
    scoring_backend: str


class ClipRunner:
    def __init__(self, session_factory, publish) -> None:
        self._session_factory = session_factory
        self._publish = publish

    # ------------------------------------------------------------------ DB

    async def _load_context(self, job_id: str) -> JobContext:
        job_uuid = uuid.UUID(job_id)
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))).scalar_one()
            params = job.params or {}
            return JobContext(
                job_id=job_id,
                job_uuid=job_uuid,
                user_id=str(job.user_id),
                source_type=job.source_type,
                source_ref=job.source_ref,
                top_n=int(params.get("top_n", 3)),
                min_sec=float(params.get("clip_min_sec", 30)),
                max_sec=float(params.get("clip_max_sec", 60)),
                scoring_backend=str(params.get("scoring_backend", settings.SCORING_BACKEND)),
            )

    async def _set_phase(self, ctx: JobContext, status: ClipJobStatus, phase: str) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.status = status
            await session.commit()
        await self._publish(
            "clip", "phase", {"user_id": ctx.user_id, "job_id": ctx.job_id, "phase": phase}
        )

    async def _record_source(self, ctx: JobContext, sha: str) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.source_sha256 = sha
            params = dict(job.params or {})
            params["pipeline_version"] = settings.CLIP_PIPELINE_VERSION
            job.params = params
            await session.commit()

    async def _save_clips(self, ctx: JobContext, rows: list[dict]) -> None:
        async with self._session_factory() as session:
            for row in rows:
                session.add(Clip(job_id=ctx.job_uuid, **row))
            await session.commit()

    async def _finish(self, ctx: JobContext) -> None:
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == ctx.job_uuid))).scalar_one()
            job.status = ClipJobStatus.DONE
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
        await self._publish("clip", "done", {"user_id": ctx.user_id, "job_id": ctx.job_id})

    async def _mark_error(self, job_id: str, message: str) -> None:
        job_uuid = uuid.UUID(job_id)
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))).scalar_one_or_none()
            if job is None:
                return
            job.status = ClipJobStatus.ERROR
            job.error = message[:2000]
            job.finished_at = datetime.now(timezone.utc)
            user_id = str(job.user_id)
            await session.commit()
        await self._publish(
            "clip", "error", {"user_id": user_id, "job_id": job_id, "error": message[:500]}
        )

    # ------------------------------------------------------------- pipeline

    async def run(self, job_id: str) -> None:
        try:
            await self._process(job_id)
        except Exception as exc:
            logger.exception("clip pipeline failed for job %s", job_id)
            await self._mark_error(job_id, str(exc))
            raise

    async def _process(self, job_id: str) -> None:
        ctx = await self._load_context(job_id)
        work_dir = Path(settings.CLIP_UPLOAD_DIR) / ctx.user_id
        work_dir.mkdir(parents=True, exist_ok=True)
        audio_path = str(work_dir / f"{ctx.job_id}.wav")
        temp_paths: list[str] = [audio_path]

        local_source, source_is_temp = await resolve_source(
            ctx.source_type, ctx.source_ref, work_dir, ctx.job_id
        )
        if source_is_temp:
            temp_paths.append(local_source)

        try:
            await self._record_source(ctx, sha256_file(local_source))

            # ---- ANALYZING: audio, prefilter, ASR ----
            await self._set_phase(ctx, ClipJobStatus.ANALYZING, "analyzing")
            if not await extract_audio(local_source, audio_path):
                raise RuntimeError("failed to extract audio from the source video")

            regions = detect_hot_regions(
                audio_path,
                min_region_sec=settings.CLIP_PREFILTER_MIN_REGION_SEC,
                max_region_sec=settings.CLIP_PREFILTER_MAX_REGION_SEC,
                max_regions=settings.CLIP_PREFILTER_MAX_REGIONS,
            )
            silences = detect_silences(audio_path)
            transcript = await transcribe_regions(audio_path, regions)
            if not transcript.regions:
                raise RuntimeError("ASR produced no usable speech regions")

            # ---- SCORING ----
            await self._set_phase(ctx, ClipJobStatus.SCORING, "scoring")
            segments = await select_clips(
                transcript,
                top_n=ctx.top_n,
                min_sec=ctx.min_sec,
                max_sec=ctx.max_sec,
                backend=ctx.scoring_backend,
            )
            if not segments:
                raise RuntimeError("no clips were selected from this source")

            # ---- RENDERING ----
            await self._set_phase(ctx, ClipJobStatus.RENDERING, "rendering")
            font_name = resolve_font_name(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)
            rows: list[dict] = []
            for segment in segments:
                rows.append(
                    await self._render_one(
                        ctx, segment, local_source, work_dir, silences, font_name, temp_paths
                    )
                )
            await self._save_clips(ctx, rows)
            await self._finish(ctx)
        finally:
            for path in temp_paths:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    logger.warning("could not remove temp file %s", path)

    async def _render_one(
        self,
        ctx: JobContext,
        segment,
        local_source: str,
        work_dir: Path,
        silences: list[tuple[float, float]],
        font_name: str,
        temp_paths: list[str],
    ) -> dict:
        """Render one clip. Any failure returns an ERROR row instead of raising."""
        base = f"{ctx.job_id}_clip_{segment.rank}"
        raw_path = str(work_dir / f"{base}_raw.mp4")
        ass_path = str(work_dir / f"{base}.ass")
        final_path = str(work_dir / f"{base}.mp4")
        video_url = f"/uploads/clips/{ctx.user_id}/{base}.mp4"
        subtitle_url = f"/uploads/clips/{ctx.user_id}/{base}.ass"

        row = {
            "rank": segment.rank,
            "score": segment.score,
            "hook_text": segment.hook_text,
            "start_sec": segment.start_sec,
            "end_sec": segment.end_sec,
            "clipspec": {},
            "output_ref": None,
            "status": ClipStatus.ERROR,
        }

        try:
            keyframes = await probe_keyframes(local_source, segment.start_sec, segment.end_sec)
            start, end = snap_cut_points(
                segment.start_sec,
                segment.end_sec,
                keyframes,
                silences,
                min_sec=ctx.min_sec,
                max_sec=ctx.max_sec,
            )
            row["start_sec"] = start
            row["end_sec"] = end

            if not await cut_video_stream(local_source, raw_path, start, end):
                raise RuntimeError("ffmpeg stream copy failed")
            temp_paths.append(raw_path)

            crop = await compute_crop_path(raw_path, 0.0, end - start)
            Path(ass_path).write_text(
                build_ass(segment, font_name=font_name), encoding="utf-8"
            )

            if not await burn_vertical(
                raw_path,
                final_path,
                crop=crop,
                ass_path=ass_path,
                font_dir=settings.CLIP_FONT_DIR,
            ):
                raise RuntimeError("ffmpeg subtitle burn failed")

            row["clipspec"] = generate_clipspec(
                segment, video_url=video_url, crop=crop, ass_relative_path=subtitle_url
            )
            row["output_ref"] = final_path
            row["status"] = ClipStatus.READY
            await self._publish(
                "clip",
                "clip_ready",
                {"user_id": ctx.user_id, "job_id": ctx.job_id, "rank": segment.rank},
            )
        except Exception as exc:
            logger.exception("clip %d failed for job %s", segment.rank, ctx.job_id)
            row["clipspec"] = {"version": 2, "error": str(exc)[:500]}
        return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_clip_runner.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Align the router default with the runner**

In `backend/app/routers/clip_jobs.py`, find the `POST /api/clip-jobs` handler signature and change the scoring backend default from the hard-coded `"ollama"` to the setting:

```python
    scoring_backend: str = Form(default=settings.SCORING_BACKEND),
```

Make sure `from app.config import settings` is already imported at the top of the file (it is — it is used for `CLIP_UPLOAD_DIR` and `CLIP_MAX_UPLOAD_BYTES`).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass. If `tests/test_clip_rbac.py` or `tests/test_clip_schemas.py` asserts `"ollama"` anywhere, update that assertion to `settings.SCORING_BACKEND`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/clip_runner.py backend/app/routers/clip_jobs.py backend/tests/test_clip_runner.py
git commit -m "feat(flow-studio): rewire clip runner to the real pipeline with short DB sessions"
```

---

### Task 11: Evaluation harness with golden-set metrics

**Files:**
- Modify: `backend/scripts/eval_pipeline.py` (full rewrite)
- Create: `backend/scripts/golden_set.example.json`

**Interfaces:**
- Consumes: every pipeline stage.
- Produces: a CLI — `python scripts/eval_pipeline.py --video path.mp4 [--golden golden_set.json] [--backend gemini] [--top-n 3]` — printing per-stage seconds, realtime factor, hot-region coverage, and (with a golden file) hot-region recall and mid-word cut rate.

- [ ] **Step 1: Write the golden-set example**

Create `backend/scripts/golden_set.example.json`:

```json
{
  "videos": [
    {
      "path": "samples/vi_podcast_01.mp4",
      "duration_sec": 3600,
      "expected_highlights": [
        {"start_sec": 412.0, "end_sec": 455.0, "note": "punchline about lai suat"},
        {"start_sec": 1890.0, "end_sec": 1935.0, "note": "guest reveals the number"}
      ]
    }
  ]
}
```

- [ ] **Step 2: Rewrite the eval script**

Replace `backend/scripts/eval_pipeline.py` with:

```python
"""Offline evaluation harness for the Flow Studio AI pipeline.

Runs the real pipeline against one video (or a golden set) and reports the
metrics from the design spec: per-stage wall clock, realtime factor, hot-region
coverage, hot-region recall against hand-labelled highlights, and mid-word cut
rate.

    python scripts/eval_pipeline.py --video samples/talk.mp4
    python scripts/eval_pipeline.py --golden scripts/golden_set.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import settings  # noqa: E402
from app.services.ai_pipeline.asr_engine import transcribe_regions  # noqa: E402
from app.services.ai_pipeline.crop import compute_crop_path  # noqa: E402
from app.services.ai_pipeline.cutter import (  # noqa: E402
    cut_video_stream,
    probe_keyframes,
    snap_cut_points,
)
from app.services.ai_pipeline.prefilter import detect_hot_regions, detect_silences  # noqa: E402
from app.services.ai_pipeline.renderer import burn_vertical, resolve_font_name  # noqa: E402
from app.services.ai_pipeline.scorer import select_clips  # noqa: E402
from app.services.ai_pipeline.subtitle_gen import build_ass, generate_clipspec  # noqa: E402
from app.services.ai_pipeline.vad_filter import extract_audio, probe_duration  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval")


def hot_region_recall(regions, expected: list[dict]) -> float:
    """Fraction of hand-labelled highlights that a hot region overlaps at all."""
    if not expected:
        return float("nan")
    hits = 0
    for item in expected:
        lo, hi = float(item["start_sec"]), float(item["end_sec"])
        if any(r.start_sec < hi and r.end_sec > lo for r in regions):
            hits += 1
    return hits / len(expected)


def mid_word_cut_rate(cuts: list[tuple[float, float]], words) -> float:
    """Fraction of cut boundaries that land strictly inside a spoken word."""
    boundaries = [t for cut in cuts for t in cut]
    if not boundaries:
        return float("nan")
    bad = sum(1 for t in boundaries if any(w.start < t < w.end for w in words))
    return bad / len(boundaries)


async def evaluate(video_path: str, *, top_n: int, backend: str, expected: list[dict]) -> dict:
    out_dir = Path("eval_out") / Path(video_path).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(out_dir / "audio.wav")
    timings: dict[str, float] = {}

    duration = await probe_duration(video_path)
    logger.info("source duration: %.1fs", duration)

    t0 = time.time()
    if not await extract_audio(video_path, audio_path):
        raise SystemExit(f"audio extraction failed for {video_path}")
    timings["extract"] = time.time() - t0

    t0 = time.time()
    regions = detect_hot_regions(
        audio_path,
        min_region_sec=settings.CLIP_PREFILTER_MIN_REGION_SEC,
        max_region_sec=settings.CLIP_PREFILTER_MAX_REGION_SEC,
        max_regions=settings.CLIP_PREFILTER_MAX_REGIONS,
    )
    silences = detect_silences(audio_path)
    timings["prefilter"] = time.time() - t0
    covered = sum(r.duration for r in regions)

    t0 = time.time()
    transcript = await transcribe_regions(audio_path, regions)
    timings["asr"] = time.time() - t0

    t0 = time.time()
    segments = await select_clips(
        transcript, top_n=top_n, min_sec=30, max_sec=60, backend=backend
    )
    timings["scoring"] = time.time() - t0

    font_name = resolve_font_name(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)
    cuts: list[tuple[float, float]] = []
    t0 = time.time()
    for segment in segments:
        base = out_dir / f"clip_{segment.rank}"
        keyframes = await probe_keyframes(video_path, segment.start_sec, segment.end_sec)
        start, end = snap_cut_points(
            segment.start_sec, segment.end_sec, keyframes, silences, min_sec=30, max_sec=60
        )
        cuts.append((start, end))
        raw = f"{base}_raw.mp4"
        if not await cut_video_stream(video_path, raw, start, end):
            logger.error("cut failed for clip %d", segment.rank)
            continue
        crop = await compute_crop_path(raw, 0.0, end - start)
        ass_path = f"{base}.ass"
        Path(ass_path).write_text(build_ass(segment, font_name=font_name), encoding="utf-8")
        final = f"{base}.mp4"
        if not await burn_vertical(
            raw, final, crop=crop, ass_path=ass_path, font_dir=settings.CLIP_FONT_DIR
        ):
            logger.error("burn failed for clip %d", segment.rank)
            continue
        spec = generate_clipspec(
            segment, video_url=final, crop=crop, ass_relative_path=ass_path
        )
        Path(f"{base}_spec.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    timings["render"] = time.time() - t0

    Path(audio_path).unlink(missing_ok=True)
    total = sum(timings.values())
    return {
        "video": video_path,
        "duration_sec": round(duration, 1),
        "timings_sec": {k: round(v, 2) for k, v in timings.items()},
        "total_sec": round(total, 2),
        "realtime_factor": round(total / duration, 3) if duration else None,
        "hot_region_count": len(regions),
        "hot_region_coverage": round(covered / duration, 3) if duration else None,
        "hot_region_recall": hot_region_recall(regions, expected),
        "clips_selected": len(segments),
        "mid_word_cut_rate": mid_word_cut_rate(cuts, transcript.all_words),
        "language": transcript.language,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Flow Studio AI pipeline evaluation")
    parser.add_argument("--video", help="single video to evaluate")
    parser.add_argument("--golden", help="golden set JSON (see golden_set.example.json)")
    parser.add_argument("--backend", default=settings.SCORING_BACKEND)
    parser.add_argument("--top-n", type=int, default=3)
    args = parser.parse_args()

    jobs: list[tuple[str, list[dict]]] = []
    if args.golden:
        data = json.loads(Path(args.golden).read_text(encoding="utf-8"))
        jobs = [(v["path"], v.get("expected_highlights", [])) for v in data["videos"]]
    elif args.video:
        jobs = [(args.video, [])]
    else:
        parser.error("pass --video or --golden")

    results = []
    for path, expected in jobs:
        if not Path(path).is_file():
            logger.error("missing video: %s", path)
            continue
        results.append(await evaluate(path, top_n=args.top_n, backend=args.backend, expected=expected))

    print(json.dumps(results, ensure_ascii=False, indent=2))
    Path("eval_out/summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Verify the script parses and its help works**

Run: `cd backend && python scripts/eval_pipeline.py --help`
Expected: usage text listing `--video`, `--golden`, `--backend`, `--top-n`. No import errors.

- [ ] **Step 4: Run the full suite one last time**

Run: `cd backend && python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/eval_pipeline.py backend/scripts/golden_set.example.json
git commit -m "feat(flow-studio): eval harness with recall, coverage and mid-word-cut metrics"
```

- [ ] **Step 6: Manual end-to-end smoke test (integration, requires ffmpeg + a real key)**

With `ffmpeg` on PATH, `GEMINI_API_KEY` set, and a real video at `backend/test_video.mp4`:

```bash
cd backend && python scripts/eval_pipeline.py --video test_video.mp4 --top-n 1
```

Verify in `eval_out/test_video/`:
- `clip_1.mp4` exists, is 1080×1920, and has burned Vietnamese subtitles with correct diacritics (`ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 eval_out/test_video/clip_1.mp4` prints `1080,1920`)
- `clip_1_spec.json` has `"version": 2`, a non-empty `cues` array, and a `crop` block
- the printed `realtime_factor` is recorded in the PR description as the CPU baseline

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-07-24-flow-studio-long-to-short-web-design.md`)

| Spec section | Covered by |
|---|---|
| §3 pipeline / data flow | Task 10 (`ClipRunner._process` implements the exact stage order) |
| §4 tier-1 prefilter (energy → hot regions) | Task 2 |
| §4 tier-2 heuristic | Task 5 (`heuristic_select`) |
| §4 tier-3 LLM rubric | Task 5 (`build_prompt`, `select_clips`) |
| §5 pluggable scoring engines | Task 4 (`SUPPORTED_BACKENDS`, `query_llm`) + `SCORING_BACKEND` setting |
| §6 CPU ASR | Task 3 (faster-whisper int8, region-scoped) |
| §7 stream-copy cut, keyframe ∩ silence snap | Task 6 |
| §7 9:16 crop, face track, smoothing | Task 7 |
| §7 re-encode only for subtitle burn | Task 8 (`renderer.burn_vertical` is the only libx264 pass) |
| §8 OpenCut clipspec contract | Task 8 (`generate_clipspec` v2 with `crop.path` + `cues`) |
| §9 data model | Unchanged — reuses existing `ClipJob`/`Clip`; `pipeline_version` rides in `params` JSONB per Global Constraints |
| §10 REST + SSE | Task 10 (phase/clip_ready/done/error events; router default fixed) |
| §12 error handling | Task 10 (`_mark_error`, per-clip isolation), Task 3 (per-region isolation), Task 5 (LLM fallback), Task 9 (`SourceUnavailable`) |
| §13 test/eval metrics | Task 11 (recall, coverage, mid-word cut rate, realtime factor) |
| §15 build order items 3–7 | Tasks 2, 3, 5, 6, 8 in that order |

Explicit gaps, stated rather than silently dropped: **ASR tier-2 "cloud" backend** (`ASR_BACKEND` setting exists and is read, but only `local` is implemented — a cloud provider was never named in the spec); **clipspec round-trip metric** (needs the OpenCut editor, which is out of scope here); **`subtitle breakage` metric** (requires visual inspection — Task 11 Step 6 covers it manually); **result caching by `source_sha256` + `model_version`** — the runner now *writes* both (Task 10 Step 3, `_record_source`), so a later cache-read task is a pure query addition with no migration, but the read path is not implemented here.

**2. Placeholder scan** — no "TBD", no "add appropriate error handling", no "similar to Task N". Every code step contains complete runnable code, with concrete expected values (e.g. `crop_w == 608` for a 1920×1080 source) rather than "whatever the implementation returns".

**3. Type consistency**

- `Word.to_dict()` emits key `"word"` (Task 1) and `generate_clipspec` re-emits `"word"` (Task 8) — matches the existing frontend contract.
- `HotRegion.index` set by `detect_hot_regions` (Task 2) → keyed by `by_index` in the scorer (Task 5) → echoed as `region_index` on `ScoredSegment` — consistent throughout.
- `select_clips` (Task 5) is called with exactly `(transcript, top_n=, min_sec=, max_sec=, backend=)` in Task 10 and Task 11.
- `snap_cut_points` takes `min_sec`/`max_sec` keyword-only in Task 6 and is called that way in Tasks 10 and 11.
- The crop dict keys `crop_w`/`crop_h`/`x`/`y` produced by `compute_crop` (Task 7) are consumed verbatim by `build_render_command` (Task 8) and asserted in both test modules.
- `resolve_font_name(font_dir, preferred)` (Task 8) is called positionally with `(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)` in Tasks 10 and 11.
- `score_and_translate_clips` (v0) is deleted in Task 5 and has exactly two call sites, both rewritten: `clip_runner.py` (Task 10) and `scripts/eval_pipeline.py` (Task 11).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-28-flow-studio-ai-pipeline.md`.
