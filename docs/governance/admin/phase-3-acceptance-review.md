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

The five existing real-MySQL Phase 3 integration tests pass against this
environment (session/CSRF, bulk/settings/secret containment, actor forgery
and session revocation, forced audit failure rollback, and capability denial).
A browser rehearsal session also performed an EOAT preview/commit over the
same loopback API; the persisted immutable `UPDATE` event retained the
server-derived actor, request ID, correlation ID, and exact before/after.

This review remains intentionally unaccepted. The browser audit event's
normal-profile link currently resolves to an unimplemented admin-shell route,
and the full Phase C real-MySQL mutation matrix, browser matrix, performance
measurement, and complete regression matrix remain outstanding. Do not make a
protected-main, deployment, or Phase 4 decision from this partial evidence.
