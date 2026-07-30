# EOAT Atlas 0.25.3 LDAPS architecture

The LDAPS implementation protects Settings administration only. Normal EOAT
Atlas viewing and operational workflows remain outside this sign-in boundary,
and the production write gate remains independent.

| Existing component | Previous behavior | 0.25.2 change | Security effect | Test coverage |
| --- | --- | --- | --- | --- |
| Provider selection | LDAP placeholder failed closed | `LDAPAuthenticationProvider` uses verified LDAPS when enabled | no development fallback | provider/configuration tests |
| LDAP transport | none | `ldap3` with `CERT_REQUIRED`, hostname-bearing canonical host, bounded endpoint iteration | no accepted-all certificates | configuration and preflight tests |
| Identity | development only | UPN direct bind first; optional anonymous DN discovery then user bind | password stays request-memory only | escaping/normalization tests |
| Authorization | database group-role mappings | approved settings-admin group adds only `ADMINISTRATOR`; missing mapping grants nothing | authentication is not authorization | fail-closed health test |
| Session | hashed server-side token | browser token moves to HttpOnly strict-SameSite cookie plus CSRF cookie/header | no browser token storage | web/session integration tests |
| Settings actions | permission checks and typed confirmations | cookie mutations additionally require CSRF validation | protects authenticated mutations |

## Flow

1. The browser posts a username and password only to `/api/v1/auth/ldap/login`
   over its existing HTTPS API origin. The password is passed directly to the
   LDAPS bind and is neither stored, returned, nor audited.
2. The provider connects to `gwplastics.com:636` with certificate-chain and
   hostname validation. The DNS name is preserved so round-robin controllers
   each present a certificate valid for the service name.
3. Direct UPN bind (`username@gwplastics.com`) is the default. The optional
   `user_dn` mode performs a minimal anonymous, escaped UPN search and then a
   direct bind; it does not require a service-account secret.
4. Only canonical identity fields and required group identifiers are retained.
   A configured settings-admin group must match an observed membership before
   `ADMINISTRATOR` is granted. Database role mappings can grant narrower roles.
5. The existing hashed, server-side session has a bounded expiry and is revoked
   on logout, provider loss, permission loss, and expiry. Browser mutations
   require the CSRF double-submit header and still pass permission checks.

Nested groups are opt-in. For AD, the implementation uses the matching-rule-in-
chain control only against the configured narrow group base.
