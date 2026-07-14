# Development Authorization Model

Writes require `X-EOAT-Identity`; anonymous or unknown identities are rejected. The explicit development provider defaults to `dev.viewer`, `dev.technician`, `dev.engineer`, and `dev.admin`, and can be replaced with the `EOAT_API_DEV_IDENTITIES` JSON map. It is rejected outside the development API environment.

| Role | Effective permissions |
|---|---|
| VIEWER | Read only |
| TECHNICIAN | Install/location, audits, maintenance, annotations, approved tag assignment, Fit Check history, instance registration |
| ENGINEER | Technician actions plus asset, compatibility, document/photo, and tag management |
| ADMINISTRATOR | All actions including controlled archive/restore |

The server enforces permissions. UI visibility is only a usability aid. Inactive/archived users and unknown identities cannot write. Security denials are structured-log events with request IDs and identity labels, without tokens or credentials. Production authentication remains an IT deployment decision.
