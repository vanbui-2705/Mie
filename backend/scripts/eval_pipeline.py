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
    Path("eval_out").mkdir(parents=True, exist_ok=True)
    Path("eval_out/summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
