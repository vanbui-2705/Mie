# Proxy and Profiles Module

## Scope

Owns proxy inventory, leases and browser-profile environments associated with
Facebook accounts.

## Responsibilities

- Proxy configuration and health.
- Direct or managed proxy lease selection.
- Profile creation, activation and persistence.
- Account-to-profile association.
- Integration with KiotProxy and browser runtimes.

## Current source

- Module boundary: `backend/app/modules/proxy_profiles/`
- `backend/app/routers/proxy.py`
- `backend/app/routers/profiles.py`
- `backend/app/services/proxy_manager.py`
- `backend/app/services/kiotproxy_client.py`
- `backend/app/services/profile_manager.py`
- `backend/app/services/browser_profiles.py`
- Proxy and profile models in `backend/app/models/sqlmodels.py`
- UI routes `frontend/src/app/proxy/` and account/profile components.

## Dependencies

- Platform database, configuration and persistent profile volume.
- Browser execution for profile activation.
- Identity for user ownership.

## Invariants

- A profile belongs to one user and its configured account.
- Private proxy credentials are never logged.
- Lease release happens after success, failure or cancellation.
- Runtime profile directories remain outside version control.

## Debugging

Identify the selected account, profile ID, proxy lease, provider response and
browser connection. Distinguish provider exhaustion from invalid credentials
and browser startup failure.

## Tests

Proxy, profile and account-isolation tests under `backend/tests/`.
