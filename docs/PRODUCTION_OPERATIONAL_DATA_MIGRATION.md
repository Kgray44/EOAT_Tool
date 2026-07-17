# Production operational-data migration

EOAT Atlas production operational data is promoted with `scripts/database/build_production_data_migration.py`. It is not promoted with an all-table `mysqldump` because a newly migrated production database already contains Alembic-owned lookup rows and because development authentication/runtime state is not portable.

## Required invariants

- The source must be the authoritative development MySQL database and must be at Alembic revision `20260715_0006`.
- The production-equivalent baseline must be a newly migrated disposable MySQL database at the same revision.
- A production database, a name ending in `_prod`, or a test database outside explicit validation mode is rejected as an export source.
- All 53 base tables must have a policy in `TABLE_POLICIES`; an unknown or missing table stops the build.
- Alembic-seeded rows are reconciled by stable code. Meaning conflicts stop the build. Source-only operational codes are assigned deterministic non-colliding target IDs, and dependent foreign keys are remapped by meaning.
- Development users, roles assignments, sessions, authentication audit events, application instances/releases, cutover sessions, idempotency state, external group mappings, and environment settings are excluded.
- Completed sanctioned `import_batches`, `import_rows`, and `import_issues` are retained because operational rows reference them as provenance.
- Generated columns are never exported. Binary values use MySQL hexadecimal literals, text is UTF-8/utf8mb4, and rows are ordered by primary key.
- The import is accepted only against exact migrated-baseline counts. A persistent `system_metadata` marker is written as `IN_PROGRESS` before the transactional data load and changed to `COMPLETED` on success. Either state prevents an accidental second import.

## Build

Create and migrate a disposable baseline first. Load connection values from an untracked environment file; never place passwords on the command line.

```powershell
py -3.14 -m alembic -c server/alembic.ini upgrade 20260715_0006
py -3.14 scripts/database/build_production_data_migration.py build `
  --source-environment development `
  --baseline-environment C:\secure\baseline.env `
  --source-branch development/mysql-api-consolidated `
  --output-directory C:\migration-evidence\eoat-operational-data
```

The output contains the SQL artifact and checksum, manifest, all-table classification, source/expected counts, seed parity, exclusions and transformations, file-reference analysis, validation report, a standalone copy of the migration utility, and controlled import/rollback instructions.

## Disposable validation

Migrate a second empty database, import `operational-data.sql`, and run both validation commands without starting a live API:

```powershell
py -3.14 scripts/database/build_production_data_migration.py validate-database `
  --package-directory C:\migration-evidence\eoat-operational-data `
  --database-environment C:\secure\validation.env
py -3.14 scripts/database/build_production_data_migration.py api-smoke `
  --package-directory C:\migration-evidence\eoat-operational-data `
  --database-environment C:\secure\validation.env
```

`validate-database` checks the revision, every expected count, all declared foreign keys, every unique index, AUTO_INCREMENT positions, transient database-name leakage, the completed marker, and runtime grants. Run `mysqlcheck --check --extended` separately with the migration account. The API smoke command uses FastAPI in-process and covers EOAT, machine, tool, compatibility, Fit Check, history, documents, photos, and home summary reads; it does not bind a network port.

Run `tools/verify_master_tracker_mysql_parity.py` against the imported disposable database. A failing strict parity verdict is a go/no-go blocker even when the data artifact perfectly reproduces the authoritative MySQL source. Preserve the detailed evidence instead of converting unresolved source issues into “expected” differences.

## Production and rollback

Use the generated `IMPORT_INSTRUCTIONS.md` and `ROLLBACK_INSTRUCTIONS.md`. They require checksums, a full pre-import backup, restore validation in a disposable database, exact typed confirmations, a disposable import before production, post-import validation and backup, and preservation of failed-import evidence. The procedure does not start the API and does not modify systemd or Nginx.
