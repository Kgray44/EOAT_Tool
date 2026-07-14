# Authentication failure behavior

| Condition | Required result |
|---|---|
| Provider unavailable | EOAT Atlas and normal API work continue; Settings stay visible and locked |
| SAML metadata/certificate invalid | Settings authentication fails closed; no bypass |
| LDAP/LDAPS unavailable | New Settings authentication fails; no credential cache or password fallback |
| No Settings session | Protected Settings check returns 401 |
| Authenticated without `settings.edit` | Protected Settings check returns 403 |
| Session expired/revoked | Settings relock; unsaved data handled safely; normal app continues |
| Administrator group removed/user disabled | Future check denied and session rejected/revoked per approved refresh policy |
| API unavailable | Cached ordinary reads remain available; Settings editing locks; no Settings write queued |
| Development provider configured in production | API startup fails configuration safety check |

The user-facing outage message states that administrator authentication is unavailable while EOAT Atlas remains fully usable. Production never falls back to the local password or development provider.
