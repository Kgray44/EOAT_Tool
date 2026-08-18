# EOAT Atlas Admin Phase 5 Traceability

Status: in progress.  The approved `kerberos_form` LDAP provider is now being
reconciled into the Phase 4 lineage; real-provider acceptance remains pending.

| Requirement area | Planned evidence | Current status |
| --- | --- | --- |
| ADM-AUTH-001 to 003 / ADM-IDP-001 | Provider authority record, selected provider configuration, persisted group mapping, real Admin/non-admin acceptance | In progress: IT approved `kerberos_form`; the approved mapping is persisted and the test-only `a2b91c6c` candidate is deployed with its login API.  Real flows await a browser profile that trusts the staging test CA and then human credential entry. |
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
  and LDAP SRV discovery.  The active non-production
  `eoat-atlas-write-test.service` selects `kerberos_form` with application
  scope through its staging environment file, while the primary runtime file
  does not.
* The isolated staging server/static releases now point to
  `eoat-atlas-phase5-a2b91c6c` and pass health, schema compatibility,
  provider/mapping, loopback route, and HTTPS static-release identity checks.
  The predeployment `eoat-atlas-0.26.10-725e97f` releases remain retained for
  rollback.  Production service, roots, listener, and health were read-only
  verified unchanged.
* The test certificate is hostname-valid but untrusted by the Codex in-app
  browser.  Validation was not bypassed, so live provider readiness and real
  credential acceptance remain unclaimed pending a trusted browser profile.
* Frontend provenance inspection established that live production and retained
  pre-Phase-5 staging are `725e97fa4603f10d32312a9b41f9b52c310dedb5`, whereas
  the deployed Phase-5 web bundle came from the older Admin-focused tree at
  `a2b91c6c`. Controlled reconciliation restored the production normal-web
  boundary, preserved Phase 1-5 Admin/auth UI, regenerated OpenAPI types, and
  added the normal-shell corporate Sign In/role-gated account control. Local
  web validation now passes TypeScript, ESLint, production build, and **53/53**
  Vitest tests; the restored fail-closed media boundary passes **10/10** focused
  server tests. See `phase-5-frontend-reconciliation.md`.
* Further certificate inspection established that staging and production vhosts
  use the same self-issued test certificate; there is no trusted existing
  certificate to reuse for `:8443`. Corporate-CA material or approved CA trust
  is an external prerequisite, not a browser workaround.

## Continuation evidence — 2026-08-18

This section supersedes the candidate/release-status statements above where
they name `a2b91c6c`. The reconciled normal EOAT Atlas frontend base
`0c7833b07e808537c6f82d73d68e3718fd83aecf` was deployed to staging first.
Current staging is `eoat-atlas-phase5-c2898bd6`
(`c2898bd66566548c6ee4be51f5bb598dc615a09c`), retaining that reconciled UI.

| Requirement area | Continuation evidence | Current status |
| --- | --- | --- |
| Normal-web parity | Current normal shell, navigation, representative API and media/history routes were checked on staging; local Playwright was 23 passed with 5 intentional non-live/visual skips. | Complete for non-corporate functional regression. |
| Admin access boundary | Anonymous overview/settings/audit routes deny with `401`; focused role/session/audit coverage passed. | Complete for synthetic/development evidence; real corporate identity evidence remains external. |
| Governed editing and audit | Real-MySQL Phase 2--4 suite passed 18/18, including controlled changes, correlation/receipt data, before/after state, append-only denial, CSRF/idempotency, fresh-auth and Danger safeguards. | Complete on the authorized test database. |
| Recovery and rollback | A staging-only recovery snapshot was restored, all 66 table counts matched, and the temporary restore schema was removed. Retained staging release pointers provide rollback through the reconciled base. | Complete; refresh recovery material before any later time-bounded drill. |
| Corporate browser sign-in | No real credentials were entered. IT has confirmed no approved trusted certificate is currently available; normal browser verification cannot be claimed. | Externally blocked solely by PKI/browser trust and the corresponding approved human corporate identity tests. |
| Production readiness | Candidate and rollback plan are prepared. Production remains healthy with writes disabled and has not been changed. | Prepared but not authorized to deploy pending corporate browser acceptance and release approval. |
