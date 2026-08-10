# Facebook Module

## Scope

Owns Facebook account connections, OAuth token exchange and Graph API
operations. Browser-driven Facebook actions belong to the Browser module.

## Responsibilities

- Facebook OAuth account connection.
- User and Page token exchange.
- Page discovery and account metadata.
- Graph API comment/post operations.
- Token health and permission checks.

## Current source

- Module boundary: `backend/app/modules/facebook/`
- `backend/app/routers/facebook_accounts.py`
- `backend/app/routers/facebook_oauth.py`
- `backend/app/routers/graph.py`
- `backend/app/services/facebook_graph.py`
- Facebook account models in `backend/app/models/sqlmodels.py`
- Account UI in `frontend/src/app/accounts/`

## Dependencies

- Identity and access for the owning user.
- Platform database and HTTP configuration.
- Automation for jobs that invoke Facebook operations.
- Browser execution when Graph API cannot complete an action.

## Invariants

- Access tokens are never returned unnecessarily or written to logs.
- Page operations use the correct Page token and owning account.
- Graph failures preserve the provider error without exposing secrets.
- Browser fallback must not duplicate a Graph operation that already succeeded.

## Debugging

Classify failures into authentication, missing permission, wrong object ID,
provider rate limit, expired token or browser fallback. Record Graph endpoint,
HTTP status and redacted provider message.

## Tests

Facebook account, Graph and task integration tests under `backend/tests/`.
