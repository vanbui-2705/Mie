# Deployment Module

## Scope

Owns container topology, build contexts, reverse proxies, TLS examples,
persistent volumes and production deployment instructions.

## Current source

- `docker-compose.yml`
- `docker-compose.prod.yml`
- Backend and frontend Dockerfiles.
- `deploy/nginx/`
- `deploy/caddy/`
- Deployment documents under `docs/`.

## Runtime services

- PostgreSQL and Redis.
- Migration job.
- Main API and worker.
- Flow API and worker.
- Browser worker and browser provider.
- Frontend.
- Reverse proxy in production.

## Persistent data

- PostgreSQL data.
- Redis data where configured.
- Backend uploads and generated clips.
- Backend logs.
- Browser profiles.
- Cached Flow AI models.

## Invariants

- Existing volume names are data contracts.
- Public ports and callback URLs remain explicit.
- Secrets come from environment or secret storage, not committed files.
- Health checks target the service's real health endpoint.
- Reverse proxies preserve SSE and byte-range streaming.
- TLS examples never contain private production keys.

## Debugging

Run Compose configuration validation, inspect service health, then check
dependency readiness and container logs. For media playback verify proxy range
headers. For live progress verify proxy buffering is disabled for SSE.

## Checks

- `docker compose config`
- Image builds for affected services.
- `/api/health` on main and Flow APIs.
- Frontend route smoke test.

