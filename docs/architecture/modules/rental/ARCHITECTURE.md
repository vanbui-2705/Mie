# Rental Module

## Scope

Owns rental-room ingestion, normalization, media, group matching, Sheet mirror
and publication preparation.

## Responsibilities

- Nhatro.vn source adapter.
- Room normalization and status tracking.
- User-scoped rental image download.
- Target-group matching.
- Rental post construction and publication state.
- Rental data mirroring to Google Sheets.

## Current source

- Module boundary: `backend/app/modules/rental/`
- `backend/app/routers/rental.py`
- `backend/app/schemas/rental.py`
- `backend/app/services/nhatrovn_adapter.py`
- `backend/app/services/rental_sync.py`
- `backend/app/services/rental_media.py`
- `backend/app/services/rental_group_match.py`
- `backend/app/services/rental_post.py`
- `backend/app/services/rental_sheet_mirror.py`
- Rental models in `backend/app/models/sqlmodels.py`
- UI route `frontend/src/app/tro/`

## Dependencies

- Sheets for mirror and writeback.
- Automation and Facebook for publication.
- Platform storage, database and queue infrastructure.

## Invariants

- Remote rental media is validated before storage.
- Media paths remain scoped to the owning user.
- Source identity prevents duplicate rooms.
- Sync does not overwrite newer local publication state.
- Group matching remains deterministic for the same normalized input.

## Debugging

Trace source room ID through adapter output, normalized model, downloaded media,
matched groups, queued publication and Sheet mirror. Separate upstream HTML
changes from local validation and publication failures.

## Tests

- `backend/tests/test_nhatrovn_adapter.py`
- `backend/tests/test_rental_media.py`
- `backend/tests/test_rental_models.py`
- `backend/tests/test_rental_sync.py`
