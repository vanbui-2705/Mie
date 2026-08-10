# Browser Execution Module

## Scope

Owns automated and user-assisted browser sessions. It performs Facebook actions
that require a real browser context.

## Responsibilities

- Browser session creation and termination.
- Browserless and remote-browser connections.
- Personal browser login checks.
- Timeline, group and share actions.
- Browser worker queue and account locking.
- Extension connector online state and job exchange.

## Current source

- Module boundary: `backend/app/modules/browser/`
- `backend/app/browser_worker.py`
- `backend/app/routers/browser_sessions.py`
- `backend/app/routers/extension_connector.py`
- `backend/app/services/browser_sessions.py`
- `backend/app/services/personal_browser.py`
- `backend/app/services/kasm_provider.py`
- `backend/app/services/extension_queue.py`
- `backend/app/services/browser_profiles.py`
- Browser Dockerfiles in `backend/`

## Dependencies

- Proxy and profiles for session isolation.
- Facebook and Automation for requested actions.
- Platform Redis, configuration and event publication.
- Browser extension for user-browser execution.

## Invariants

- One account cannot be driven concurrently by conflicting jobs.
- Browser profiles are isolated by user and account.
- Session termination releases locks and remote resources.
- Selectors and browser errors include useful context without account secrets.
- Fallback execution must remain idempotent.

## Debugging

Check worker availability, queue claim, account lock, browser provider,
profile path, login state, page URL and selector failure in that order.

## Tests

Browser session, group share and page task tests under `backend/tests/`.
