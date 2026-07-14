# Constraint Reference

Live verification found 147 foreign keys, 37 unique constraints, and 15 check constraints across the 40 model tables.

Important constraints include:

- Unique EOAT, tool and part business identifiers.
- Unique machine/robot numbers within a plant.
- Unique plant/area and plant/storage-location codes.
- Unique versioned relationship keys (`entity pair + effective_from`).
- Check constraints for positive row versions, nonnegative EOAT component counts, positive machine/robot capacities, and valid effective/installation/storage dates.
- `uq_active_installation_eoat` and `uq_active_installation_machine` on generated nullable markers.
- `uq_active_storage_eoat` on the generated storage marker.
- Unique UUIDs for import batches, documents, application instances and change-audit events.
- Source-row uniqueness within an import batch.

Foreign keys generally use `RESTRICT` for engineering relationships and `SET NULL` for optional actor/source attribution. Import rows/issues cascade only with their containing import batch. Photos/document links cascade with deleted development-stage documents; user-facing permanent deletion remains prohibited by service policy.

