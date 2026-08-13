# EOAT Atlas Admin Phase 5 Traceability

Status: in progress.  The approved `kerberos_form` LDAP provider is now being
reconciled into the Phase 4 lineage; real-provider acceptance remains pending.

| Requirement area | Planned evidence | Current status |
| --- | --- | --- |
| ADM-AUTH-001 to 003 / ADM-IDP-001 | Provider authority record, selected provider configuration, persisted group mapping, real Admin/non-admin acceptance | In progress: IT approved `kerberos_form`; mapping and real flows require verification. |
| ADM-AUTH-004 to 009 | Existing server-held rehearsal session remains environment-gated; `corporate_auth.py` reports the approved no-fallback provider boundary and config-only safe state. | Partial: enterprise session issuance is being reconciled. |
| ADM-ACC-001 to 004 | `/admin/access/status` exposes provider state and mapping-configured state without endpoints, group values, or secrets. | Partial: persisted mapping and provider diagnostic data still require verification. |
| ADM-DNG-001 | Corporate fresh-auth reconciliation with Phase 4 safeguards | In progress; rehearsal remains test-only. |
| ADM-SEC-010 to 017 | Provider state never reports `READY` from configuration strings; unavailable or unsupported providers fail closed. The Kerberos-form flow requires SASL/GSSAPI protection and avoids browser token storage. | Partial: provider-specific implementation review remains. |
| ADM-OBS-004 to 005 | Authentication/authorization event visibility and log redaction tests | In progress. |
| ADM-API-007 to 008 / ADM-TST-003 / ADM-TST-005 | Endpoint denial and forged-actor tests with session context | In progress. |
| PA-01, PA-02, PA-03, PA-07 | Provider-neutral synthetic and later real-provider browser/API evidence | Pending. |
| PA-13 / PA-14 | Session expiry and provider-unavailable fail-closed evidence | Pending. |

## Focused validation performed

* `ruff check` passed for the Phase 5 provider-state implementation, its
  Admin consumers, and focused configuration tests.
* Focused configuration, provider/session, header-forgery, CSRF, logout, and
  HTTP authorization tests pass **10/10**.  The test-only fake authenticator
  asserts that a supplied password reaches only the authentication boundary;
  no raw token or password is persisted or returned.
* Alembic static SQL passed and the protected loopback test target migrated
  from `20260813_0008` to `20260813_0010`.  The pre-existing compatible group
  mapping table was safely adopted, the approved mapping was seeded once, and
  the new session/event tables were verified.
* A real test-schema runtime transaction was intentionally rolled back after
  it exposed missing least-privilege DML on `corporate_authentication_events`.
  This is a fail-closed deployment prerequisite, not a passing runtime test.
* `compileall` passed for the new provider-state module and its Admin callers.
* The normal project pytest executable from the archived UNC environment timed
  out before emitting test collection output, both with normal discovery and
  with a null configuration/cache disabled.  This is a validation-environment
  limitation, not a test pass; the focused assertions above are the only
  executed unit evidence in this worktree.
