# Enterprise Settings authentication test plan

## Automated scope

1. Provider interface and normalized development identity.
2. Invalid provider/scope and production-development safety assertion.
3. SAML and LDAP fail-closed configuration health before IT approval.
4. Unsigned-in startup and ordinary endpoint access.
5. Settings visibility and disabled-control state without authentication.
6. 401 without a Settings session, 403 without permission, and success with `settings.edit`.
7. Logout, revocation, expiry, disabled user and provider outage.
8. Memory-only client token handling and no token/credential diagnostics.
9. Settings auto-lock and server recheck before save.
10. Alembic 0005 upgrade/downgrade, metadata and MySQL table/index/constraint checks.

SAML issuer/audience/signature/replay tests or LDAP bind/certificate/account-state tests remain blocked until IT selects a provider and supplies staging configuration. They must be added before production approval.
