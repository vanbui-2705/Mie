# Web Console Module

## Scope

Owns the authenticated Next.js management UI. Backend behavior remains owned
by the corresponding backend module.

## Responsibilities

- Application routes and navigation.
- Authentication state and protected pages.
- Feature forms, tables, progress and result views.
- Typed API and SSE clients.
- Shared UI components and notifications.

## Current source

- Feature boundaries: `frontend/src/features/`
- Routes: `frontend/src/app/`
- Flow Studio: `frontend/src/components/flow-studio/`
- Shared UI: `frontend/src/components/ui/`
- API clients: `frontend/src/lib/api-client.ts` and `flow-api.ts`
- Auth state: `frontend/src/lib/auth-context.tsx`
- Local rules: `frontend/AGENTS.md`

## Feature ownership

| UI area | Backend module |
|---|---|
| Accounts | Identity and Facebook |
| Auto comment/post/share | Automation and Browser |
| Flow Studio | Flow Video |
| Google Sheets and campaigns | Sheets |
| Proxy and profiles | Proxy and Profiles |
| Rental | Rental |
| Users and settings | Identity and Platform |

## Invariants

- Route components do not duplicate backend authorization.
- API calls use the shared authenticated client.
- SSE and polling cleanup when pages unmount.
- User-facing errors retain actionable provider or job context.
- Next.js changes follow the local version documentation referenced by
  `frontend/AGENTS.md`.

## Debugging

Start with browser network status, response body, auth state and SSE connection.
Then route the failure to the owning backend module. UI success messages must
not hide a backend failure.

## Checks

- `npx tsc --noEmit`
- ESLint for affected files.
- `npm run build`
