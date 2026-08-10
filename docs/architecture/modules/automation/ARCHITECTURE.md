# Automation Module

## Scope

Owns comment, post, share and scheduled automation workflows, including job
creation, queueing, execution state and publication retries.

## Responsibilities

- Comment task creation and input expansion.
- Page, timeline and group publication jobs.
- Scheduled posts and due-job enqueueing.
- Task queue lifecycle, cancellation and logs.
- Extension and browser fallback coordination.
- Retry policy and publication status.

## Current source

- Module boundary: `backend/app/modules/automation/`
- `backend/app/routers/comment_tasks.py`
- `backend/app/routers/page_tasks.py`
- `backend/app/routers/scheduled_posts.py`
- `backend/app/routers/tasks.py`
- `backend/app/services/task_queue.py`
- `backend/app/services/task_runner.py`
- `backend/app/services/publication_jobs.py`
- `backend/app/services/scheduled_post_service.py`
- `backend/app/worker.py`
- Automation pages under `frontend/src/app/auto-*` and `scheduled-posts/`

## Dependencies

- Facebook for Graph operations.
- Browser execution and extension connector for interactive actions.
- Proxy and profiles for isolated accounts.
- Platform database, Redis queues and events.

## Invariants

- A queued item is claimed atomically.
- Cancellation is observable by long-running operations.
- Retries do not duplicate a confirmed publication.
- Task status and logs remain scoped to the owning user.
- Input delays and concurrency limits are enforced by the worker.

## Debugging

Trace one task ID from API creation to Redis queue, worker claim, selected
execution backend and final publication state. Check account locks and
extension presence before treating a queued job as stuck.

## Tests

- `backend/tests/test_phase5_task_runner_accounts.py`
- Scheduled post, page-task and publication tests under `backend/tests/`.
