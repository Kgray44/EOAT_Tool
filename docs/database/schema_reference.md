# EOAT Atlas MySQL Schema Reference

Alembic authority: revision `20260714_0003` (`cutover_session_traceability`) over `20260713_0002`. Database defaults: MySQL 8.4 LTS, InnoDB, `utf8mb4`, `utf8mb4_0900_ai_ci`, UTC application timestamps. There are 48 application tables plus `alembic_version`. The cutover session table provides a durable source-checksum, release-version, authority-window, and rollback audit anchor.

## Implemented tables

| Group | Tables | Purpose |
|---|---|---|
| Lookup/reference | `eoat_types`, `connection_types`, `cleanroom_classifications`, `asset_statuses`, `compatibility_statuses`, `compatibility_sources`, `document_types`, `history_event_types` | Evolvable categorized values without MySQL ENUM coupling |
| Organization/location | `plants`, `areas`, `storage_locations` | Facility, area, and non-machine EOAT locations |
| Engineering assets | `eoats`, `machines`, `robots`, `tools`, `parts` | Separate authoritative assets with internal unsigned BIGINT keys and business identifiers |
| Asset relationships | `machine_robot_assignments`, `tool_parts` | Dated machine/robot and tool/part relationships |
| Compatibility | `eoat_machine_compatibility`, `eoat_tool_compatibility`, `tool_machine_compatibility` | Explicit pairwise engineering evidence for Fit Check |
| Operations/location history | `eoat_installations`, `eoat_storage_assignments` | Dated installation/storage intervals and one-active-location guards |
| Current application features | `fit_check_records`, `audit_records`, `maintenance_events` | Historical Fit Check, audit, and maintenance records |
| Documents/photos | `documents`, `photos`, `document_links` | Controlled path/metadata model; no binary engineering files in MySQL |
| Identity | `users`, `roles`, `user_roles`, `application_instances` | Actor, authorization and client attribution foundation |
| History/auditing/sync | `entity_history_events`, `change_audit_log`, `change_feed` | User-facing timeline, authoritative before/after audit, monotonic cache cursor |
| Migration | `import_batches`, `import_rows`, `import_issues` | Batch, exact source row, normalized staging and review traceability |
| Configuration | `system_settings`, `system_metadata` | Central non-secret settings and operational metadata |
| Annotations/tags | `tags`, `annotation_targets`, `entity_tags`, `annotations`, `annotation_target_links` | Migrated definitions, assignments, notes, and strict legacy target links |
| Request safety | `idempotency_records` | Actor/operation-scoped request hashes and replayable authoritative results |
| Schema authority | `alembic_version` | Current migration revision; not duplicated in system metadata |

## Key design rules embodied in schema

- Business identifiers are unique columns separate from internal keys.
- Permanent entities carry UTC timestamps, actor references, `row_version`, archive state, source system, and import batch provenance where appropriate.
- Relationship effective/end dates have check constraints.
- Current EOAT machine and storage assignments use MySQL generated nullable marker columns and unique constraints. The service layer must still lock and validate moves transactionally.
- `document_links` is polymorphic to cover the present entity set; service code must validate target existence.
- `audit_records.details_json` preserves current workbook fields that do not yet have an approved normalized Phase A destination. It is not a replacement for future audit template/response tables.
- `change_feed` uses unsigned auto-increment `change_id` as the server-issued synchronization cursor.
- `change_audit_log` and history/import tables are intended to be append-only under application policy.

## Deferred by scope

Audit template/response normalization, BOM/components, production cutover, production authentication, and EOAT Profile page data/UI redesign remain later work. The legacy workbook, synchronization modules, and annotation SQLite source remain intact for comparison and the production `legacy` backend.
