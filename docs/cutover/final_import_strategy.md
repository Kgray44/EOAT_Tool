# Final Import and Reconciliation Strategy

1. Create an empty allowlisted staging database and migrate from zero to Alembic head.
2. Record a `cutover_sessions` row containing UUID, source checksum, schema/API/client versions, start cursor, status, and rollback deadline.
3. Run a dry analysis against the frozen workbook. Zero rejected rows and zero errors are required.
4. Execute the workbook import once. Duplicate-completed-checksum protection prevents accidental replay.
5. Execute the annotation SQLite import and require exact counts, zero duplicates, zero orphans, and an unchanged source hash.
6. Compare legacy identifiers, compatibility relationships, audits, documents, photos, parts, and installations with MySQL.
7. Verify schema revision, tables, constraints, foreign keys, indexes, source checksums, and documented issue dispositions.

Blocking outcomes are rejected source rows, an unexpected missing/extra identifier, foreign-key failure, duplicate business keys, source mutation, annotation orphan, or a classified `BLOCKER`. Unknown installation dates and locations are displayed as unknown; part candidates are deferred; no current location or part number is invented.

Authority can be enabled only after a restorable MySQL backup exists and the go/no-go scorecard is signed. Import evidence is under `reports/cutover_rehearsal/`.
