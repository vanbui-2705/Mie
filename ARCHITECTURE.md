# FlowMeta Architecture

## Purpose

FlowMeta is a monorepo containing several user interfaces and runtime processes
that share a backend, PostgreSQL, Redis, browser automation, and deployment
configuration. The repository is organized logically by functional module even
where the current source files still live in layer-based folders.

This document is the starting point for architecture discovery. Before changing
a feature, locate its module in
[`docs/architecture/MODULES.md`](docs/architecture/MODULES.md) and read that
module's `ARCHITECTURE.md`.

## Runtime map

| Runtime | Current entry point | Responsibility |
|---|---|---|
| Main API | `backend/app/main.py` | Authentication, accounts, automation, rental, Sheets, proxy and management APIs |
| Main worker | `backend/app/worker.py` | General automation jobs |
| Flow API | `backend/app/flow_app.py` | Flow Studio jobs, clips, streaming and SSE |
| Flow worker | `backend/app/flow_worker.py` | Reup, Gen, rendering and retention |
| Browser worker | `backend/app/browser_worker.py` | Browser-based Facebook operations |
| Web console | `frontend/src/app` | Main browser UI |
| Desktop | Root C# project | Windows desktop client |
| Browser extension | `extension/` | User-browser connector |
| Guide site | `guide-site/` | User documentation website |

## Shared infrastructure

- PostgreSQL stores users, accounts, tasks, campaigns, rooms and clip jobs.
- Redis carries job queues, events and cross-process progress.
- Docker Compose defines runtime topology and persistent volumes.
- Nginx or Caddy fronts the APIs, uploads and web console.
- Browserless or a remote browser provides automated browser sessions.

## Dependency direction

The intended dependency direction is:

`entrypoints → functional modules → platform services`

Rules:

- HTTP routers must delegate work instead of implementing business workflows.
- Workers orchestrate jobs but algorithms stay in their owning module.
- Functional modules may use platform services such as database, Redis, events,
  storage and subprocess execution.
- Platform services must not import feature routers.
- Cross-module calls should use an explicit service, contract or event.
- Public API paths, database schemas, queue names and volume paths are stable
  contracts unless a migration is explicitly approved.

## Source organization status

The current repository is not being physically moved by this architecture
layer. Module documentation maps current files to clear ownership without
changing runtime imports or behavior. Physical moves can be performed later in
small, separately tested phases.

## Agent reading order

1. Read the nearest `AGENTS.md`.
2. Read this file.
3. Find the task in `docs/architecture/MODULES.md`.
4. Read the owning module's `ARCHITECTURE.md`.
5. Read the listed entrypoints and tests before implementation files.
6. Do not modify adjacent modules unless the dependency impact is documented.

## Global invariants

- Secrets remain outside Git.
- User uploads and browser profiles remain in persistent runtime storage.
- Workers must be restart-safe and jobs must expose useful failure state.
- Generated media must remain scoped to the owning user and job.
- Prompt text contains task logic and flow direction, not executable code.
- Every behavior change requires tests proportional to its risk.

