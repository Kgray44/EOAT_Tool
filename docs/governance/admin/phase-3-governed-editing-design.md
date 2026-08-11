# EOAT Atlas Admin Phase 3: Governed Editing Design Record

Status: active Phase 3 implementation design. This record extends the accepted
Phase 1 audit foundation and Phase 2 read-only Administrator surface. It does
not authorize Phase 4 Danger Zone work, Phase 5 corporate identity work, or a
production deployment.

## Baseline and isolated worktree

| Item | Evidence |
| --- | --- |
| Accepted source baseline | `532e3adef34e1b6290647ee9637de396f5f7afa8` |
| Accepted source branch | `feature/admin-phase2-readonly` |
| Phase 3 branch | `feature/admin-phase3-governed-editing` |
| Phase 3 worktree | `C:\\Users\\kgray\\eoat-admin-phase3-governed-editing` |
| Baseline relationship | Phase 3 HEAD begins exactly at the accepted Phase 2 commit. |

The prior Phase 2 worktree is clean and remains untouched. The archival UNC
checkout was found dirty and is not a Phase 3 source or mutation target.

## Reused authoritative architecture

| Layer | Existing owner | Phase 3 use |
| --- | --- | --- |
| HTTP request correlation | `eoat_api.app` middleware | Preserve `X-Request-ID` and return it from mutation responses/errors. |
| Transactions | `get_write_session` | Keep business write, global audit, legacy change audit, history, change feed, and idempotency persistence in one transaction. |
| Audit ledger | `admin.AuditEventWriter`, `material_diff`, `redact` | Retain the closed taxonomy, canonical material diff, redaction-before-persistence, flush-to-fail rollback behavior, and append-only model. |
| Domain mutations | `write_services.py` | Reuse EOAT/Machine/Tool, relationship, document/photo, archive, and history domain services. Do not add Admin SQL paths. |
| Concurrency | `VersionMixin.row_version` and `check_version` | Require expected row version for governed edits and return controlled `409` conflicts. |
| Retry control | `IdempotencyRecord` / `idempotent` | Require idempotency keys for replay-sensitive Admin operations. |
| Read-only Admin | `admin/routes.py`, `web/src/app/AdminApp.tsx` | Extend typed `/api/v1/admin` contracts and existing Admin shell; retain Phase 2 ledger and detail rendering. |
| Settings | `SystemSetting` | Add a typed, allowlisted setting registry; never return sensitive values. |
| Roles | `User`, `Role`, `UserRole`, `ROLE_PERMISSIONS` | Add action-level capabilities; Phase 3 mapping administration is limited to explicit development/test identities and roles. |

## Identity and mutation trust boundary

Phase 2's request header mapper is retained only for the accepted read-only
rehearsal contracts. It is not sufficient for Phase 3 mutations because a
browser can choose a header value. Phase 3 therefore adds a development/test
rehearsal session issuance endpoint that requires a server-held rehearsal
secret and creates a short-lived opaque, HttpOnly, SameSite cookie plus a
server-side session record. Every Phase 3
mutation resolves the actor and current role from that server-side session,
never from submitted actor fields or a JavaScript role value.

The development/test session issuer permits only explicitly configured local
identities in `development` or `staging_local`; it cannot run in production
mode. It fails closed unless `EOAT_API_ADMIN_REHEARSAL_SECRET` matches the
submitted development/test secret, then resolves role/name from persisted
server mappings and the database. The cookie never exposes identity, role,
audit identity, or credential data.
Each mutation additionally requires a session-bound CSRF token, JSON content
type, bounded request body, validated identifiers/enumerations, request ID,
and route-specific capability. No frontend service credential is introduced.

## Phase 3 domain strategy

EOAT, Machine, and Tool editing uses the authoritative asset services and
their lookup validation. Stable business identifiers, numeric database IDs,
timestamps, lifecycle/audit fields, source metadata, and row versions are
read-only. Domain business fields are allowlisted per entity. Lookup values are
selected from authoritative lookup APIs; form input cannot set foreign-key IDs.

The existing models provide row versions for assets, relationships, documents,
settings, and user records. The Admin API returns the current version, requires
it on commit, locks the target read, and returns `409 STALE_RECORD` if it has
changed. The UI loads the latest record, renders canonical preview values, and
on conflict offers reload/reapply rather than an overwrite.

Corrections are updates with a mandatory reason and action `CORRECTION`; they
create a new audit event and do not alter earlier ledger rows. Archive/restore
uses existing reversible lifecycle fields. EOAT archival reuses the existing
active-installation prohibition; relationship unlink is a reversible archive
of the relationship record. Document/photo scope is safe metadata and archive
only. Existing server-side supersession requires a controlled storage-path and
revision-ingestion workflow that the browser surface does not safely expose,
so file revision and association reassignment remain deferred rather than
simulated. Raw storage paths and physical file deletion are not exposed.

The bounded bulk workflow is an atomic, explicit selection of active EOATs for
one allowlisted status change. It has preview and commit modes, validates every
target and version, requires a confirmation phrase and idempotency key, writes
one correlated child audit event per target plus a redacted parent summary, and
rolls the full transaction back if any target or mandatory audit write fails.
It is not a generic bulk database editor.

## Settings and Access strategy

`/admin/settings` exposes only existing persisted `SystemSetting` keys. Non-secret values are
typed and audited with safe canonical before/after values. Sensitive values are
write-only: GET returns configuration state only, and audit/log/response data
contains only state transition metadata. A registry explicitly marks whether a
restart is required. The write gate is never exposed as a mutable production
bypass and no production state is changed.

`/admin/access` shows safe current roles, development/test mapping state, and
the current test session. It permits only constrained development/test identity
role mappings under a distinct capability. It neither connects to corporate
LDAP/AD nor encodes a production group. Session visibility/revocation is
limited to Phase 3-issued local rehearsal sessions; cookies/tokens are never
shown.

## Explicit deferrals

* Phase 4: Danger Zone, destructive mass operations, backup/restore controls,
  audit export, deep repair, diagnostics commands, and generic import tooling.
* Phase 5: approved LDAPS/SAML provider, corporate directory lookup, AD group
  mapping, and production session integration.
* Phase 6: staging/production deployment, production migration, production
  write enablement, NGINX changes, and production acceptance.
