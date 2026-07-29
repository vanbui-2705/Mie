# Flow Studio page redesign — design

Date: 2026-07-29
Status: approved (section 1 approved explicitly; remaining sections approved by "ổn rồi thực hiện đi")

## Problem

`frontend/src/app/flow-studio/page.tsx` is a mock: both API calls are commented out and the
result gallery renders a hardcoded clip. The real pipeline (Flow API on `:8001`, worker, Postgres,
Redis) works end to end and is proven by `backend/scripts/eval_pipeline.py`, but no UI reaches it.

Four concrete gaps block wiring:

1. `ClipOut` has no `clipspec`, so `ClipPlayer` cannot render karaoke words.
2. `clipspec.video_url` points at `/uploads/clips/...` which no app mounts, and
   `GET /api/clips/{id}/download` authenticates with a header that `<video src>` cannot send.
3. `ProgressTracker` opens a relative SSE URL with the wrong query parameter and no token.
4. The frontend has one `API_BASE` (Face, `:8000`); Flow lives on `:8001`.

## Scope

In scope: page redesign with a mode menu, real Reup/Edit flow, job history, settings, and a
Gen-video form whose submit is a local payload preview. Out of scope: the video generation
engine itself, clip editing (OpenCut), cancel/delete.

## Decisions

| Question | Decision |
| --- | --- |
| Gen engine | Not chosen. UI only this round; a later spec picks the engine. |
| Mode menu | Vertical sub-sidebar inside the page: Reup/Edit, Gen video, History, Settings. |
| History | Real list endpoint `GET /api/clip-jobs`, click a job to reopen its clips. |
| Video playback | `GET /api/clips/{id}/stream?token=...` with RBAC + owner check + HTTP Range. |
| Gen form fields | Prompt + negative prompt, duration/aspect/variants, voice + subtitle language, reference image. |
| Gen submit | Validate, then show the JSON payload. No backend call. |
| Reup parameters | All of them live in the Settings panel, persisted in localStorage. |
| Flow transport | New `NEXT_PUBLIC_FLOW_API_URL`, a `flowFetch` sibling of `apiFetch`. |

## Architecture

One route, `/flow-studio`. The active mode lives in the URL as `?tab=reup|gen|history|settings`
so reload and shared links land on the same panel. SideNav gains a `Flow Studio` entry gated on
`clip:create`.

```
src/app/flow-studio/page.tsx      reads ?tab, renders shell + active panel
src/components/flow-studio/
  FlowSidebar.tsx                 four-item vertical menu
  ReupPanel.tsx                   source (file | link) + submit
  GenPanel.tsx                    prompt form, submit renders payload
  HistoryPanel.tsx                job list, click to reopen
  SettingsPanel.tsx               pipeline parameters, localStorage
  JobProgress.tsx                 replaces ProgressTracker, uses useSSE
  ResultGallery.tsx               kept, video source now the stream endpoint
  ClipPlayer.tsx                  kept, spec is real clipspec v2
  useFlowSettings.ts              read/write parameters
```

Each panel owns its own API calls. `page.tsx` holds only `activeJobId`, the one piece of state
shared between panels (Reup hands off to progress; History sets it when a job is reopened).

## Backend changes

All three land in `app/routers/clip_jobs.py`, mounted only on `flow_app`.

**1. `clipspec` on `ClipOut`.** Add `clipspec: dict | None` to the schema and pass `c.clipspec`
in `get_clip_job`. The column already exists and the worker already writes clipspec v2.

**2. `GET /api/clip-jobs`.** Permission `clip:read`, own rows only, newest first, `limit`
(default 20, max 100) and `offset`. Returns `ClipJobSummary`: `id`, `status`, `source_type`,
`source_ref` basename, `created_at`, `finished_at`, `clip_count`, `error`. A summary, not the
full `ClipJobOut` — the list must not carry every clipspec.

**3. `GET /api/clips/{clip_id}/stream`.** Authenticates from `?token=` because a `<video>` tag
cannot set headers; SSE already uses that pattern. Checks `clip:read` and job ownership, then
serves `clip.output_ref` with `Accept-Ranges: bytes`, honouring a single `bytes=start-end`
range with `206 Partial Content`; a missing or unparseable Range yields the whole file as `200`.
Starlette 0.37.2's `FileResponse` does not implement Range, so the handler builds the response.

Token-in-query auth is a deliberate, narrow exception: a new `current_user_media` dependency in
`app/auth.py` reads the header first and falls back to the query parameter. The existing
`current_user` keeps rejecting query tokens, so no other endpoint widens.

## Data flow

Reup submit → `POST /api/clip-jobs` (multipart: `file` or `source_link`, plus settings) →
`{job_id}` → `page.tsx` sets `activeJobId` → `JobProgress` subscribes to
`GET /api/events/stream?channels=clip&token=...` on the Flow origin. The worker publishes
`phase`, `clip_ready`, `done`, and `error`, each carrying `job_id`; the component ignores events
for other jobs. On `done` it fetches `GET /api/clip-jobs/{id}` and renders `ResultGallery`.
`ClipPlayer` plays `${FLOW_BASE}/api/clips/${clip.id}/stream?token=...`.

History reopens a job through the same `GET /api/clip-jobs/{id}` path, so a finished job renders
identically whether it just completed or is being revisited.

## Error handling

- No token: `apiFetch` already redirects to `/login`; `flowFetch` reuses that behaviour.
- Flow API down: panels show "Flow API không phản hồi" with a retry button. The page must not
  blank out — Face-side navigation stays usable.
- SSE drop: `useSSE` reconnects with backoff. Because a reconnect can miss the terminal event,
  `JobProgress` also polls `GET /api/clip-jobs/{id}` every 15s while a job is active, and stops
  on `DONE`/`ERROR`.
- Job in `ERROR`: show `job.error` verbatim in a red panel; keep the form enabled for a retry.
- Clip with `status != READY` or no `output_ref`: render a placeholder card, not a broken player.
- Upload over `CLIP_MAX_UPLOAD_BYTES` (4 GB): the client checks `file.size` first; the server
  still returns 413 and the client surfaces that message.
- Bad link: server returns 400 from `sanitize_link`; show the detail under the input.

## Testing

Backend (pytest, existing style):
- `GET /api/clip-jobs` returns only the caller's jobs, newest first, and respects `limit`.
- `get_clip_job` includes `clipspec`.
- Stream: valid token + owner returns 200 with `Accept-Ranges`; `Range: bytes=0-9` returns 206
  with a 10-byte body and a correct `Content-Range`; another user's clip returns 404; a missing
  or invalid token returns 401; a clip with no `output_ref` returns 409.
- Route registration test in `test_flow_app.py` extended with the new paths.

Frontend: `npm run lint` and `npx tsc --noEmit`, plus a manual pass — upload a short mp4, watch
the phases advance, play the finished clip, reload into History and reopen it.

## Risks

- Token in a query string can land in access logs. Accepted for media and SSE only; the token is
  short-lived and the endpoint is read-only.
- The Gen panel ships without an engine, so a user may expect it to work. The submit button
  renders the payload under a "Chưa bật engine" badge to make the state obvious.
