# IT authentication requirements checklist

Production provider selection is blocked until Nolato IT completes this checklist. Do not place secrets, private keys, passwords, or sensitive production metadata in this file.

## Common requirements

- [ ] Approved method: SAML 2.0 or LDAP/Active Directory
- [ ] Identity-system owner and incident-response contact
- [ ] Staging/test and production availability
- [ ] Test users and stable test security-group identifiers
- [ ] Access assignment model: users, groups, nested groups, app roles, or combination
- [ ] MFA and conditional-access behavior
- [ ] Session duration, recent-authentication and renewal requirements
- [ ] Account lockout, deactivation and emergency-access policy
- [ ] Audit-log content and retention
- [ ] TLS/certificate, internal DNS and firewall requirements
- [ ] Production secret-storage and certificate-rotation mechanism
- [ ] Confirmation that authentication is Settings-only and normal EOAT Atlas use remains unsigned-in

## SAML 2.0 option

- [ ] IdP name, owner, metadata URL/XML, entity ID, SSO URL and optional logout URL
- [ ] Signing-certificate source and rollover procedure
- [ ] Required SP entity ID, ACS URL and logout return URL for staging and production
- [ ] NameID format; username, display-name, email and stable group/role claims
- [ ] Assertion/response signature and encrypted-assertion requirements
- [ ] Issuer, audience, recipient, destination and InResponseTo requirements
- [ ] Allowed clock skew, assertion/session lifetime and replay requirements
- [ ] MFA and conditional-access behavior
- [ ] Staging and production enterprise-application registrations
- [ ] Approved maintained SAML library or IT authentication gateway

## LDAP / Active Directory option

- [ ] Primary/secondary hostnames, approved port and mandatory LDAPS/secure transport
- [ ] Trusted certificate chain and certificate-rotation process
- [ ] Base DN, user/group search bases and filters
- [ ] Approved login pattern: user bind, service search plus user bind, integrated Windows, or IT gateway
- [ ] Bind-account requirement and approved secret location
- [ ] Nested-group behavior and stable group identifiers/DNs/SIDs/object IDs
- [ ] Username and UPN formats
- [ ] Connection timeout, pooling and failover policy
- [ ] Disabled, locked and password-expired attributes/behavior
- [ ] Staging directory or test OU and test accounts

Production remains NO-GO until the completed response has an IT approval reference.
