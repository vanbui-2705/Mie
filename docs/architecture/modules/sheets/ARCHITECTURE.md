# Google Sheets Module

## Scope

Owns Google Sheets connectivity, campaign synchronization, posting input and
status writeback.

## Responsibilities

- Sheet connection and credential validation.
- Campaign creation and column mapping.
- Reading task or rental input from Sheets.
- Synchronization locks and incremental updates.
- Publication result writeback.

## Current source

- Module boundary: `backend/app/modules/sheets/`
- `backend/app/routers/google_sheets.py`
- `backend/app/routers/sheet_campaigns.py`
- `backend/app/services/google_sheets.py`
- `backend/app/services/sheet_sync.py`
- `backend/app/services/sheet_post.py`
- `backend/app/services/sheet_writeback.py`
- `backend/app/services/rental_sheet_mirror.py`
- `backend/app/schemas/google_sheet_campaigns.py`
- UI routes `frontend/src/app/google-sheets/` and `sheet-campaigns/`

## Dependencies

- Platform database and configuration.
- Automation for publication jobs.
- Rental for rental-sheet mirroring.
- Google Sheets API.

## Invariants

- A campaign cannot run overlapping destructive syncs.
- Row identity remains stable across reads and writebacks.
- Provider credentials and raw tokens never enter logs.
- Partial provider failure must not mark unrelated rows successful.

## Debugging

Check credential access, spreadsheet ID, worksheet, column mapping, sync lock,
provider error and writeback queue. Use row identity rather than display order
when tracing an item.

## Tests

Google Sheets client, campaign, sync and writeback tests under
`backend/tests/`.
