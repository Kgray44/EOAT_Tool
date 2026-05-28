# Workbook Validation and Repair System

Phase 5 adds structured workbook health findings and guarded safe repairs while preserving the existing markdown validation report and local-first workbook workflow.

## Structured Findings

Validation now attaches structured findings to `ToolResult.structured_data["validation_findings"]`. Each finding uses `core.validation_findings.ValidationFinding`:

- `finding_id`
- `severity`
- `category`
- `sheet_name`
- `row_number`
- `column_name`
- `audit_id`
- `machine_number`
- `message`
- `current_value`
- `expected_behavior`
- `recommended_action`
- `fix_available`
- `fix_id`
- `source_validator`

Severity values are:

- `BLOCKER`
- `ERROR`
- `WARNING`
- `INFO`
- `AUTO_FIXABLE`

The existing markdown report path is still supported. Structured findings are exported as a JSON companion report when foundation validation writes reports:

`00_Project_Admin/Validation_Reports/Foundation_Validation_YYYY-MM-DD_HHMM.json`

The JSON payload includes generation time, project root, summary counts, and the full findings list.

## Workbook Health UI

The Workbook Health page keeps the existing validation, schema repair, generated view refresh, open-folder, and open-workbook buttons. It now also shows a findings table with filters for:

- Severity
- Category
- Fix availability
- Search text

Finding actions include:

- Open Audit
- Jump to Field
- Create Annotation
- Create Follow-Up
- Preview Fix
- Apply Safe Fix
- Export Report

Open/jump actions use the existing annotation target navigator so audit-page behavior stays consistent with notes/tags.

## Compatibility Health

`core.compatibility_health` checks physical-vs-compatible consistency without implementing a full Robot Info entity system. It currently flags:

- Compatible rows missing a source audit ID
- Compatible rows referencing a missing or non-physical source
- Stale inherited compatible-row values
- Physical rows carrying compatibility metadata
- Missing or extra compatible relationships when the capacity reference file is available

Compatibility health findings are structured findings. They are not injected into the legacy warning string list, which preserves previous blank metadata behavior.

## Safe Repair Framework

`core.workbook_repairs` provides preview/apply functions. Apply requires explicit confirmation, checks for workbook locks, creates backups, logs activity, records audit history when rows change, and reruns validation afterward.

Supported safe fix IDs:

- `clear_stale_hidden_na`
- `repair_legacy_headers`
- `refresh_generated_views`
- `reapply_formatting`
- `rebuild_dropdown_validation`

Allowed safe fixes do not guess engineering values. The stale hidden value repair only sets meaningful values in non-applicable fields to `N/A`.

## Workbook Locks

`core.workbook_locks.detect_workbook_lock` checks whether the master workbook is present and likely writable. It detects common Office lock files and permission/open failures before repair writes.

## Audit History

Audit history now records:

- User-created and user-updated audit saves
- Compatibility regeneration events from source-audit saves
- Validation auto-fix row changes
- Workbook repair actions

History remains local JSONL under `00_Project_Admin/history/audit_history.jsonl`.

## Local-First Safety

The system writes only local project reports, backups, history, and SQLite annotation data. Generated reports and backups should stay uncommitted. Real workbooks, operational data, internal paths, logs, caches, reports, mold/part/customer/capacity/downtime/scrap details, and local configs must not be committed.
