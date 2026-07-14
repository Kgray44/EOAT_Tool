# Authentication secret management

No company password, SAML assertion, token, private key or LDAP bind secret is stored by the desktop or committed to Git.

Non-secret provider settings use environment-specific configuration templates. Production secrets must use the mechanism approved by Nolato IT, such as an IT-managed service identity, certificate store, secret vault or protected service environment. The repository contains placeholders only.

Rotation requirements:

- SAML signing metadata/certificates must support overlap and documented rollover.
- LDAP trust chains and optional bind credentials must have named owners, expiry monitoring and rotation procedures.
- Session-signing or encryption material, if the selected implementation requires it, must be externally supplied and rotatable.
- Diagnostic and audit output must mask sensitive values.
- Development authentication must never be enabled in production.

The existing local PBKDF2 administrator file is retained only as migration evidence and dormant recovery code; the active Settings path does not initialize or consult it.
