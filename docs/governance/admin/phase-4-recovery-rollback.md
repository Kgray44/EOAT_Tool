# EOAT Atlas Admin Phase 4 Recovery and Rollback Record

## Scope and recovery point

Before applying revision `20260813_0008`, a local, non-Git SQL recovery
artifact was created for `eoat_atlas_test`. Its recorded SHA-256 is
`1D620BFEFCFD50BD8C818D6E0B8471096D8F56907D611927C29DB6D6C0A5456C` and size
is 1,888,798 bytes. It contains no production data target and is not copied
into this repository.

After the verified migration-forward result, a new local `0008` recovery
artifact was created for the Phase 4 rehearsal. Its recorded SHA-256 is
`423F7C766B5B80C07946CE579408D5BCEEE56076684855346ACB88472AE9C66E` and size
is 948,783 bytes. The high-risk precondition requires the configured artifact
path, this expected SHA-256, declared `20260813_0008` revision, and an age no
greater than four hours. This is an explicit rehearsal-only freshness rule,
not a corporate retention policy.

The `0008` artifact was restored once after its checksum verification. MySQL
then selected `eoat_atlas_test`, reported revision `20260813_0008`, and found
all three Phase 4 tables. It is therefore the validated recovery point for the
current Phase 4 test schema.

The browser receives only a configured-path availability result. It cannot
read the artifact, invoke a restore, reveal a path, run MySQL, start SSH, or
execute an operating-system command.

## Executed schema recovery exercise

On the protected Windows-loopback to Debian-loopback test route, the migrator
identity selected `eoat_atlas_test` and completed a real restore of the
pre-Phase-4 artifact. MySQL then reported `20260811_0007` from
`alembic_version`.

The artifact is a table-level dump. It correctly recreates every table known
at revision `0007`, but it cannot remove a table first introduced at `0008`.
The initial forward migration therefore failed closed rather than silently
accepting a mixed schema. The controlled recovery procedure removes only the
three known Phase 4 tables absent from the predecessor artifact, in foreign-key
order, before the forward migration:

1. `admin_operation_fixtures`
2. `admin_operations`
3. `admin_danger_step_ups`

It then completed `20260811_0007 -> 20260813_0008`.

The resulting Alembic revision is `20260813_0008`, and MySQL reports all three
new Phase 4 tables: `admin_danger_step_ups`, `admin_operations`, and
`admin_operation_fixtures`.

This is a verified test-only restoration procedure, not a generic production
restore recipe. A future recovery artifact taken after `0008` should include
the Phase 4 tables and be rehearsed independently before it replaces this
record.

## Operational rollback policy

The only executable high-risk action deletes rows from the test-only
`admin_operation_fixtures` namespace created by the Phase 4 acceptance test.
It never targets business tables. If that rehearsal needs recovery, an
authorized operator uses the existing out-of-band `eoat_atlas_test` recovery
procedure after verifying the artifact hash and target identity. Restoration
was not invoked in this pass because the action could not begin under the
least-privilege runtime account and no authoritative test-recovery approval
was supplied.

The recovery artifact was restored before the privilege repair and then
verified again at `20260813_0008` with all three Phase 4 tables. The
controlled fixture-recovery action was subsequently exercised with the normal
runtime identity only against disposable `phase4-...` rows. The final
acceptance cleanup restores the same validated `0008` artifact; the browser
never executes or receives access to that restore procedure.

Production restore, overwrite, purge, or factory reset have no API route and
remain blocked pending a separate approved runbook.
