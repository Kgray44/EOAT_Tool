# Phase 10 work waiting on Nolato IT

Status: **OPEN — production provider unselected**  
Updated: 2026-07-15

This is the exact external dependency list for completing Phase 10. None of these items may be guessed. Ordinary EOAT Atlas startup and use remain unsigned-in; the selected provider is used only after a user clicks **Admin** to unlock Settings editing.

## Decisions and information required for either provider

1. **Written provider selection.** Select SAML 2.0 or LDAP/Active Directory and provide the approving ticket/change/reference. A verbal preference is not sufficient.
2. **Identity-system ownership.** Name the technical owner, security approver, operations contact, and incident/escalation contact for staging and production.
3. **Settings-only scope approval.** Confirm in writing that no authentication is required for application startup or ordinary Home, Search, Library, profile, History, Fit Check, report, PDF, Refresh, Deep Refresh, or EOAT workflow access.
4. **Administrator assignment source.** Supply the immutable identifier for the group/app-role that grants `settings.edit`, plus any explicit-deny group and the expected nested-group behavior.
5. **Role mapping approval.** Approve Viewer, Technician, Engineer, and Administrator mappings and confirm that only Administrator receives `settings.edit`, `settings.set_default`, `settings.import`, `settings.restore`, and `settings.authentication.configure`.
6. **Identity normalization.** Define the stable subject, username, display-name, email, and group identifier sources; state whether usernames can be renamed and which identifier remains immutable.
7. **Test identities.** Provide staging identities for at least one authorized Administrator, one authenticated Viewer/non-administrator, one disabled account, and one account removed from the administrator group.
8. **Environment endpoints.** Provide separate staging and production endpoints/registrations, internal DNS names, required proxy settings, firewall rules, and source/destination allow-list requirements.
9. **Transport trust.** Provide the trusted CA chain, hostname-validation requirements, TLS minimums/cipher policy, certificate owner, expiry monitoring, and rollover procedure.
10. **MFA and conditional access.** State whether MFA is required for Settings administration, which conditional-access rules apply, and the expected user experience when MFA or policy denies access.
11. **Session policy.** Approve authentication lifetime, Settings unlock maximum, reauthentication rules, idle behavior, logout/single-logout expectations, and whether the current configurable Immediate–5 minute client relock may end sooner than the identity session.
12. **Account-state behavior.** Define disabled, locked, expired, terminated, and group-removed behavior and the maximum acceptable revocation propagation delay.
13. **Availability policy.** Define timeouts, retries, failover order, maintenance behavior, and outage messaging. Confirm that outages lock Settings only and never block normal application use.
14. **Secret and key handling.** Select the server-side secret/certificate store, name owners, define access controls and rotation, and confirm that no company password, private key, bind password, or reusable assertion is stored in the desktop client or repository.
15. **Audit requirements.** Approve events, identity fields, request correlation, retention, access controls, SIEM forwarding, alerting, and privacy requirements. Sensitive credentials/assertions will not be logged.
16. **Emergency access.** Decide whether an IT-controlled break-glass path is required. The dormant local shared-password code is not an approved production fallback and will not be activated.
17. **Staging window and participants.** Provide the environment-ready date, test window, IT observer, business testers, and rollback/contact plan.
18. **Security approval criteria.** Supply the required security checklist, penetration/vulnerability expectations, evidence format, and named approver.

## Additional information required if IT selects SAML

1. IdP product/tenant and authoritative metadata URL or signed metadata XML.
2. IdP entity ID, SSO URL, optional SLO URL, supported bindings, and redirect/post binding choice.
3. Separate staging and production SP entity IDs, assertion-consumer-service URLs, and permitted logout return URLs.
4. NameID format and exact claim names/formats for immutable subject, username, display name, email, and groups/app roles.
5. Signing rules for response and assertion; accepted algorithms; whether assertions must be encrypted; certificate/key ownership.
6. Issuer, audience, recipient, destination, and `InResponseTo` validation requirements.
7. Maximum assertion age, NotBefore/NotOnOrAfter handling, allowed clock skew, request correlation, and replay-cache lifetime.
8. Signing-certificate fingerprints/chain, current and next certificates, overlap window, metadata refresh, and emergency rollover procedure.
9. Browser/redirect policy, custom URI or loopback callback approval if required, and restrictions imposed by endpoint security tools.
10. Staging/production enterprise-application registrations and assignment policy.
11. Approved maintained SAML library or IT authentication gateway and its support owner.
12. IdP-initiated login decision. The intended EOAT Atlas flow is Admin-button initiated; unsolicited assertions must remain disabled unless explicitly approved and threat-reviewed.

## Additional information required if IT selects LDAP/Active Directory

1. Primary and secondary LDAPS hostnames, ports, site affinity, DNS behavior, and failover order.
2. Root/intermediate CA chain, hostname/SAN expectations, certificate rollover, and whether certificate pinning is prohibited or required.
3. Base DN, user search base, group search base, search scope, user filter, and group-membership filter/attribute.
4. Stable identity attribute and exact mappings for username, display name, email, group DN/SID/object ID.
5. Approved authentication pattern: direct user bind, service search plus user bind, integrated Windows authentication, or IT gateway.
6. If a service account is required, provide only an approved secret-store reference and rotation/ownership policy—never the password in client configuration or Git.
7. UPN/domain input formats and canonicalization rules; ambiguity behavior for duplicate usernames.
8. Nested group, cross-domain, trusted-forest, universal-group, and referral behavior.
9. Disabled, locked, expired-password, must-change-password, and account-expired attributes and expected denial messages.
10. Connection/open/read timeouts, pool limits, retry policy, health-check method, and outage/failover behavior.
11. Firewall rules from the API host only. The desktop must never connect directly to LDAP.
12. A staging directory/test OU with representative authorized, unauthorized, disabled, locked, and group-removed accounts.

## Work that remains blocked until IT supplies the selected-provider information

1. Implement the real selected-provider adapter using the approved library/gateway and configuration. The existing SAML and LDAP adapters intentionally fail closed and cannot produce a successful production identity.
2. Configure staging without committing secrets and validate provider diagnostics, certificate trust, identity normalization, and administrator group mapping.
3. Run selected-provider security tests: SAML signature/audience/correlation/replay/expiry/rollover tests or LDAP certificate/bind/search/failover/account-state tests.
4. Run outage, revocation, permission-removal, timeout, logout, audit, and multi-client tests against the real provider.
5. Obtain IT security review approval and record its reference.
6. Execute human business UAT with real authorized and unauthorized users and obtain signed approval.
7. Remove the dormant shared administrator-password implementation only after selected-provider staging validation and approvals pass. Until then it remains isolated and unreachable from the `mysql_api` Admin workflow.
8. Reissue the Phase 10 scorecard. Phase 10 remains **NO-GO** until all selected-provider validation, IT approval, and human UAT are complete.
