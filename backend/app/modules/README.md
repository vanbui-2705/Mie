# Backend Modules

These packages expose stable functional boundaries over the current backend
implementation. They do not duplicate or replace business logic.

Read the architecture catalog at `docs/architecture/MODULES.md` before working
inside a module.

| Package | Responsibility |
|---|---|
| `platform` | Health and shared runtime foundations |
| `identity_access` | Authentication, OAuth, users and roles |
| `facebook` | Facebook accounts, OAuth and Graph API |
| `automation` | Tasks, comments, posts, shares and scheduling |
| `browser` | Browser sessions, extension and browser worker |
| `proxy_profiles` | Proxy leases and browser profiles |
| `sheets` | Google Sheets and campaigns |
| `rental` | Rental ingestion and publishing |
| `flow_video` | Reup, Gen and media processing |

During this phase, old import paths remain supported and no implementation file
is moved or removed.

