# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
dotnet run                    # Run the app
dotnet build -c Debug         # Build debug
dotnet publish -c Release -r win-x64 --self-contained true  # Self-contained publish
```

No test framework is configured. There is no test project or CI config.

## Architecture

Single WinForms app (`net9.0-windows`, assembly `ToolEditDeleteCmt`, branded "FlowMeta"). Startup order: network/update check → license gate (offline machine-bound via RSA + DPAPI) → main form.

Everything lives in one namespace and `Form1` orchestrates UI. The actual logic is split into service classes:

- **ProfileManager** — parses `uid|token` input, tracks per-UID token status (Live/Die/Checkpoint/expired), refreshes tokens on duplicate UID merge, uses `GraphCommentAuthorResolver` for token health checks via `GET /me?fields=id`.
- **CommentTaskManager** — builds tasks from profile/UID/link/post inputs, runs them in thread-limited rounds with optional delay between rounds, dispatches edit/delete/new-comment via `ICommentService`. Console-logs are managed per-task but nothing is persisted after run.
- **FacebookGraphCommentService** (`ICommentService`) — makes Graph API calls. Uses interfaces so swapping the HTTP backend (e.g., KiotProxy) is a registration change.
- **ProxyManager / KiotProxyClient** — round-robin proxy leasing. Each lease is `IDisposable`; `ProxyLease.MarkUsed()` decrements the slot, `Dispose` (uncalled) returns the slot. Proxies rotate IP automatically when uses hit zero. Falls back to `DirectLease` when proxy is off.
- **SecureSettingsStore** — serializes `AppSettings` to JSON then encrypts with Windows DPAPI (`CurrentUser`). File: `%LOCALAPPDATA%\ToolEditDeleteCmt\settings.dpapi`.
- **LicenseManager** — RSA-verified license key stored in `%LOCALAPPDATA%\FlowMeta\license.dpapi` via DPAPI. Private key lives in `FlowMetaLicenseAdmin/` admin tool only; never ship it with the customer app.

## Important Conventions

- **Progress reporting is required** — after every task or phase, report what was completed, which files/modules changed, what checks/tests ran, and what remains or is blocked. For longer work, provide short status updates while working.
- **No DI container** — `Form1` constructs managers directly. Adding services means wiring them manually in `Form1`.
- **All profiles keyed by UID** (case-insensitive) — duplicate UIDs infer a token refresh request, not a new row.
- **Cancellation** — `CancellationTokenSource` is passed to all async I/O but the app has no global cancellation token; each manager owns its own `_cts`.
- **DPAPI scope is `CurrentUser`** — settings/license are only readable by the same Windows user. Migrating to another user or machine requires re-activation.
- **The License dialog must pass before the main form loads** — nothing after the license gate runs if activation fails.
- **WinForms designer** — controls are created in `Form1.Designer.cs` (the partial class). The `.Designer.cs` file is auto-generated; edit it only when you understand the designer serialization format.

## License Admin

Build separately: `dotnet build .\FlowMetaLicenseAdmin\FlowMetaLicenseAdmin.csproj -c Release`. Admin generates keys from a private key file that must never be committed or shipped with the main app.
