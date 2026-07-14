# Settings administration session security

Company authentication produces a short-lived EOAT Atlas Settings session. It is not an application login.

- The API generates a cryptographically random token and stores only its SHA-256 hash.
- The desktop retains the token in memory inside `AuthenticationGateway`; it is not written to JSON, INI, SQLite, logs, environment files or command arguments.
- The MySQL session records user, provider, roles, permissions, authentication time, expiry, application instance and revocation.
- Default development lifetime is five minutes and is configurable within a bounded limit. IT must approve production lifetime and renewal.
- Logout revokes server state and clears desktop memory.
- Expired, revoked or disabled-user sessions fail closed.
- Leaving Settings applies the existing immediate-through-five-minute usability lock and clears local session material.
- Every Settings save calls the API to recheck `settings.edit` before writing locally.
- Ordinary application workflows have no user session and continue after Settings relocks.

SAML request correlation/replay validation and LDAP secure-bind details remain provider-specific and blocked pending IT selection. No custom cryptography is used.
