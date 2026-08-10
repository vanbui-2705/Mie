# Legacy Facebook Poster Module

## Status

Legacy standalone application. It is separate from the main FlowMeta backend
and should not be used as a dependency by new modules.

## Scope

Owns the Tkinter UCMAS Facebook poster and its Playwright browser helper.

## Current source

- `facebook/app.py`
- `facebook/browser.py`
- `facebook/requirements.txt`
- `facebook/UCMAS_Poster.spec`
- Platform build scripts under `facebook/`

## Generated artefacts

`facebook/build/`, `facebook/dist/` and Python caches are generated output, not
architecture source. They are currently present in repository history and must
not be confused with implementation files.

## Dependencies

- Facebook Graph API.
- Playwright and local browser profiles.
- Local SQLite configuration and data.

## Invariants

- New FlowMeta features do not import this application.
- Legacy behavior is preserved unless a dedicated migration is approved.
- Generated executable contents are not edited as source.
- Stored tokens and local databases remain outside documentation and logs.

## Debugging

Reproduce inside the standalone application and distinguish Graph API,
Playwright, local database and packaging errors.

## Checks

- Python import/startup smoke test.
- PyInstaller build only when legacy packaging changes.

