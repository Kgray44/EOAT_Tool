# Authentication provider architecture

```text
EOAT Atlas desktop (no startup login)
  -> Settings Admin button
  -> AuthenticationGateway (memory-only session)
  -> EOAT Atlas API authentication routes
  -> AuthenticationService
  -> one configured provider: development, SAML, or LDAP
```

Provider-specific attributes are normalized into external subject, username, display name, email, provider, groups, authentication time/method and session identifier. UI and business code do not depend on SAML claim names or LDAP DNs.

For SAML, the future approved flow uses the system browser and API/service-provider or IT gateway; the desktop never parses assertions. For LDAP, only the API may use IT-approved LDAPS or an approved authentication gateway; the desktop never binds or stores credentials.

Provider selection and configuration are environment-specific. `development` is valid only in development/staging-local and fails startup in production. SAML and LDAP adapters currently fail closed until IT supplies and approves configuration.
