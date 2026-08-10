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
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Running `python scripts/eval_pipeline.py` puts scripts/ on sys.path, not the
# backend root, so `app` would not import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

load_dotenv()

from app.config import settings  # noqa: E402
from app.services.ai_pipeline.asr_engine import transcribe_regions  # noqa: E402
from app.services.ai_pipeline.crop import compute_crop_path  # noqa: E402
from app.services.ai_pipeline.cutter import (  # noqa: E402
    cut_video_stream,
    probe_keyframes,
    resegment,
    snap_cut_points,
)
from app.services.ai_pipeline.prefilter import detect_hot_regions, detect_silences  # noqa: E402
from app.services.ai_pipeline.renderer import burn_vertical, resolve_font_name  # noqa: E402
from app.services.ai_pipeline.scorer import select_clips  # noqa: E402
from app.services.ai_pipeline.source import sha256_file  # noqa: E402
from app.services.ai_pipeline.subtitle_gen import build_ass, generate_clipspec  # noqa: E402
from app.services.ai_pipeline.types import (  # noqa: E402
    HotRegion,
    RegionTranscript,
    Transcript,
    Word,
)
from app.services.ai_pipeline.vad_filter import extract_audio, probe_duration  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eval")


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


def hot_region_recall(regions, expected: list[dict]) -> float | None:
    """Fraction of hand-labelled highlights that a hot region overlaps at all.

    `None`, not NaN, when there is nothing to measure: json.dumps emits a bare
    `NaN` token that strict JSON parsers reject, and summary.json is meant to be
    machine-readable.
    """
    if not expected:
        return None
    hits = 0
    for item in expected:
        lo, hi = float(item["start_sec"]), float(item["end_sec"])
        if any(r.start_sec < hi and r.end_sec > lo for r in regions):
            hits += 1
    return hits / len(expected)


MID_WORD_TOLERANCE_SEC = 0.15


def mid_word_cut_rate(cuts: list[tuple[float, float]], words) -> float | None:
    """Fraction of cut boundaries that land deep inside a spoken word.

    "Strictly inside a word" alone is useless: faster-whisper emits contiguous
    word spans (measured 100/104 adjacent pairs with a zero gap), so every cut
    that falls in speech is inside some word and the metric pins at 1.0. What
    actually audibly clips a word is a boundary far from either edge, so measure
    the distance to the nearest edge of the word the boundary lands in.
    """
    boundaries = [t for cut in cuts for t in cut]
    if not boundaries:
        return None
    bad = 0
    for t in boundaries:
        inside = [w for w in words if w.start < t < w.end]
        if not inside:
            continue
        word = min(inside, key=lambda w: min(t - w.start, w.end - t))
        if min(t - word.start, word.end - t) > MID_WORD_TOLERANCE_SEC:
            bad += 1
    return bad / len(boundaries)


def dump_transcript(transcript: Transcript, path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "language": transcript.language,
                "regions": [
                    {
                        "region": {
                            "index": rt.region.index,
                            "start_sec": rt.region.start_sec,
                            "end_sec": rt.region.end_sec,
                            "energy": rt.region.energy,
                        },
                        "text": rt.text,
                        "words": [{"start": w.start, "end": w.end, "text": w.text} for w in rt.words],
                    }
                    for rt in transcript.regions
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def load_transcript(path: Path) -> Transcript:
    """Reload a dumped transcript so scoring/render can be iterated without ASR.

    ASR is ~85% of the wall clock, so re-running it to test a prompt change costs
    minutes per attempt.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Transcript(
        language=raw["language"],
        regions=tuple(
            RegionTranscript(
                region=HotRegion(**r["region"]),
                text=r["text"],
                words=tuple(Word(**w) for w in r["words"]),
            )
            for r in raw["regions"]
        ),
    )


async def evaluate(
    video_path: str, *, top_n: int, backend: str, expected: list[dict], reuse_transcript: bool = False
) -> dict:
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

    cache_path = out_dir / "transcript.json"
    t0 = time.time()
    if reuse_transcript and cache_path.is_file():
        transcript = load_transcript(cache_path)
        logger.info("reusing cached transcript %s (ASR skipped)", cache_path)
    else:
        transcript = await transcribe_regions(audio_path, regions)
        dump_transcript(transcript, cache_path)
    timings["asr"] = time.time() - t0

    t0 = time.time()
    segments = await select_clips(
        transcript, top_n=top_n, min_sec=30, max_sec=60, backend=backend
    )
    timings["scoring"] = time.time() - t0

    font_name = resolve_font_name(settings.CLIP_FONT_DIR, settings.CLIP_SUBTITLE_FONT)
    cuts: list[tuple[float, float]] = []
    # The equality gate compares these three fields, so they are recorded before
    # the encode: a render that fails is a render bug, not a behaviour change.
    clips: list[dict] = []
    t0 = time.time()
    for segment in segments:
        base = out_dir / f"clip_{segment.rank}"
        keyframes = await probe_keyframes(video_path, segment.start_sec, segment.end_sec)
        start, end = snap_cut_points(
            segment.start_sec, segment.end_sec, keyframes, silences, min_sec=30, max_sec=60
        )
        cuts.append((start, end))
        segment = resegment(segment, start, end)
        clips.append(
            {
                "rank": segment.rank,
                "start_sec": segment.start_sec,
                "end_sec": segment.end_sec,
                "subtitle_text": segment.subtitle_text,
            }
        )
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
    metrics = {
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
    report_path = write_report(
        Path("eval_out"),
        source_path=video_path,
        source_sha=sha256_file(video_path),
        stages={name: round(seconds, 3) for name, seconds in timings.items()},
        clips=clips,
        metrics=metrics,
    )
    print(f"report: {report_path}")
    return metrics


async def main() -> None:
    parser = argparse.ArgumentParser(description="Flow Studio AI pipeline evaluation")
    parser.add_argument("--video", help="single video to evaluate")
    parser.add_argument("--golden", help="golden set JSON (see golden_set.example.json)")
    parser.add_argument("--backend", default=settings.SCORING_BACKEND)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument(
        "--reuse-transcript",
        action="store_true",
        help="skip ASR when eval_out/<video>/transcript.json exists (prompt iteration)",
    )
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
        results.append(
            await evaluate(
                path,
                top_n=args.top_n,
                backend=args.backend,
                expected=expected,
                reuse_transcript=args.reuse_transcript,
            )
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    Path("eval_out").mkdir(parents=True, exist_ok=True)
    Path("eval_out/summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
