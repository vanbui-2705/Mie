# Browser Extension Module

## Scope

Owns the Manifest V3 connector that executes FlowMeta jobs in the user's real
browser.

## Responsibilities

- Extension background service worker.
- Facebook content-script actions.
- Popup status and connection controls.
- Backend job polling and result reporting.
- Host-permission management.

## Current source

- `extension/manifest.json`
- `extension/background.js`
- `extension/content.js`
- `extension/content-main.js`
- `extension/popup.html`
- `extension/popup.js`
- `extension/README.md`

## Dependencies

- Automation and Browser backend modules.
- Main API extension connector routes.
- Facebook DOM and browser permissions.

## Invariants

- Manifest permissions remain minimal and explicit.
- Jobs are acknowledged exactly once.
- Content scripts validate the active host and target.
- Backend URLs are configured consistently with deployment.
- Backup files are not production source.

## Debugging

Check extension service-worker console, content-script console, active tab URL,
connector online state, job ID and backend response. DOM changes should be
diagnosed separately from connector authentication.

## Checks

- Validate `manifest.json`.
- Load unpacked extension.
- Confirm connector online state.
- Run a controlled browser job.

