# EOAT Atlas Admin Phase 5: Provider Authority Record

Status: **Phase E provider approved on 2026-08-13.  `kerberos_form` is the
new corporate-authentication standard.**

## Authority hierarchy result

| Evidence class | Finding | Authority disposition |
| --- | --- | --- |
| Governing specification | Phase E requires an IT-approved corporate identity provider and an explicit Administrator group or equivalent server-side mapping. | Authoritative, as amended by the later IT approval below. |
| Accepted Phase 1-4 records | Phase 3/4 use an explicitly labelled local rehearsal session and defer corporate provider/group integration to Phase 5. | Authoritative for the rehearsal boundary; not provider approval. |
| Current Phase 5 baseline repository | Contains only the rehearsal secret, local identities, and local session configuration; it contains no LDAPS/SAML endpoint, metadata, trust chain, or Administrator group mapping. | Directly verified.  No enterprise provider selected. |
| Current server service configuration | The installed service declares `kerberos_form` with application scope and Kerberos configuration.  The inspection intentionally did not read secret values. | Directly verified current implementation and configuration standard. |
| Historical provider-neutral worktree | A separate later worktree contains LDAPS/SAML adapters marked unselected and a Kerberos-form implementation. | Historical/supporting context only; not merged into this accepted Phase 4 baseline and not provider approval. |
| Existing Administrator mapping | `kerberos_form` maps `CN=GWP-VT - EOAT Atlas Administrators,OU=GW,DC=gwplastics,DC=com` to `ADMINISTRATOR` as one active persisted mapping. | Previously verified server-side evidence; the identifier is configuration authority only and is never returned to a browser client. |
| Explicit IT approval | IT approved LDAP and identified the current `kerberos_form` server configuration as Phase E approval and the new standard. | Authoritative 2026-08-13 user-supplied IT decision.  It replaces the prior pending-provider conclusion. |

## Directly verified safe configuration facts

* The active service has an `/etc/eoat-atlas/runtime.env` environment file and
  reports `EOAT_AUTH_PROVIDER=kerberos_form`.
* Kerberos configuration is present on the server.
* The inspected runtime file exposes names for Kerberos-related settings; no
  secret value, password, bind credential, token, private key, or certificate
  material was read or recorded.
* The Phase 5 baseline exposes only `EOAT_API_ADMIN_REHEARSAL_SECRET` and
  `EOAT_API_ADMIN_COOKIE_SECURE` for the local rehearsal path.
* The approved LDAP path is Kerberos-authenticated LDAP over SASL/GSSAPI with
  a configured security floor.  It is not an anonymous, simple-bind, or
  plaintext LDAP design.

## Approved-provider constraints

* Use the current `kerberos_form` server configuration with application scope.
* Authenticate credentials through a unique temporary private Kerberos cache;
  never retain passwords or place them in command arguments, environment,
  logs, audit data, or browser storage.
* Query LDAP using the Kerberos-authenticated SASL/GSSAPI channel and enforce
  the configured security floor.
* Resolve the existing persisted Administrator mapping server-side.  Its
  authority identifier is `CN=GWP-VT - EOAT Atlas Administrators,OU=GW,DC=gwplastics,DC=com`;
  do not copy it to browser claims or public diagnostics, and do not replace it
  with a guessed group.
* Migration `20260813_0009` establishes that approved mapping idempotently for
  a new Phase 5 schema; it never changes AD group membership.
* Retain the local rehearsal path only for development/staging-local tests.

## Consequence

Provider-specific implementation and non-production acceptance may proceed
against the approved standard.  A PASS remains gated on verified mapping,
real Administrator/non-admin flows, expiry/revocation and outage evidence,
and all other Phase 5 acceptance criteria.  No production activation is
authorized by this record.
