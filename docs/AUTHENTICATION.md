# FlowMeta Authentication

FlowMeta supports normal account authentication and quick sign-in with Google or Facebook.

## Routes

- `POST /api/auth/register`
- `POST /api/auth/login` (username or email)
- `POST /api/auth/forgot-password`
- `POST /api/auth/reset-password`
- `GET /api/auth/oauth/google/start`
- `GET /api/auth/oauth/facebook/start`

OAuth uses the server-side authorization-code flow. Callback requests validate a signed, ten-minute `state` value before exchanging the code. Provider identities are stored in `oauth_accounts` and linked to a local user by verified provider email.

## Provider configuration

Configure the exact callback URLs in Google Cloud and Meta for Developers:

- `https://your-domain/api/auth/oauth/google/callback`
- `https://your-domain/api/auth/oauth/facebook/callback`

Set the matching `AUTH_GOOGLE_*`, `AUTH_FACEBOOK_*` and `AUTH_FRONTEND_CALLBACK_URL` environment variables documented in `.env.example`. Production callback URLs must use HTTPS.

## Password reset

Reset tokens are random, stored only as SHA-256 hashes, expire after 30 minutes and are single-use. An email delivery adapter is still required for production. `EXPOSE_PASSWORD_RESET_TOKEN=true` exposes the reset URL in the API response for local development only and must remain `false` in production.

## Authorization and tenant isolation

Protected API routes require a valid Bearer token. `current_user` rejects missing, expired, disabled-user and invalid tokens; it never falls back to a default account.

Authorization combines RBAC and ownership:

- `roles`, `permissions`, `role_permissions` and `user_roles` are managed by Alembic.
- Normal permissions such as `facebook_account:read` apply only to the signed-in user's rows.
- Cross-user access requires an explicit `:any` permission and must not be inferred from a role name.
- The bootstrap owner is assigned `super_admin`; normal users receive the `user` role.
- `GET /api/auth/me` returns effective `roles` and `permissions` for frontend guards.

RBAC administration endpoints are available under `/api/roles`, `/api/permissions` and `/api/users/{user_id}/roles`. System roles and permissions are catalog-managed and cannot be deleted through the API.

SSE clients must pass the signed token in the `token` query parameter because browser `EventSource` cannot set an Authorization header. The server filters events by `user_id`.
