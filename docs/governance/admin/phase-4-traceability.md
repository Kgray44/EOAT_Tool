# EOAT Atlas Admin Phase 4 Traceability

Status: development/test implementation with an explicit runtime-privilege
acceptance blocker. This is not production authorization.

| Requirement area                    | Implementation evidence                                                                                                                                                                                                                                                                                                                        | Verification status                                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Isolated baseline                   | Branch `feature/admin-phase4-danger-operations` begins at accepted Phase 3 commit `eed879b5ce1d5840ce76bc81bbf31ed62ce443ce`; the original UNC checkout was not changed.                                                                                                                                                                       | PASS                                                                                                 |
| Diagnostics truthfulness            | `admin/operations.py` produces independent API, database, schema, audit, authentication-rehearsal, and storage checks. `/admin/system` and `/admin/diagnostics` render those safe results rather than fabricated green values.                                                                                                                 | PASS: API read smoke and OpenAPI route check.                                                        |
| Integrity evidence                  | `POST /api/v1/admin/integrity/scans` has a closed capability, creates an operation receipt, inspects documented invariants, and writes `INTEGRITY_SCAN` evidence in the same transaction.                                                                                                                                                      | Blocked in real runtime acceptance: current test runtime role lacks DML on the new operation table.  |
| Audit and support exports           | Server-side bounded CSV/JSON audit export and selected-section support bundle apply redaction, checksum manifests, CSRF/session controls, and `AUDIT_EXPORT`/`ADMIN_EXPORT` evidence.                                                                                                                                                          | Blocked in real runtime acceptance for the same least-privilege grant gap.                           |
| Danger Zone                         | `/admin/danger-zone` provides test-only fixture recovery preview and commit with server-held session, CSRF, scoped five-minute step-up, exact typed phrase, reason, current target fingerprint, preconditions, operation locking, idempotency, and structured denial/completion evidence. No business or production data operation is exposed. | Code and route contract PASS; real runtime acceptance blocked before operation persistence.          |
| Environment isolation               | High-risk commit requires `development` or `staging_local`, MySQL-selected `eoat_atlas_test`, an existing configured recovery-point artifact, healthy database/audit/schema checks, and active scoped step-up.                                                                                                                                 | PASS: server-side implementation and direct test-database identity verification.                     |
| No arbitrary administration channel | No SQL console, shell execution, filesystem browser, browser backup/restore, upload executor, generic repair, production endpoint, or production privilege change was added.                                                                                                                                                                   | PASS by source/route inventory.                                                                      |
| Migration and rollback              | `20260813_0008` adds durable danger-step-up, operation, and test-fixture tables only.                                                                                                                                                                                                                                                          | PASS: isolated MySQL `0007 -> 0008 -> 0007 -> 0008`, ending at `0008` with all three tables present. |
| Existing Admin regression           | Phase 2/3 read and governed-editing test subset ran against `eoat_atlas_test`.                                                                                                                                                                                                                                                                 | PASS: 26 tests passed.                                                                               |
| Web quality                         | Generated OpenAPI artifacts include all six Phase 4 routes. TypeScript, ESLint, and Vitest all pass.                                                                                                                                                                                                                                           | PASS: 47 Vitest tests passed.                                                                        |

## Required external follow-up

The isolated runtime principal can still use prior Admin tables, but MySQL
denied its `INSERT` on `admin_operations`. The migrator principal successfully
applied the additive migration, so the schema is present. An authorized
test-only database administrator must extend the existing runtime role's
least-privilege `SELECT, INSERT, UPDATE, DELETE` access to the three new
`eoat_atlas_test` Phase 4 tables, then the committed real-MySQL Phase 4 suite
must be rerun. This record does not prescribe a credential, account command,
or production grant.

## Explicit deferrals

Corporate identity/reauthentication is Phase 5. Production deployment,
production database privileges, NGINX, retention policy, production backups,
real restore approval, factory reset, data purge, destructive repair, and
security-mapping reset require project-owner, IT, and Quality approval and are
not implemented here.
