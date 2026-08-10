# License Admin Module

## Scope

Owns the Windows-only administrative utility for creating FlowMeta license
keys. It is intentionally separate from the customer desktop application.

## Responsibilities

- Administrative private-key storage.
- License payload and key generation.
- License Admin WinForms UI.
- Offline operator workflow.

## Current source

- `FlowMetaLicenseAdmin/FlowMetaLicenseAdmin.csproj`
- `FlowMetaLicenseAdmin/AdminPrivateKeyStore.cs`
- `FlowMetaLicenseAdmin/LicenseKeyGenerator.cs`
- `FlowMetaLicenseAdmin/MainForm.cs`
- `FlowMetaLicenseAdmin/Program.cs`
- Helper scripts under `tools/`

## Dependencies

- Windows protected-data APIs.
- Shared FlowMeta icon under `Assets/`.
- License format consumed by the Desktop module.

## Invariants

- Private signing material never enters Git, logs or generated documentation.
- License generation remains offline unless explicitly redesigned.
- The root Desktop project must not compile License Admin source.
- Changes to license format require coordinated Desktop compatibility tests.

## Debugging

Check protected key access, payload fields, signing operation and Desktop
verification separately. Never print private-key bytes during diagnosis.

## Checks

- Restore and build `FlowMetaLicenseAdmin.csproj`.
- Generate a non-production test license.
- Verify the test license with the Desktop application.

