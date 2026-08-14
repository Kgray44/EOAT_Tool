# EOAT Atlas Admin Phase 5 Traceability

Status: in progress.  The approved `kerberos_form` LDAP provider is now being
reconciled into the Phase 4 lineage; real-provider acceptance remains pending.

| Requirement area | Planned evidence | Current status |
| --- | --- | --- |
| ADM-AUTH-001 to 003 / ADM-IDP-001 | Provider authority record, selected provider configuration, persisted group mapping, real Admin/non-admin acceptance | In progress: IT approved `kerberos_form`; the approved mapping is persisted and runtime/session evidence passes, while real flows require an active non-production provider configuration and human credential entry. |
| ADM-AUTH-004 to 009 | Existing server-held rehearsal session remains environment-gated; `corporate_auth.py` reports the approved no-fallback provider boundary and config-only safe state. | Partial: opaque corporate session issuance, revocation, expiry, mapping refresh, and fresh-auth semantics are implemented and tested against real MySQL with a synthetic authenticator. |
| ADM-ACC-001 to 004 | `/admin/access/status` exposes provider state and mapping-configured state without endpoints, group values, or secrets. | Partial: persisted mapping and provider diagnostic data still require verification. |
| ADM-DNG-001 | Corporate fresh-auth reconciliation with Phase 4 safeguards | Implemented and real-MySQL exercised: a password is revalidated only through the corporate authenticator, the proof is session-bound, operation/risk scoped, short-lived, and invalidated by session revocation. The Danger operation remains test-only. |
| ADM-SEC-010 to 017 | Provider state never reports `READY` from configuration strings; unavailable or unsupported providers fail closed. The Kerberos-form flow requires SASL/GSSAPI protection and avoids browser token storage. | Partial: provider-specific implementation review remains. |
| ADM-OBS-004 to 005 | Authentication/authorization event visibility and log redaction tests | In progress. |
| ADM-API-007 to 008 / ADM-TST-003 / ADM-TST-005 | Endpoint denial and forged-actor tests with session context | In progress. |
| PA-01, PA-02, PA-03, PA-07 | Provider-neutral synthetic and later real-provider browser/API evidence | Partial: focused service/HTTP and browser-client build evidence is complete; real Admin/non-admin browser acceptance awaits the active provider endpoint and manual entry. |
| PA-13 / PA-14 | Session expiry and provider-unavailable fail-closed evidence | Partial: real-MySQL expiry, revocation, and unavailable-provider unit paths pass; live provider outage recovery remains pending. |

## Focused validation performed

* `ruff check` passed for the Phase 5 provider-state implementation, its
  Admin consumers, and focused configuration tests.
* Focused configuration, provider/session, header-forgery, CSRF, logout,
  mapping-invalidation, fresh-auth, and HTTP authorization tests pass
  **11/11**.  The test-only fake authenticator
  asserts that a supplied password reaches only the authentication boundary;
  no raw token or password is persisted or returned.
* The protected loopback test target is now at `20260814_0011`.  Migrations
  `20260813_0009`/`0010` safely adopted the pre-existing compatible group
  mapping table, seeded the approved mapping once, and verified the new
  session/event tables.  `20260814_0011` adds only the
  relevant authorization-group context and server-side fresh-auth metadata.
* The runtime identity was granted only `SELECT`, `INSERT`, and `UPDATE` on
  `corporate_authentication_sessions`, and only `INSERT` on
  `corporate_authentication_events`.  A real runtime transaction proved the
  allows and the denials for event update/delete, schema change, grants, user
  creation, protected-schema access, and immutable global-Audit update.
* Real-MySQL synthetic corporate-session acceptance proved persistence, token
  and CSRF hashing, Administrator mapping, multi-session semantics, logout
  revocation, expiry, authorization refresh after an isolated mapping change,
  and fresh-auth success/failure audit events.  All synthetic user/session/
  event rows were removed through the migration identity afterward.
* Server-focused pytest passed **29** tests; web Vitest passed **47** tests;
  TypeScript, ESLint, production build, targeted Ruff, and `compileall` pass.
  The Phase 4 real-MySQL Danger rehearsal passed **3/3** at schema `0011`.
  The broad integration command exceeded its 120-second bound without output
  and is not counted as a pass; four pre-existing-or-interrupted non-authoritative
  Phase 4 fixture rows were preserved rather than deleted without provenance.
* EOAT-ATLAS prerequisite probing confirmed Kerberos tools, krb5 configuration,
  and LDAP SRV discovery.  The assumed active runtime environment file did not
  expose the Phase E `kerberos_form`/application settings, so no live provider
  readiness or real credential acceptance is claimed.
