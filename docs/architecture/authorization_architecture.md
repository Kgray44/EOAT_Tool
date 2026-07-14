# Settings authorization architecture

Authentication answers who requested Settings access. Authorization independently checks whether the normalized identity has `settings.edit`.

```text
Settings mutation intent
  -> bearer session validated
  -> active user resolved
  -> synchronized Settings roles/permissions resolved
  -> settings.edit checked
  -> 200 allow, 401 unauthenticated, or 403 unauthorized
  -> local Settings write
  -> secured audit acknowledgement
```

Ordinary EOAT Atlas endpoints use the application-instance actor and remain available without a user session. The application actor can never authorize a `settings.*` permission. Client-side disabled controls are a usability lock, not the security boundary.

The API does not trust a client-provided Settings role. Development identity selection is resolved server-side and is forbidden in production. External company group mappings are server-side and require stable IT-approved identifiers.
