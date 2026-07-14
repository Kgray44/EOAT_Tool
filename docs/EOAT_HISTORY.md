# EOAT Lifecycle History

## Architecture

The EOAT profile History tab is a read-only lifecycle view. `LibraryRecordStateView` continues to build the existing hero and tab shell and lazily creates `RecordHistoryTab` only when History is opened. Non-EOAT profiles retain their previous compact history panel.

History data is isolated from the UI in `core/eoat_history.py`:

- `EOATHistoryRepository` defines retrieval for one EOAT.
- `LegacyAuditHistoryRepository` reads the existing project-local `00_Project_Admin/history/audit_history.jsonl` stream and returns only rows whose saved audit data identifies the requested EOAT.
- `GatewayEOATHistoryRepository` uses `AtlasDataGateway.get_eoat_history`; it is selected only when `EOAT_ATLAS_DATA_BACKEND=mysql_api` is explicitly configured.
- `EOATHistoryService` validates and normalizes source rows, assigns display categories, deduplicates stable source identities, applies deterministic newest-first ordering, filters events, and builds export summaries.
- `EOATHistoryEvent`, `EOATHistoryViewModel`, and `EOATHistoryExportModel` are typed immutable models consumed by the UI and PDF exporter.

The UI does not read JSONL, Excel, SQLite, MySQL, or SQL directly. Loading and PDF generation run on background threads. The activity list uses Qt model/view painting rather than one widget per event, keeping 500-row histories responsive.

## Current production source

The default application backend remains `legacy`. In that mode the only currently usable genuine lifecycle event source is the existing audit-save JSONL log. Consequently, legacy production profiles show documented audit completions/updates only. They do not infer machine installs, removals, maintenance, status changes, or tool changes from current-state workbook rows.

If no matching audit-history records exist, the profile displays the documented empty state. Test fixture events are located only under `tests/fixtures/eoat_history.py` and are never selected by a production provider.

The broader application remains hybrid: legacy Excel-based profile data and project-local support stores are the default, while the API/cache gateway is opt-in. SQLite is not used as an EOAT lifecycle-history source by this feature.

## MySQL readiness

The MySQL foundation contains `history_event_types`, `entity_history_events`, `eoat_installations`, `eoat_storage_assignments`, `change_audit_log`, and related audit tables. The API already exposes `/api/v1/eoats/{identifier}/history`, and the gateway repository consumes that endpoint only in explicit `mysql_api` mode.

No production routing or migration is changed here. Before MySQL becomes the production history authority, a later migration should:

1. Define stable event/source/transaction identifiers and uniqueness rules.
2. Populate typed location, maintenance, tool, status, verification, actor, effective-date, and previous/new-value fields rather than relying on generic summary/detail JSON.
3. Add offline history rows to the API cache if offline history is required; the current gateway deliberately reports unavailable history when no cached endpoint data exists.
4. Backfill legacy audit JSONL and verified installation/storage evidence with traceable source references.
5. Add integration coverage against `eoat_atlas_test` before enabling the backend for production reads.

## Supported event categories

Normalized categories are `LOCATION`, `AUDIT`, `MAINTENANCE`, `STATUS`, `TOOL`, `DOCUMENTATION`, `INSPECTION`, `IMPORT`, `ISSUE`, and `OTHER`. Unknown source types remain visible as `OTHER`; records are not discarded merely because the source type is new.

Each event may carry machine/tool transitions, statuses, reason, notes, audit or maintenance IDs, actor, source, effective/logged timestamps, verification, and source metadata. Blank fields are omitted from Event Details.

## Filters and selection

Search covers title, event type, machines, tool numbers, reason, notes, audit/maintenance IDs, recorded-by, and source. Event Type and Machine options are derived from the current EOAT history. Date options are All, Last 30 Days, Last 90 Days, This Year, and Previous Year. Search is debounced; filtering never mutates source events.

The first visible event is selected automatically. Selection is retained by stable event ID where possible and otherwise moves to the first remaining event. The activity list scrolls independently while Event Details remains visible. At constrained widths the controls reflow and the details region may stack below the list.

## Empty and error states

No matching production records produces “No documented history” and never sample data. Active filters with no results produce “No matching history.” Provider failures produce “History could not be loaded” with Retry; technical exceptions are logged and are not exposed as tracebacks.

## Export

The History Export menu offers Complete History and Filtered Results. `core/reporting/eoat_history_pdf.py` creates a branded PDF under `output/pdf` on a worker thread with:

- EOAT identity and current overview fields;
- an indexed EOAT image when a readable source image is available;
- total events, covered date range, event-type counts, and represented machines;
- every event in the selected scope with repeating table headers and wrapped details;
- an explicit no-history statement when applicable;
- EOAT ID, export timestamp, Atlas identification, and page number in the footer.

Filename format is `EOAT_History__<safe EOAT ID>__YYYYMMDD_HHMM.pdf`. Existing files receive a numeric suffix rather than being overwritten.

## Test and visual fixtures

`tests/fixtures/eoat_history.py` provides empty, mixed, randomly ordered, long-text, approximate-date, missing-field, and scalable histories for automated tests and local visual preview only. The feature tests cover repository isolation, empty results, deterministic sorting, duplicate suppression, partial/unknown rows, filters, export models, PDF output/no-history text/multipage behavior, read-only UI controls, selection, and a 500-event model.

Visual comparison captures are generated under `tmp/history_visuals`; PDF render checks use `tmp/pdfs`. These are temporary QA outputs, not production data.
