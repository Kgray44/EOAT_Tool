# External group to Settings role mapping

Mappings are stored server-side in `external_group_role_mappings` and use provider plus stable external group identifier. Display names must not be used when IT can provide an immutable ID, SID, object identifier, claim value or DN.

Placeholder configuration:

```yaml
role_mappings:
  - provider: <saml-or-ldap>
    external_group_identifier: <IT-approved-stable-administrator-group>
    role: ADMINISTRATOR
```

Multiple groups and roles are supported. Effective permissions are the union of active roles unless IT approves explicit deny. Roles are synchronized on successful Settings authentication; removed memberships are not permanently trusted. Development identities map to synthetic development-only group identifiers.
