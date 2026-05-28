# Performance, Cache, and Telemetry

Phase 6 adds clearer dashboard cache staleness tracking and structured performance diagnostics while preserving the quick refresh/deep refresh split.

## Quick vs Deep Refresh

Quick Refresh remains lightweight:

- Reads the dashboard cache.
- Checks source metadata with file and folder `stat`/glob operations.
- Does not open or scan the master workbook.
- Shows cached cards even when stale, with a visible stale explanation.

Deep Refresh remains intentional:

- Recomputes workbook-backed metrics.
- Updates the dashboard cache.
- Logs refresh duration.

## Cache Metadata

Dashboard cache source metadata now tracks:

- Master tracker workbook
- Activity log
- Scheduled report log
- Daily report folder
- Weekly report folder
- Task and schedule JSON files
- Annotation database
- Small `Robot_Info.xlsx`
- Validation findings JSON reports
- Photo index files, if separate files exist
- Documentation gap outputs
- Open items report outputs

Missing optional files are recorded but do not break cache loading.

## Stale Reasons

The cache no longer returns only stale/not stale. `cached_snapshot_status()` includes a list of stale reasons and a user-facing explanation, for example:

```text
Dashboard cache stale because:
- activity_log.jsonl changed.
- EOAT_Master_Tracker.xlsx changed.
```

The older `cached_snapshot()` tuple remains available for existing callers.

## Structured Performance Logging

Text performance logs still write to:

`00_Project_Admin/logs/performance.log`

Structured JSONL events now write to:

`00_Project_Admin/logs/performance.jsonl`

Each JSONL row includes:

- `timestamp`
- `operation`
- `duration_seconds`
- `success`
- `source`
- `page_tool`
- `project_root_mode`
- `details`
- `warning_count`
- `error_count`

## Performance Page

The Performance page displays:

- Event count
- Cache hit/stale/miss counts
- Warning/error totals
- Latest startup duration
- Latest quick refresh duration
- Latest deep refresh duration
- Slowest recent operations

Generated cache and performance logs are local project outputs and must not be committed.

## Page Open Pattern

Pages that need workbook reads, report scans, backup scans, validation data, or repository checks should open as shells first:

- `__init__()` builds widgets and connects signals only.
- `on_show()` displays cached or last-known data when available, then starts a debounced background refresh.
- Event-bus handlers return `True` after scheduling their own refresh so the dashboard does not launch a duplicate fallback refresh.
- Filter controls update already-loaded rows locally; they do not call workbook or folder scanners.
- Table population disables sorting, signals, and updates while rows are rebuilt, then resizes columns once.
- Page performance is logged as `page.<page_key>.shell_create`, `page.<page_key>.data_load`, and `page.<page_key>.table_render`.

Expensive safety audits, full tests, cleanup, validation repair, and final handoff generation remain explicit button actions.
