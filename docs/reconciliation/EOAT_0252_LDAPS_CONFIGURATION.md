# EOAT Atlas 0.25.3 LDAPS configuration contract

The checked-in [environment template](../../.env.example) contains only
non-secret values. Production activation requires `EOAT_AUTH_PROVIDER=ldap`
and all of the following protected configuration, but this change does not
activate it.

| Key | Required production value / rule |
| --- | --- |
| `EOAT_LDAP_ENABLED` | `true` only after activation approval |
| `EOAT_LDAP_HOSTS` | `gwplastics.com` (canonical round-robin name) |
| `EOAT_LDAP_PORT` | `636` |
| `EOAT_LDAP_USE_LDAPS` | `true`; plaintext LDAP is rejected |
| timeouts | both 1–30 seconds; template uses 5 |
| `EOAT_LDAP_TRUST_STORE_PATH` | blank uses OS trust; otherwise an IT-approved CA bundle only |
| `EOAT_LDAP_UPN_SUFFIX` | `gwplastics.com` |
| `EOAT_LDAP_AUTHENTICATION_MODE` | `upn` default; `user_dn` requires a discovered/approved narrow search base |
| `EOAT_LDAP_SETTINGS_ADMIN_GROUP` | IT-approved DN or stable directory identity; required for administration |
| nested groups | false unless IT approves bounded group-base traversal |

No LDAP password is a configuration value. If a future approved service
account is unavoidable, its secret reference may be recorded in
`EOAT_LDAP_SERVICE_ACCOUNT_SECRET_REFERENCE`; secret material belongs only in
the protected server-side secret service and is not implemented as a source or
environment password field.
