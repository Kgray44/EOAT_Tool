# EOAT Atlas Phase 10 IT security review package

Status: submitted package foundation; formal IT review not yet performed.

## Scope and data flow

Authentication is invoked only by the Settings Admin button. EOAT Atlas startup and ordinary workflows require no user identity. The desktop calls API authentication routes; only the API/provider adapter may contact the selected company identity system. A normalized identity maps stable company groups to Settings roles and permissions. The API issues a short-lived, revocable Settings session whose raw token remains desktop-memory-only.

## Controls implemented and validated

- Provider abstraction with development, SAML and LDAP adapters
- Production rejection of development authentication
- No desktop LDAP/SAML parsing or company-password storage
- Settings-only `settings.edit` enforcement with distinct 401/403
- Hashed session tokens, bounded expiry, logout/revocation and disabled-user checks
- JIT user record and role synchronization without passwords/assertions
- Authentication audit table and Settings-specific event vocabulary
- Application availability during authentication outage
- Alembic 0005 upgrade/downgrade and MySQL constraints
- No global login screen or normal-work identity requirement

## Required IT decisions

Select SAML or LDAP; provide staging/production configuration, stable administrator group, claim/search mapping, MFA, session/refresh, TLS/certificates, secret storage, audit retention, outage/revocation and emergency access policies. Approve the permission matrix and Settings-only scope.

## Known risks and open items

- No real company provider is selected or integrated.
- SAML signature/replay behavior or LDAP certificate/bind behavior cannot be validated before selection.
- Human UAT has not run.
- Production deployment remains unchanged and NO-GO.

Use `IT_AUTHENTICATION_REQUIREMENTS_CHECKLIST.md`, `IT_AUTHENTICATION_CONFIGURATION_RESPONSE.md`, the architecture documents, test results and Phase 10 scorecard as review evidence. Do not add secrets to the package.
