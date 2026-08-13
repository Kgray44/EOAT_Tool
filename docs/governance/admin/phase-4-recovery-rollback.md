# EOAT Atlas Admin Phase 4 Recovery and Rollback Record

## Scope and recovery point

Before applying revision `20260813_0008`, a local, non-Git SQL recovery
artifact was created for `eoat_atlas_test`. Its recorded SHA-256 is
`1D620BFEFCFD50BD8C818D6E0B8471096D8F56907D611927C29DB6D6C0A5456C` and size
is 1,888,798 bytes. It contains no production data target and is not copied
into this repository.

The browser receives only a configured-path availability result. It cannot
read the artifact, invoke a restore, reveal a path, run MySQL, start SSH, or
execute an operating-system command.

## Executed schema recovery exercise

On the protected Windows-loopback to Debian-loopback test route, the migrator
identity selected `eoat_atlas_test` and completed:

1. `20260811_0007 -> 20260813_0008`
2. `20260813_0008 -> 20260811_0007`
3. `20260811_0007 -> 20260813_0008`

The resulting Alembic revision is `20260813_0008`, and MySQL reports all three
new Phase 4 tables: `admin_danger_step_ups`, `admin_operations`, and
`admin_operation_fixtures`.

## Operational rollback policy

The only executable high-risk action deletes rows from the test-only
`admin_operation_fixtures` namespace created by the Phase 4 acceptance test.
It never targets business tables. If that rehearsal needs recovery, an
authorized operator uses the existing out-of-band `eoat_atlas_test` recovery
procedure after verifying the artifact hash and target identity. Restoration
was not invoked in this pass because the action could not begin under the
least-privilege runtime account and no authoritative test-recovery approval
was supplied.

Production restore, overwrite, purge, or factory reset have no API route and
remain blocked pending a separate approved runbook.
