# Platform Module

## Scope

Provides shared runtime foundations used by every backend feature. It does not
own user-facing business workflows.

## Responsibilities

- Application configuration and environment parsing.
- PostgreSQL sessions and model registration.
- Redis connections, queues and event relay.
- Server-sent event publication.
- Shared authentication primitives.
- Safe subprocess lifecycle and persistent upload storage.
- Health checks and application startup/shutdown behavior.

## Current source

- Module boundary: `backend/app/modules/platform/`
- `backend/app/config.py`
- `backend/app/db/`
- `backend/app/event_bus.py`
- `backend/app/sse.py`
- `backend/app/services/ai_pipeline/procs.py`
- `backend/app/services/clip_storage.py`
- `backend/app/routers/health.py`
- `backend/alembic/`

## Runtime entrypoints

- `backend/app/main.py`
- `backend/app/flow_app.py`
- `backend/app/worker.py`
- `backend/app/flow_worker.py`
- `backend/app/browser_worker.py`

## Owned contracts

- Database and Redis connection lifecycle.
- Event channel delivery across processes.
- Upload root and user-scoped storage rules.
- Health response used by Compose and peer services.

## Invariants

- Database sessions are closed after use.
- Redis or event relay failures must not silently corrupt job state.
- File paths must remain inside configured storage roots.
- Subprocess cancellation must terminate tracked FFmpeg and downloader children.
- Platform code must not import feature routers.

## Debugging

Start with `/api/health`, container health, PostgreSQL, Redis, then the relevant
worker log. For missing progress, inspect the Redis event relay and SSE
connection before changing feature logic.

## Tests

- `backend/tests/test_event_bus_relay.py`
- `backend/tests/test_clip_storage.py`
- Health and lifecycle coverage in endpoint tests.
