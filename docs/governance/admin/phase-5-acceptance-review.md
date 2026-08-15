# EOAT Atlas Admin Phase 5 Acceptance Review

Date: 2026-08-15
Branch: `feature/admin-phase5-corporate-auth`
Baseline: `341270e2bb7a500ead7d61466279b61e590b4246`

## Result

**ADMIN PHASE 5: INCOMPLETE.**

IT approved LDAP and designated the installed `kerberos_form` server
configuration as the new Phase E standard on 2026-08-13.  The Phase 4 lineage
now requires provider/session reconciliation and safe verification of the
existing persisted Administrator mapping before real acceptance can begin.

## Completed safe work

* Created an isolated worktree at the accepted Phase 4 commit; the archived
  UNC source and Phase 4 worktree were not changed.
* Read the governing specification and Phase 1-4 design, traceability,
  acceptance, operation, failure-mode, and recovery records.
* Recorded the provider authority amendment, the approved non-plaintext
  Kerberos-authenticated LDAP/SASL-GSSAPI posture, and the Phase 6 boundary.
* Added a safe provider-status boundary that recognizes the approved provider
  but never treats configuration strings as verified provider or role-mapping
  readiness.
* Added the Kerberos-form authentication implementation: strict principal
  normalization; one private temporary credential cache per attempt; password
  delivery only through `kinit` stdin; LDAP SASL/GSSAPI lookup with the
  configured security floor; opaque, hashed, short-lived server sessions;
  CSRF; logout revocation; and persisted-group role resolution.
* Reconciled existing protected reads and mutations to derive their actor from
  the corporate session when application-scoped Kerberos-form authentication is
  selected.  Browser identity headers cannot substitute for that session.
* Applied only the approved table-level test-runtime grants to
  `eoat_adminp1_runtime@127.0.0.1`: sessions `SELECT`/`INSERT`/`UPDATE` and
  events `INSERT`.  The real runtime account proved all allowed operations and
  was denied event `UPDATE`/`DELETE`, DDL, grants, user creation, protected
  schemas, and global-Audit mutation.
* Added migration `20260814_0011` and updated the authoritative expected
  schema revision.  The protected `eoat_atlas_test` target was backed up and
  migrated successfully to `20260814_0011`; a current selection-safe recovery
  snapshot is retained locally.
* Added session authorization refresh and corporate fresh-auth proof support.
  Relevant directory groups only are stored server-side; mapping removal
  immediately removes elevated roles on the next protected request.  Fresh
  authentication is session-bound, operation/risk scoped, short-lived, and
  never stores a password.
* Focused configuration, service, and HTTP tests pass **11/11**.  They cover
  no persisted password/raw token, approved mapping, unmapped non-Admin,
  forged-header denial, cookie session, CSRF, Admin access, and logout denial.
* Updated the Admin client so `kerberos_form` uses the corporate login form and
  corporate password re-entry for Danger fresh-auth; local rehearsal remains
  available only when the provider is not selected.  The browser never stores
  a password, ticket, or session token.
* Server pytest passed **29** tests, web Vitest **47** tests, Phase 4 real-MySQL
  Danger rehearsal **3/3**, and targeted Ruff/compile/TypeScript/ESLint/build
  all passed.  A bounded broad integration run timed out without results and
  is not treated as a pass.
* Built a clean server/static candidate from exact commit
  `a2b91c6c642e7c6456a47389e599fadd239ad07c`, excluding Git metadata,
  environment files, dependency caches, and browser artifacts.  Its staged
  archives were SHA-256 verified before extraction into retained versioned
  nonproduction release directories.
* Switched only `eoat-atlas-write-test.service` and its separate staging static
  pointer to `eoat-atlas-phase5-a2b91c6c`.  The test service is active only on
  `127.0.0.1:8766`; health reports `eoat_atlas_test` schema `20260814_0011`,
  the approved provider/mapping, and the Kerberos-form login route.  The old
  `eoat-atlas-0.26.10-725e97f` releases remain intact as rollback targets.
* The staging-only release allowlist was expanded from the old release to the
  old release plus this exact candidate; its database, staging-environment,
  explicit-write, and database-URL-override fail-closed checks were preserved.
  Production service, release roots, listener, and health were read-only
  verified unchanged.

## Remaining completion evidence

1. Use an approved browser profile that trusts the staging test TLS CA for
   `https://eoat-atlas.gwplastics.com:8443/`.  The hostname-valid test
   certificate is untrusted by the available Codex in-app browser, and no
   certificate bypass is acceptable for corporate credential entry.
2. Approved real corporate Administrator and non-admin test identities must
   manually enter their credentials into the prepared browser form.  No
   credential may be provided in chat or retained by Codex.
3. Complete live Kerberos ticket, LDAP SASL/GSSAPI security-layer, outage,
   real actor-mutation, browser, and direct-route acceptance after item 1.
4. Re-run the broad MySQL integration suite to completion and reconcile the
   four preserved non-authoritative Phase 4 fixture rows by ownership before
   any cleanup.

There is not yet a real Administrator login, real non-admin denial, directory
security-negative test, provider outage proof, real actor mutation,
corporate-session expiration/revocation proof, or real-provider browser
acceptance to report.  This record is not a PASS.

## Frontend reconciliation and TLS correction status (2026-08-15)

Production and pre-Phase-5 staging frontend metadata both identify
`725e97fa4603f10d32312a9b41f9b52c310dedb5`; the deployed Phase-5 static bundle
instead identifies `a2b91c6c`. This caused the reported return of obsolete
normal UI and hid corporate Sign In inside the Admin surface. The controlled
source reconciliation restores the current production normal-web boundary,
preserves accepted Phase 1-5 Admin/authentication implementation, adds a
normal-shell Sign In/account control, regenerates the current API contract,
and restores hardened read-only media delivery. TypeScript, ESLint, production
build, 53 web Vitest tests, and 10 focused media-security tests pass locally.
It has not yet been deployed to staging.

The current staging TLS certificate cannot be accepted for credential entry:
it is self-issued despite the correct hostname/SAN, and the same test files are
also referenced by the production vhost. No trusted certificate exists on the
host to reuse. An IT-provided browser-trusted corporate-CA chain/key or
approved CA trust path is required before staging-vhost-only TLS correction,
trusted-browser verification, or any real corporate login. No warning was
bypassed and no credential was handled.

## Production safety

No production deployment, production database migration, production write
enablement, NGINX change, Active Directory membership change, MySQL exposure,
or secret commit occurred.  No real corporate credential was requested or
handled.

ADMIN PHASE 5: INCOMPLETE
