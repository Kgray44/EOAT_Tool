# EOAT Atlas Admin Phase 5: Corporate Authentication Design

Status: active Phase 5 design; the `kerberos_form` LDAP standard is approved
for non-production integration and acceptance.

## Baseline and isolation

| Item | Value |
| --- | --- |
| Accepted source baseline | `341270e2bb7a500ead7d61466279b61e590b4246` |
| Baseline verdict | `ADMIN PHASE 4: PASS` |
| Phase 5 branch | `feature/admin-phase5-corporate-auth` |
| Phase 5 worktree | `C:\\Users\\kgray\\eoat-admin-phase5-corporate-auth` |
| Data boundary | `eoat_atlas_test` only for any later runtime acceptance |

The archived UNC source and the accepted Phase 4 worktree remain untouched.
No Phase 6 deployment, production database migration, production browser write
enablement, NGINX change, AD membership change, or production MySQL operation
is in scope.

## Governing architecture

Phase 5 replaces the Phase 3/4 local rehearsal identity seam for production
use without weakening the existing authorization, CSRF, transaction, or audit
boundaries.  The intended protected path is:

`approved provider -> validated stable identity -> approved group mapping ->
application role/capabilities -> opaque server session -> protected workflow ->
immutable actor-aware audit evidence`.

Authentication and Administrator authorization are independent.  A corporate
identity with no approved elevated mapping is never an Administrator.

## Provider-neutral implementation boundary

The approved provider is the existing `kerberos_form` flow: browser form to a
temporary private Kerberos cache, followed by LDAP over SASL/GSSAPI with the
configured security floor.  Implementation must:

* preserve a provider-neutral identity, group-mapping, role-resolution, and
  session contract;
* server-controlled opaque session storage with token digests, expiry,
  revocation, and fixation rotation;
* explicit production rejection of the local rehearsal issuer and all
  browser-supplied actor/role claims;
* safe provider readiness and mapping status contracts; and
* synthetic, non-corporate tests for the above boundary; and
* use the existing persisted Administrator group mapping without exposing or
  guessing its identifier.

There is no fallback
from an unavailable enterprise provider to rehearsal, a generic user, or a
browser header.

## Session and actor model

The production-intended session is an opaque, cryptographically random browser
cookie whose digest is stored server-side with the mapped user, provider,
auth-time, issuance time, expiry, revocation state, and authorization version.
The raw session or CSRF secret is never written to audit evidence, logs, API
responses, localStorage, or sessionStorage.  Session fixation is prevented by
issuing a fresh session after successful authentication or step-up.

The existing rehearsal mechanism remains test-only and must stay visibly and
technically isolated to `development` and `staging_local`.  It is not a
corporate provider, cannot be enabled by a route parameter or browser state,
and cannot satisfy production authentication or fresh-auth requirements.

## Step-up reconciliation

Phase 4's rehearsal proof remains usable only for its bounded test-only Danger
rehearsal.  A corporate fresh-auth proof will be selected only after the
approved provider defines a safe reauthentication mechanism.  A normal
corporate login alone will not authorize a Danger Zone operation.

## Current decision

IT approved LDAP on 2026-08-13 and designated the current `kerberos_form`
server configuration as Phase E approval and the new standard.  This allows
provider-specific non-production implementation; it does not claim production
readiness or a Phase 5 pass.
