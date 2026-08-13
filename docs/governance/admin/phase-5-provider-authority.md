# EOAT Atlas Admin Phase 5: Provider Authority Record

Status: **provider decision unresolved; Phase 5 cannot pass until the missing
enterprise inputs are supplied and accepted.**

## Authority hierarchy result

| Evidence class | Finding | Authority disposition |
| --- | --- | --- |
| Governing specification | Phase E permits an IT-approved `LDAPS` or `SAML` provider and requires an explicit Administrator group or equivalent server-side mapping.  Appendix D expressly defers the exact group name. | Authoritative.  No provider or group value is supplied. |
| Accepted Phase 1-4 records | Phase 3/4 use an explicitly labelled local rehearsal session and defer corporate provider/group integration to Phase 5. | Authoritative for the rehearsal boundary; not provider approval. |
| Current Phase 5 baseline repository | Contains only the rehearsal secret, local identities, and local session configuration; it contains no LDAPS/SAML endpoint, metadata, trust chain, or Administrator group mapping. | Directly verified.  No enterprise provider selected. |
| Current server service configuration | The installed service declares `kerberos_form` with application scope and Kerberos configuration.  The inspection intentionally did not read secret values. | Directly verified current state, but not Phase E approval: the governing Phase E choice is LDAPS or SAML and expressly forbids inferring a new browser architecture from historical directory success. |
| Historical provider-neutral worktree | A separate later worktree contains LDAPS/SAML adapters marked unselected and a Kerberos-form implementation. | Historical/supporting context only; not merged into this accepted Phase 4 baseline and not provider approval. |
| Explicit IT approval | No current IT-approved LDAPS or SAML configuration, exact Administrator group, metadata, or acceptance identity was found in the available evidence. | Missing. |

## Directly verified safe configuration facts

* The active service has an `/etc/eoat-atlas/runtime.env` environment file and
  reports `EOAT_AUTH_PROVIDER=kerberos_form`.
* Kerberos configuration is present on the server.
* The inspected runtime file exposes names for Kerberos-related settings; no
  secret value, password, bind credential, token, private key, or certificate
  material was read or recorded.
* The Phase 5 baseline exposes only `EOAT_API_ADMIN_REHEARSAL_SECRET` and
  `EOAT_API_ADMIN_COOKIE_SECURE` for the local rehearsal path.

## Required IT inputs before provider-specific work or PASS

Choose exactly one approved production identity provider and supply safe
configuration through the approved secret/configuration channel:

* For LDAPS: approved host(s)/port, TLS trust chain and hostname policy,
  approved bind/search pattern, identity and stable-subject attributes, group
  strategy including nesting semantics, exact Administrator group, and approved
  acceptance identities.
* For SAML: signed IdP metadata, entity IDs, approved ACS URL, certificate
  rotation/signature policy, stable subject and group claims, exact
  Administrator claim/group, replay/time/RelayState policy, and approved
  acceptance identities.
* For either: approved Viewer/Technician/Engineer mapping rules, session and
  fresh-auth policy, a real approved Administrator, and a real non-admin test
  identity.  No password belongs in this record or in Codex chat.

## Consequence

Provider-neutral hardening may continue.  Selecting LDAPS or SAML, testing a
real directory/IdP, assigning roles from guessed group data, and asserting a
real administrator/non-admin result are blocked.  The only compliant final
verdict absent those inputs is `ADMIN PHASE 5: INCOMPLETE`.
