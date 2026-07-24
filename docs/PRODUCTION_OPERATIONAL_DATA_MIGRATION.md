# Production operational-data migration

EOAT Atlas production operational data is promoted with `scripts/database/build_production_data_migration.py`. It is not promoted with an all-table `mysqldump` because a newly migrated production database already contains Alembic-owned lookup rows and because development authentication/runtime state is not portable.

## Required invariants

- The source must be the authoritative development MySQL database and must be at Alembic revision `20260721_0008`.
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
py -3.14 -m alembic -c server/alembic.ini upgrade 20260721_0008
py -3.14 scripts/database/build_production_data_migration.py build `
  --source-environment development `
  --baseline-environment C:\secure\baseline.env `
  --source-branch development/mysql-api-consolidated `
  --output-directory C:\migration-evidence\eoat-operational-data
```

The output contains the SQL artifact and checksum, manifest, all-table classification, source/expected counts, seed parity, exclusions and transformations, file-reference analysis, validation report, a standalone copy of the migration utility, and controlled import/rollback instructions.

For the approved observed-location correction, the package also contains the owner approval evidence, required empty-production baseline counts, location observation/assertion report, duplicate-resolution report, and an explicit supersession record for `eoat-operational-633d0596386fc44b33c2`. The superseded package must never be amended or overwritten.

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

For machine-profile smoke coverage, the tool derives a deterministic imported machine record and sends its `plant_code` with the machine number. Machine numbers are unique only within a plant; this intentionally preserves the API's `409` response for an unqualified ambiguous number rather than choosing an arbitrary machine.

Run `verify-empty-baseline` against production immediately before the backup and again after the disposable rehearsal. It requires the exact migrated baseline table counts, absent operational marker, and zero location observations/assertions. After a disposable or production import, attempt the same SQL a second time; the marker guard must refuse it, and a subsequent `validate-database` must still pass.

The generated guard always drops its temporary stored procedure before a refusal is surfaced. A duplicate or non-baseline import reports its guard reason and aborts before any operational rows or freshness metadata can change; it must not leave a temporary routine behind.

Run `tools/verify_master_tracker_mysql_parity.py` against the imported disposable database. The verifier is state-aware: compatibility rows never imply current installation; explicit cabinet/not-installed audit notes override a generic machine/context field; and conflicting simultaneous machine observations must be represented by `CONFLICTING` observations. It writes `eoat_location_state.csv` and `state_aware_location_parity.json` in addition to the general parity evidence.

Packages built for `20260715_0006` or `20260717_0007` are obsolete and must be rejected. Use only a new migration identity whose manifest requires `20260721_0008`; never amend or reuse an older package.

An observed current installation is not installation history. Revision `20260717_0007` represents this evidence in `eoat_location_observations` and retains row-level support in `eoat_location_assertions`. Date-only audits use `observed_on` with no fabricated `observed_at`. Real lifecycle tables still require genuine event times, and storage assignments still require a real storage location. “EOAT in cabinet” may prove stored state without identifying a cabinet; keep the observation target null rather than inventing a cabinet code.

A failing strict parity verdict is a go/no-go blocker even when the data artifact perfectly reproduces the authoritative MySQL source. Preserve the detailed evidence instead of converting unresolved source issues into “expected” differences.

## Production and rollback

Use the generated `IMPORT_INSTRUCTIONS.md` and `ROLLBACK_INSTRUCTIONS.md`. They require checksums, a full pre-import backup, restore validation in a disposable database, exact typed confirmations, a disposable import before production, post-import validation and backup, and preservation of failed-import evidence. The procedure does not start the API and does not modify systemd or Nginx.
