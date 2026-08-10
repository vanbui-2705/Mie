# Identity and Access Module

## Scope

Owns authentication, OAuth login, users, roles, permissions and access tokens.

## Responsibilities

- Username/password authentication.
- Google and Facebook OAuth callbacks.
- Token creation, parsing and expiry.
- Password reset.
- User status, role and permission enforcement.
- Default-user compatibility behavior.

## Current source

- Module boundary: `backend/app/modules/identity_access/`
- `backend/app/auth.py`
- `backend/app/auth_oauth.py`
- `backend/app/rbac.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/auth_oauth.py`
- `backend/app/routers/roles.py`
- `backend/app/services/permission_service.py`
- Identity models in `backend/app/models/sqlmodels.py`
- Frontend auth state in `frontend/src/lib/auth-context.tsx`

## Public surface

- Authentication and OAuth HTTP routes.
- Bearer token dependency used by protected routers.
- Permission lookup used by API authorization.

## Dependencies

- Platform database and configuration.
- External OAuth providers.
- Web console callback routes.

## Invariants

- Secret values and OAuth credentials never enter logs or Git.
- Disabled users cannot obtain privileged access.
- Authorization is enforced server-side, not only hidden in the UI.
- OAuth redirect URLs must match configured public URLs.

## Debugging

For 401 errors, identify whether the failure is missing token, invalid
signature, expiry, disabled user or missing permission. For OAuth failures,
compare provider redirect URI, backend callback route and frontend callback
URL.

## Tests

Authentication, RBAC and protected endpoint tests under `backend/tests/`.
