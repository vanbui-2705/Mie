# Flow Video Module

## Scope

Owns Flow Studio Reup and Gen jobs from request creation through media
publication, progress events, retention and download.

## Responsibilities

- Link and upload source validation.
- Job creation, queueing, heartbeat, cancellation and retention.
- Reup audio extraction, prefilter, ASR, AI scoring and vertical rendering.
- Gen script writing, TTS, stock imagery, slideshow and subtitles.
- Product-image Gen: validated multi-image upload, ordered scene allocation and
  animated pan/zoom sales-video rendering.
- Range-capable clip streaming.
- User-editable AI direction.

## Runtime entrypoints

- Module boundary: `backend/app/modules/flow_video/`
- API: `backend/app/flow_app.py`
- Worker: `backend/app/flow_worker.py`
- Router: `backend/app/routers/clip_jobs.py`
- Reup orchestrator: `backend/app/services/clip_runner.py`
- Gen orchestrator: `backend/app/services/gen_runner.py`

## Pipeline source

- Shared algorithms: `backend/app/services/ai_pipeline/`
- Queue: `backend/app/services/clip_queue.py`
- Retention: `backend/app/services/clip_retention.py`
- Storage: `backend/app/services/clip_storage.py`
- Models: `backend/app/models/clip_models.py`
- Migration: `backend/alembic/versions/20260729_0009_clip_retention.py`
- UI: `frontend/src/components/flow-studio/`
- API client: `frontend/src/lib/flow-api.ts`

## Reup flow

1. Validate source and editing parameters.
2. Download or resolve the source.
3. Extract mono audio.
4. Select capped candidate regions.
5. Transcribe candidates with local Whisper.
6. Score segments and write Vietnamese copy.
7. Cut at safe boundaries.
8. Crop, subtitle, optionally voice over and render.
9. Store clip metadata and publish progress.

## Gen flow

1. Convert the user's direction into a timed scene script.
2. Synthesize narration per scene.
3. Build the visual timeline from real audio duration.
4. Resolve Pexels, Wikimedia or generated fallback backdrops.
5. Build subtitles and hook text.
6. Render the vertical slideshow with audio.
7. Store the clip and publish completion.

When product images are uploaded, they replace stock backdrops and are assigned
in upload order. The script requests at least as many scenes as uploaded images,
up to the 12-scene safety cap.

Videos currently render as one bounded job of 5–120 seconds. Long-form Gen
should use a segment plan, render retryable short segments independently, then
stream-copy compatible segments into one final MP4.

## Dependencies

- Platform database, Redis, events, storage and subprocess management.
- Gemini or another configured LLM.
- Faster Whisper local ASR.
- FFmpeg and yt-dlp.
- Edge TTS and stock-image providers.

## Invariants

- A job and every output belongs to one user.
- Jobs, clips, edits and media expire together one day after their last
  heartbeat; active work is cancelled before cleanup.
- AI direction cannot override timestamps, duration, factual fidelity or output
  format.
- Prompt content contains logic and editing direction, not executable code.
- Candidate regions remain capped after overlap handling.
- Cancellation terminates live subprocesses.
- Missing optional media providers degrade visibly instead of producing a
  silent false success.
- Streaming supports byte ranges for browser playback.

## Debugging

Trace one job ID through status, worker logs and output files. For slow Reup,
inspect source duration, selected region count, total ASR seconds, model and CPU
use. For black Gen output, inspect each scene's `visual_source`. For render
failure, capture the final FFmpeg stderr and input durations.

## Tests

- `backend/tests/test_clip_endpoints.py`
- `backend/tests/test_clip_runner.py`
- `backend/tests/test_prefilter.py`
- `backend/tests/test_scorer.py`
- `backend/tests/test_renderer.py`
- `backend/tests/test_gen_pipeline.py`
- `backend/tests/test_tts_engine.py`
- `backend/tests/test_clip_retention.py`
