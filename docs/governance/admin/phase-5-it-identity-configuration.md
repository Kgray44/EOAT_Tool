# EOAT Atlas Phase 5 IT Identity Configuration Checklist

This is an input checklist, not a credential store.  Do not enter passwords,
private keys, session cookies, or token values in this file.

## Approved decision

* Approved provider: `kerberos_form` using the existing Kerberos-authenticated
  LDAP/SASL-GSSAPI server configuration.
* Authority source: IT approval communicated on 2026-08-13.
* Existing approved Administrator directory mapping:
  `CN=GWP-VT - EOAT Atlas Administrators,OU=GW,DC=gwplastics,DC=com` maps to
  `ADMINISTRATOR` in the persisted server-side mapping store.  Membership data
  never belongs in this document or a browser response.
* Explicit Viewer, Technician, and Engineer mapping rules, if any.
* Stable immutable subject attribute/claim and the supported login format.
* Approved real Administrator and real non-admin acceptance identities.

## Kerberos-form LDAP inputs

* Kerberos realm, directory base DN, private credential-cache directory,
  login timeout, and minimum SASL security factor are application-protected
  runtime settings; record names only, never their sensitive values.
* Username normalization, identity/group lookup, disabled-account treatment,
  nested-group policy, and stable-subject derivation must remain server-side.
* The LDAP connection must use SASL/GSSAPI with its required protection, not a
  simple or anonymous bind.

## Deployment prerequisites

* Approved test/staging callback or LDAPS network path.
* Application-scoped trust/metadata placement and protected secret names.
* Session absolute, idle, and fresh-auth policies.
* IT-approved manual real-credential acceptance procedure.

No production configuration is activated by this document.  Phase 6 owns
production deployment and NGINX/runtime activation.
