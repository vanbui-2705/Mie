# Desktop Module

## Scope

Owns the Windows FlowMeta desktop client built with .NET and WinForms.

## Responsibilities

- Desktop application shell and controls.
- Comment task management.
- Profile and proxy management UI.
- Secure local settings.
- Licensing and update checks.
- Windows-specific network safeguards.

## Current source

- Root `ToolEditDeleteCmt.csproj`
- Root C# files such as `Program.cs`, `Form1.cs`, managers and services.
- Visual assets in `Assets/`
- Build output in ignored `bin/` and `obj/`

## Dependencies

- Backend or Facebook APIs as configured by the desktop application.
- Windows DPAPI and local secure settings.
- License validation and update delivery.

## Invariants

- Local secrets use protected storage.
- UI work does not block the WinForms event thread.
- Update verification occurs before installing external content.
- License Admin source is excluded from the desktop project compile.
- Build output is never treated as source.

## Debugging

Identify UI event, manager/service call, network request and local settings
state. Keep license and credential values redacted.

## Checks

- Restore and build `ToolEditDeleteCmt.csproj`.
- Launch smoke test on Windows.
- Verify settings, licensing and update paths.

