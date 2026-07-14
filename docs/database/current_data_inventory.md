# Current EOAT Atlas Data Inventory

## Active Excel sources

### EOAT_Master_Tracker.xlsx

Workbook schema version: `2026.06.26.1`.

| Sheet | Used range | Source rows (excluding header) | Role |
|---|---:|---:|---|
| EOAT Inventory | A1:BX103 | 102 | Wide audit/current-state/compatibility source; 76 columns |
| Issue Log | A1:T2 | 1 placeholder row | Issue register |
| KPI Baseline | A1:R2 | 1 placeholder row | KPI observations |
| Interview Notes | A1:M2 | 1 placeholder row | Interview evidence |
| Pilot Candidates | A1:R2 | 1 placeholder row | Pilot candidates |
| FMEA Draft | A1:Q100 | 99 source/display rows | FMEA work area |
| Action Items | A1:J2 | 1 placeholder row | Action register |
| Photo Index | A1:T160 | 159 | Photo/document metadata; 158 resolvable file records in dry run |
| _EOAT_App_Metadata | A1:B4 | 3 | Workbook schema/app metadata |
| Audit by Press | A1:T168 | 167 display rows | Generated view from EOAT Inventory; not an independent authority |

EOAT Inventory contains 67 `Audited` rows and 35 `Compatible` rows, 57 EOAT identifiers, 65 usable tool identifiers, and machine values across Plant 4 and Cleanroom. Repeated EOAT rows represent both evidence and compatibility, so one Excel row cannot be treated as one database record.

### Robot_Info.xlsx

- Sheet: `Robot Info`, range A1:K50, 49 data rows.
- Fields: plant/area, machine number, robot type/identifier, vacuum/pressure/interchangeable circuit counts, last audit, updated timestamp, and notes.
- `Robot Identifier` is blank in the inspected rows, preventing creation of authoritative robot business identifiers without review.

### master_press_list.xlsx

- Sheet: `Machine Specifications`, range A1:AY62, 61 rows, 51 columns.
- Authoritative candidates for machine number, tonnage, manufacturer/model/year/serial/controller, injection/clamp/platen/ejector specifications, robot brand/model/serial, circuits, and peripherals.
- Phase A maps core machine/robot fields; detailed machine specifications remain import provenance pending a dedicated machine-specification extension.

### press_capacity.xlsx

- Sheet: `P4 Capacity`, range A1:W280, 279 mixed heading/detail/summary rows.
- Contains machine-to-part/tool candidates and forecast/cycle/capacity calculations.
- It is evidence for compatibility and part/tool relationships, not a clean entity table. Formula errors (`#VALUE!`) and combined machine lists were observed and must not be imported as facts without normalization.

## SQLite inventory

`project_data/annotations.sqlite` is schema versioned separately and contains:

| Table | Rows | Purpose |
|---|---:|---|
| schema_migrations | 2 | SQLite annotation schema revisions |
| notes | 11 | Markdown notes and follow-up metadata |
| tags | 15 | Annotation tags |
| annotation_targets | 52 | Workbook/audit/field/object targets |
| tag_assignments | 45 | Tag-to-target links |
| note_targets | 2 | Note-to-target links |
| note_tags | 0 | Note-to-tag links |
| attachments | 0 | File attachments |
| annotation_suggestion_ignores | 0 | Ignored suggestion fingerprints |
| open_item_states | 0 | Open-item resolution state |

This SQLite file contains permanent user-created annotation information today. It cannot be reclassified as disposable until those records are migrated to server tables in a later schema/application phase.

## Existing Python models

- `core.atlas_models`: workbook-derived immutable UI models for EOAT, machine, tool, compatibility, photos, warnings, search and recommendations.
- `core.fit_check_service`: typed Fit Check request/result and evidence structures.
- `core.annotations.models`: note/tag/target/assignment/attachment domain records persisted in SQLite.
- `core.audit.schema`: audit field specifications and workbook schema metadata.
- `core.models`: project-status model.

The new `core.domain` layer is separate from these legacy/UI models and has no PySide6, SQLAlchemy, Excel, SQLite, or HTTP dependency.

## Data quality findings affecting migration

- The workbook has part descriptions but no independent Part Number field. Tool # cannot be assumed to be part_number.
- Robot identifiers are not populated.
- At least one machine value contains a qualifier (`26 - Xqual in 25`) rather than one canonical machine number.
- Multiple EOATs have more than one `Audited` machine row with no explicit removal timeline; no installation history/current location was inferred.
- One Photo Index placeholder row has no file path; all 158 populated photo paths resolved during the dry run.
- Cleanroom/Whiteroom/Plant 4 terminology needs an approved plant/area/classification crosswalk.
- Several categorical and `N/A` fields require explicit unknown/null rules rather than silent coercion.

