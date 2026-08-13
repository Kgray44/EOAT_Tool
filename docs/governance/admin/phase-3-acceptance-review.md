# EOAT Atlas Admin Phase 3 Acceptance Review

Status: **in progress; not accepted**.

The earlier block was caused by incorrectly relying on the unavailable local
Windows `MySQL80_dashboard` service. Acceptance resumed through the already
approved Debian MySQL 8.4.10 architecture: Windows process -> loopback SSH
tunnel -> Debian loopback MySQL -> `eoat_atlas_test`. Both migration and
runtime identities selected `eoat_atlas_test` from MySQL itself; no other
schema, external MySQL exposure, production service, NGINX, LDAP/AD, or
production write gate was touched.

Before change, an acceptance-only recovery dump was created at
`%LOCALAPPDATA%\EOAT Atlas Development\admin-phase3-acceptance-backups\eoat_atlas_test-before-20260811_0007-20260811-164656.sql`
(created 2026-08-11 20:47Z). The predecessor was `20260811_0006`; migration
`20260811_0007` was applied and is current. A real-MySQL downgrade exposed a
MySQL foreign-key/index-order defect in the migration. A follow-up commit
corrected the downgrade, and `0006 -> 0007 -> 0006 -> 0007` then passed.

The expanded real-MySQL Phase 3 integration suite passes **11/11** against
this environment. It now covers session/CSRF, EOAT single- and multi-field
editing, stale conflict, idempotency, correction, archive/restore, Machine and
Tool validation/conflicts, relationship link/duplicate/free-text rejection and
unlink, document and photo metadata/archive with path containment, bulk
preview/zero-target/invalid-target atomicity/commit/replay correlation,
non-secret and secret settings, development-only role mapping, actor forgery,
session revocation, forced audit failure rollback, and capability denial. The
suite exposed and corrected a document response serialization defect; it was
then rerun successfully before the test schema was restored from the clean
Phase 3 recovery point.

A browser rehearsal session performed an EOAT preview/commit over the same
loopback API. The persisted immutable `UPDATE` event retained the
server-derived actor, request ID, correlation ID, exact before/after, and a
working in-app Audit Event link. Browser Back restored the request-filtered
Audit Ledger state. This browser pass also exposed and corrected the missing
rehearsal-identity handoff for Admin read endpoints and the disappearing
post-commit Audit Event link.

This review remains intentionally unaccepted. The browser audit event's
normal-profile link now uses the authorized same-origin relative contract and
the historic canonical display identifier: `/eoats/:identifier`,
`/machines/:number`, and `/tools/:identifier`. The normal profile renderer
itself is proven to exist only on the separate newer web lineage
`codex/web-desktop-full-parity` (`7d9b6952ca`), which has no Git merge base
with this accepted Admin lineage. This branch intentionally does not recreate
normal-profile components or merge that broad unrelated history. Full rendered
cross-navigation is therefore an explicit reconciliation dependency, while
the Phase C real-MySQL mutation matrix, browser matrix, performance
measurement, and complete regression matrix also remain outstanding. Do not
make a protected-main, deployment, or Phase 4 decision from this partial
evidence.
