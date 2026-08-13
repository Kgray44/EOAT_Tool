# EOAT Atlas Phase 5 IT Identity Configuration Checklist

This is an input checklist, not a credential store.  Do not enter passwords,
private keys, session cookies, or token values in this file.

## Required decision

* Approved production provider: `LDAPS` or `SAML` (one only unless a governed
  addendum explicitly approves a different design).
* Authority source, approver, and approval date.
* Exact approved Administrator directory group or SAML claim value.
* Explicit Viewer, Technician, and Engineer mapping rules, if any.
* Stable immutable subject attribute/claim and the supported login format.
* Approved real Administrator and real non-admin acceptance identities.

## LDAPS-only inputs

* Approved hostname(s), port, certificate chain/trust source, and hostname
  validation policy.
* User/group search bases, safe filter template, bind strategy, secret
  reference name only, group attribute, and nested-group policy.

## SAML-only inputs

* Signed IdP metadata location or managed metadata artifact, IdP entity ID,
  service-provider entity ID, and approved ACS/callback URL.
* Signature, certificate rotation, audience, destination, assertion window,
  replay, and logout policy.
* Stable subject, username, display-name, email, and group claim names.

## Deployment prerequisites

* Approved test/staging callback or LDAPS network path.
* Application-scoped trust/metadata placement and protected secret names.
* Session absolute, idle, and fresh-auth policies.
* IT-approved manual real-credential acceptance procedure.

No production configuration is activated by this document.  Phase 6 owns
production deployment and NGINX/runtime activation.
