# Security boundary

MySQL/API is the operational trust boundary. Compatibility and installation decisions fail closed. Write endpoints
require server-resolved permissions, request IDs, application instance context, optimistic concurrency, and audit
history. Compatibility override is a distinct permission and reasoned event.

Settings authentication does not imply complete production federation. Operational read endpoints require an
IT-approved device credential, service identity, or enforced network boundary in production. TLS, SAML/LDAP, group
mapping, secret management, certificate lifecycle, and infrastructure controls remain external until configured and
verified.

Logs must not contain tokens, passwords, assertions, LDAP credentials, private keys, or sensitive setting values.
Repository safety rejects internal/personal paths, operational reports, credentials, private keys, and unapproved data.
