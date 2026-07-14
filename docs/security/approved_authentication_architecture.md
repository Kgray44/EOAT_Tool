# Approved authentication architecture

Approval status: **NOT APPROVED - IT provider selection required**

- Selected provider: UNSELECTED (`saml` and `ldap` adapters are available behind one boundary)
- Identity authority: pending IT
- User/claim mapping: pending IT
- Stable administrator group: pending IT
- Session model: short-lived, revocable API session used only for Settings editing
- Logout: API revocation plus memory-token clearing; IdP logout pending IT policy
- Failure behavior: application remains fully usable; Settings remain locked
- Staging/production configuration: placeholders only
- IT approval reference: not supplied

The desktop never validates SAML XML, connects to LDAP, or stores company passwords. Only the API/provider boundary may communicate with the selected company identity service. Exactly one provider is active per environment. Development authentication is rejected in production.
