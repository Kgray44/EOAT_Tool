# EOAT Atlas Excel-to-MySQL Dry-Run Report

- Batch: `08af702b-8b58-4a62-90b7-2b1ce0459789` (Phase 9 frozen-source dry run)
- Source: `C:\Users\kgray\AppData\Local\EOAT Atlas Staging\rehearsals\4f26cee2-7849-48ba-b437-f8a2a5bb485e\frozen_source\01_EOAT_Audit\EOAT_Audit_Database\EOAT_Master_Tracker.xlsx`
- SHA-256: `207e166c3c75f4a517a47f572c84d683b3b7a194bb23b1f5649e97c5d76b7eac`
- Workbook schema: `2026.06.26.1`
- Target Alembic revision: `20260714_0003`
- Source unchanged: `True`
- Rejected source rows: `0`
- Warnings: `22`
- Errors: `0`
- Unresolved relationships: `19`
- Photo paths checked/missing: `158` / `0`

## Staged counts

- `plants`: 1
- `areas`: 2
- `eoats`: 57
- `machines`: 61
- `tools`: 65
- `parts`: 0
- `part_candidates_requiring_crosswalk`: 67
- `eoat_machine_compatibility`: 87
- `eoat_tool_compatibility`: 65
- `tool_machine_compatibility`: 88
- `audit_records`: 102
- `installation_records`: 0
- `documents`: 155
- `photos`: 158
- `import_rows`: 261

`installation_records` remains zero by design: the workbook has repeated audited/current-looking rows but no reliable removal timeline, so the dry run refuses to invent installation history.

## Validation findings

| Severity | Code | Sheet | Row | Field | Description |
|---|---|---|---:|---|---|
| WARNING | MISSING_TOOL | EOAT Inventory | 29 | Tool # | No tool relationship can be created for this row. |
| WARNING | AMBIGUOUS_MACHINE_NUMBER | EOAT Inventory | 37 | Press/Machine # | Machine value contains qualifiers or multiple meanings and cannot be normalized safely. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 54 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 55 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 56 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 57 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 58 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 59 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 60 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 61 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 62 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 63 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 65 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | MISSING_MACHINE | EOAT Inventory | 66 | Press/Machine # | No machine relationship can be created for this row. |
| WARNING | CONFLICTING_EOAT_ATTRIBUTES | EOAT Inventory | 86 | cleanroom_classification | Repeated EOAT rows disagree on stable profile attributes. |
| WARNING | CONFLICTING_EOAT_ATTRIBUTES | EOAT Inventory | 89 | cleanroom_classification | Repeated EOAT rows disagree on stable profile attributes. |
| WARNING | CONFLICTING_CURRENT_ASSIGNMENT | EOAT Inventory |  | Press/Machine # | CL-EOAT-0050 has multiple audited machine assignments and no explicit removal timeline. |
| WARNING | CONFLICTING_CURRENT_ASSIGNMENT | EOAT Inventory |  | Press/Machine # | CL-EOAT-0052 has multiple audited machine assignments and no explicit removal timeline. |
| WARNING | CONFLICTING_CURRENT_ASSIGNMENT | EOAT Inventory |  | Press/Machine # | CL-EOAT-0054 has multiple audited machine assignments and no explicit removal timeline. |
| WARNING | CONFLICTING_CURRENT_ASSIGNMENT | EOAT Inventory |  | Press/Machine # | P4-EOAT-0057 has multiple audited machine assignments and no explicit removal timeline. |
| WARNING | PART_IDENTIFIER_AMBIGUITY | EOAT Inventory |  | Part Name/Description | The workbook contains part names but no independent Part Number field; Tool # cannot safely be assumed to be the part number. |
| WARNING | MISSING_PHOTO_PATH | Photo Index | 2 | Stored Relative Path | Photo metadata has no resolvable file path. |
