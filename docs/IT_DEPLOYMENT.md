# IT deployment

IT must provide and approve production infrastructure, MySQL hosting/backups, TLS certificates, DNS/network rules,
device or service identity for read endpoints, SAML/LDAP choice and group mapping for administration, secret storage,
monitoring, installer distribution, code-signing credentials, rollback, and support ownership.

Set operational roots through approved configuration such as `EOAT_ATLAS_NETWORK_ROOT` and
`EOAT_ATLAS_DEPLOYMENT_ROOT`; do not bake internal paths into source. Production API docs should remain disabled unless
explicitly restricted and approved. Complete security review, installer pilot, business UAT, and go-live approval before
production use.
