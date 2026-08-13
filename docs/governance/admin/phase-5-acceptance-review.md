# EOAT Atlas Admin Phase 5 Acceptance Review

Date: 2026-08-13
Branch: `feature/admin-phase5-corporate-auth`
Baseline: `341270e2bb7a500ead7d61466279b61e590b4246`

## Result

**ADMIN PHASE 5: IN PROGRESS.**

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
* Added migrations `20260813_0009` and `20260813_0010`.  The protected
  `eoat_atlas_test` target was backed up and migrated successfully to
  `20260813_0010`; it contains one active approved Administrator mapping and
  both new corporate session/audit tables.
* Focused configuration, service, and HTTP tests pass **10/10**.  They cover
  no persisted password/raw token, approved mapping, unmapped non-Admin,
  forged-header denial, cookie session, CSRF, Admin access, and logout denial.
* Updated safe Access and System/Diagnostics state to describe enterprise
  provider status rather than calling local rehearsal authentication a
  corporate-ready provider.
* Added focused provider-state tests.  Static lint and compile checks passed;
  direct bundled-Python assertions passed 4/4.  The normal UNC pytest runner
  timed out before collection output and is not counted as a pass.

## Remaining completion evidence

1. Reconciled provider/session implementation in the accepted Phase 4 lineage.
2. Safe verification of the existing persisted Administrator mapping and
   approved lower-role rules.
3. Approved real corporate Administrator and non-admin test identities.
4. Approved manual credential-entry and non-production acceptance procedure.
5. Provider-specific fresh-auth/step-up semantics for the Phase 4 Danger
   safeguard.
6. Test-runtime least-privilege grants for `corporate_authentication_sessions`
   (`SELECT`, `INSERT`, `UPDATE`) and `corporate_authentication_events`
   (`INSERT`).  The real runtime identity currently lacks them and has no
   grant option.  A synthetic test transaction was rolled back immediately
   after the event insert was denied; no synthetic identity or session remains.

There is not yet a real Administrator login, real non-admin denial, directory
security-negative test, provider outage proof, real actor mutation,
corporate-session expiration/revocation proof, or real-provider browser
acceptance to report.  This record is not a PASS.

## Production safety

No production deployment, production database migration, production write
enablement, NGINX change, Active Directory membership change, MySQL exposure,
or secret commit occurred.  No real corporate credential was requested or
handled.

ADMIN PHASE 5: IN PROGRESS
