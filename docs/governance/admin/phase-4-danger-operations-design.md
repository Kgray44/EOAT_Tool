# EOAT Atlas Admin Phase 4: Danger Zone and Operations Design

Status: active Phase 4 development/test design. This record begins at accepted
Phase 3 commit `eed879b5ce1d5840ce76bc81bbf31ed62ce443ce`. It neither starts
Phase 5 corporate authentication nor authorizes a production deployment.

## Current architecture and reuse boundary

| Area                                     | Current state                                                                                                                                                                                                                 | Phase 4 disposition                                                                                                                                                                    |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/admin/system` and `/admin/diagnostics` | Phase 2 returns a single optimistic health shape with API, database, audit, and schema fields.                                                                                                                                | Replace its fabricated green values with independently evaluated, safe diagnostic checks.                                                                                              |
| `/admin/danger-zone`                     | Governed route is reserved but no surface or endpoint exists.                                                                                                                                                                 | Add an isolated Administrator page and a typed operation API only.                                                                                                                     |
| Audit ledger                             | `AuditEventWriter` is the sole application writer; it redacts before persistence and flushes inside the business transaction.                                                                                                 | Reuse it for export, support, scan, and danger-operation evidence. A failed required audit write aborts the operation.                                                                 |
| Rehearsal identity                       | Opaque, short-lived, HttpOnly/SameSite Phase 3 session plus server-side CSRF validation; it is allowed only in `development` and `staging_local`.                                                                             | Add a distinct short-lived, server-side step-up proof. It is visibly labelled development/test rehearsal and never represents corporate reauthentication.                              |
| MySQL and schema                         | The accepted test path is Debian MySQL through the protected loopback SSH tunnel, with `eoat_atlas_test` only at revision `20260811_0007`.                                                                                    | New operational state requires an additive migration and live acceptance only against `eoat_atlas_test`. No local Windows MySQL, development schema, or production schema may be used. |
| Backup/recovery tooling                  | The older cutover rehearsal can dump and restore only allowlisted staging databases and proves its artifact by checksum/count comparison. Existing Phase 3 acceptance also has a clean test-schema recovery dump outside Git. | Do not expose those commands or credentials through the browser. Phase 4 may inspect test-recovery evidence, but browser restore and production backup policy remain unavailable.      |
| Import tooling                           | Offline migration/import tooling exists; Phase 3 does not expose a generic browser import endpoint.                                                                                                                           | Do not create a new browser uploader or a commit path without an owned import contract.                                                                                                |
| Storage                                  | Documents/photos have server-side metadata and browser-safe serializers which suppress storage paths.                                                                                                                         | Storage checks report only a safe status. Support bundles never contain paths, logs, or file contents.                                                                                 |
| Transactions and locks                   | Phase 3 uses MySQL transactions, idempotency records, row versions, and session state.                                                                                                                                        | Add a persisted `admin_operations` lifecycle and a narrow server-side operation lock. Browser state is never authoritative.                                                            |

## Controlled Phase 4 model

Phase 4 adds the following server-owned concepts:

1. A diagnostic registry. Each named check has a capability,
   source, safe detail, remediation hint, and `HEALTHY`, `DEGRADED`, `FAILED`,
   `UNAVAILABLE`, or `UNKNOWN` result. One check cannot blank another card.
2. An integrity engine. It runs explicit, read-only database queries and stores
   a bounded result summary/finding list as an `admin_operation`; it never
   guesses a repair from incomplete evidence.
3. Server-generated Audit CSV and JSON exports. The repository applies the
   existing authorized filters, redaction is applied again at serialization,
   and an `AUDIT_EXPORT` event plus manifest is produced in the same request.
4. A safe support-evidence JSON package. It contains selected safe health,
   schema, release, integrity, request-ID, and sanitized ledger evidence. It
   contains no environment dump, cookie, token, credential, raw log, or path.
5. A two-stage Danger Zone rehearsal operation. Preview evaluates all required
   server preconditions, issues a short-lived server-stored reference, and
   exposes the exact test-only phrase. Commit rechecks the current state,
   requires CSRF, session, step-up, reason, exact phrase, and idempotency key.
   The only executable Phase 4 Danger operation is a bounded test-fixture
   recovery rehearsal; it can act only on records created for its own
   ephemeral test namespace in `eoat_atlas_test` and remains unavailable in
   every other environment.

The operation API is deliberately not a SQL console, shell, filesystem
browser, arbitrary script runner, upload executor, or generic maintenance
button. A request can name only an operation defined in the registry.

## Risk and environment policy

`LOW`: read-only diagnostics and integrity scans.

`MODERATE`: Audit export and support-evidence generation; these produce bounded
artifacts but do not mutate business records.

`HIGH`: test-fixture recovery rehearsal, which is a two-stage operation with
an operation lock, a fresh step-up proof, a recovery-point requirement, and
durable evidence.

`CATASTROPHIC`: factory reset, purge, overwrite restore, destructive repair,
and security-mapping reset. The taxonomy exists, but no executable operation is
implemented in Phase 4. Each is explicitly disabled pending project-owner/IT/
Quality authorization and Phase 5 identity/Phase 6 deployment.

Every high-risk commit requires the server to identify `development` or
`staging_local`, and the actual database name must equal `eoat_atlas_test`.
`production`, `eoat_atlas_prod`, `eoat_atlas_dev`, unknown environments, an
unknown dependency, or a missing recovery point fail closed. No query
parameter, browser value, or environment toggle can override that policy.

## Step-up and preconditions

The Phase 3 rehearsal session is necessary but insufficient for high-risk
commit. The new step-up proof is a server-side row scoped to the exact
operation/risk class, expires quickly, and is invalid when its session is
revoked, expired, or no longer has the required role/capability. The browser
receives only a safe reference for presentation; it is not stored in
localStorage or trusted for authorization by the frontend.

The shared evaluator reports individual `PASS`, `FAIL`, `WARNING`, or
`UNKNOWN` results for authorization, step-up, environment/database identity,
audit health, schema compatibility, recovery evidence, preview
freshness, and lock availability. Required `UNKNOWN` is a denial. Commit
always recomputes these values; preview never authorizes a stale commit.

## Integrity scope

Phase 4 checks only actual, queryable invariants: active open-ended duplicate
compatibility relationships, document links whose referenced entity is absent,
and archived-entity inventory. Schema mismatch is reported independently by
Diagnostics. Database-enforced constraints are reported as constraints, not
fabricated findings. Repairs are deferred: no authoritative data is guessed or
automatically rewritten.

## Recovery and deferred decisions

The test-only recovery rehearsal is recoverable by restoring the pre-created,
validated `eoat_atlas_test` recovery point through the existing approved
operator procedure. Phase 4 does not invoke `mysqldump`, `mysql`, SSH, or an
OS process through the API. The following remain `REQUIRES PROJECT OWNER / IT /
QUALITY DECISION`: production factory reset/purge/destructive repair, production
restore/dual approval/freshness policy, retention/purge duration, export
approval or watermark policy, and real corporate step-up behavior.
