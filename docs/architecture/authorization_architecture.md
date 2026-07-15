# Settings authorization architecture

Authentication answers who requested Settings access. Authorization independently checks whether the normalized identity has `settings.edit`.

```text
Settings mutation intent
  -> bearer session validated
  -> active user resolved
  -> provider availability and provider continuity checked
  -> active Settings roles/permissions re-resolved from MySQL
  -> settings.edit checked
  -> 200 allow, 401 unauthenticated, or 403 unauthorized
  -> protected API Settings write or API-authorized local client-preference write
  -> secured audit acknowledgement
```

Ordinary EOAT Atlas endpoints use the application-instance actor and remain available without a user session. The application actor can never authorize a `settings.*` permission. Client-side disabled controls are a usability lock, not the security boundary.

The API does not trust a client-provided Settings role. Development identity selection is resolved server-side and is forbidden in production. External company group mappings are server-side and require stable IT-approved identifiers.

`GET /api/v1/settings` exposes only active, non-sensitive shared Settings and requires no user session. `PUT /api/v1/settings/{key}` requires a live `settings.edit` grant. Sensitive rows are excluded from anonymous reads and cannot be changed through the general endpoint.
