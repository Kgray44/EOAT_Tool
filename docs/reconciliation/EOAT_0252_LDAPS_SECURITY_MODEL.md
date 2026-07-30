# EOAT Atlas 0.25.3 LDAPS security model

- TLS is always LDAPS with `CERT_REQUIRED`; production configuration cannot
  disable it. The OS trust store is the default, and a new certificate is never
  trusted automatically.
- User-controlled LDAP filter data is escaped with `ldap3` RFC 4515 escaping;
  distinguished names are returned by the directory rather than constructed
  from user input.
- Login failures are externally generic. Audits retain only outcome classes,
  provider, request context, and the minimal provisioned identity—never a
  password, token, raw entry, or LDAP response dump.
- A successful bind grants no Settings access. A missing or non-matching
  administrator group produces no administrator role, so protected operations
  remain denied.
- Browser session credentials are HttpOnly, strict-SameSite cookies (Secure in
  production) backed by hashed server-side session records. A non-HttpOnly
  CSRF cookie must match `X-EOAT-CSRF` for cookie-authenticated mutations.
- Logout revokes the server record and clears both cookies. Expiry, provider
  outage, disabled users, and permission loss relock Settings server-side.
