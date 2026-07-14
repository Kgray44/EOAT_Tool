# EOAT History Event Model

## Contract

`HistoryEvent` exposes `event_id`, `eoat_identifier`, `event_type`, `event_category`, `occurred_at`, summary/description, actor/application instance, source record type/ID, related machine/tool/robot/storage/document/photo, reason, notes, previous/new values, and metadata. Missing values remain null or empty at the transport/model edge and are formatted only by the client.

## Categories

- `INSTALLATIONS`
- `MAINTENANCE`
- `AUDITS`
- `ENGINEERING_CHANGES`
- `DOCUMENTS_AND_PHOTOS`
- `TAGS_AND_ANNOTATIONS`
- `ARCHIVE_ACTIVITY`
- `OTHER`

## Generated event types

EOAT create/edit/archive/restore; install/remove/move-to-machine/move-to-storage/location-unknown; compatibility create/update/archive; audit start/complete; maintenance start/complete; document add/update/supersede/archive; photo add/update/profile-select/archive; tag assign/remove; and annotation add/update/archive are generated transactionally where the corresponding operation exists.

`COMPATIBILITY_VERIFIED` is represented through compatibility create/update plus its structured status rather than a separate command. `PM_COMPLETED` is currently represented by `MAINTENANCE_COMPLETED`. No current write endpoint creates `AUDIT_FINDING_CREATED`; the type is reserved for a future normalized finding operation. The generic typed renderer/API/cache/PDF path can carry these codes when implemented.

## Traceability

Source references identify records in `eoats`, compatibility tables, `eoat_installations`, `eoat_storage_assignments`, `audit_records`, `maintenance_events`, `documents`, `photos`, `entity_tags`, or `annotations`. Relationship labels and identifiers are copied into structured metadata at write time to avoid display-time N+1 queries. Before/after values are held as JSON objects but rendered as changed fields, never raw JSON.

## Ordering and identity

`occurred_at DESC, event_uuid DESC` is the default stable order. UUID is unique. Import-generated audit UUIDs are deterministic from source checksum/audit identity; API write UUIDs are generated once inside the idempotent transaction.
