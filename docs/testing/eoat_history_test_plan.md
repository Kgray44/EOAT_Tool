# EOAT History Test Plan

## Scope and safety

Run only against local development MySQL, the allowlisted disposable `eoat_atlas_test`, offscreen PySide6 widgets, and validation-only fixtures. Do not change production, legacy SQLite, or the workbook. Verify the workbook checksum before/after controlled import.

## Automated coverage

- API: health/version/schema, known/unknown EOAT, archived/no-history behavior, pagination, newest-first and UUID tie ordering, filters, search, snapshot, and normalized outage.
- Generation: EOAT edits, location transitions, compatibility, audits, maintenance, documents/photos/profile selection, tags/annotations, archive/restore, structured source link, audit/change-feed rows, idempotency, and rollback atomicity.
- Gateway/cache: typed mapping, selected-EOAT population, full snapshot, physical cache deletion and rebuild, standard/deep refresh, offline marked delivery, incompatible server, and offline-write blocking.
- Multi-client: client A writes; client B refreshes, sees the event, deletes its cache, rebuilds, and sees the same event IDs.
- UI: zero/one/many events, out-of-order/tied events, selection, relevant details, changed fields, filters/search, read-only controls, compact/typical/high-DPI, and light/dark themes.
- PDF: zero/many/mixed events, long notes, missing values, correct overview/count/source/limitation, multipage extraction, no sensitive data, and visual render inspection.
- Legacy isolation: guard workbook open calls during actual `mysql_api` detail/history/PDF execution; confirm zero attempts.

## Runtime sequence

Start the development API at `127.0.0.1:8765`, verify schema `0004`, request P4-EOAT-0001 History, delete a temporary SQLite cache, run Deep Refresh, compare event IDs/counts, disconnect the API adapter, read offline history, build the application-service view and PDF, and save timings/evidence.

## Acceptance

All targeted tests pass; schema verification has no errors; cache rebuild preserves history; no Excel open occurs; screenshots have no overlap/clipping at tested sizes; PDF text and rendered pages are complete; production remains unchanged.
