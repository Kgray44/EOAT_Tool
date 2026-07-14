# Development Authorization Model

Ordinary EOAT Atlas work does not require user authentication. Requests without `X-EOAT-Identity` use a technical application actor for attribution and retain normal workflow access; that actor can never authorize `settings.*`. Explicit development identities remain available for regression attribution, and unknown explicitly supplied identities are rejected.

The following legacy development attribution roles remain available only when a test explicitly sends an identity header; they do not describe the unsigned-in product experience:

| Explicit test role | Effective regression permissions |
|---|---|
| VIEWER | Read only |
| TECHNICIAN | Install/location, audits, maintenance, annotations, approved tag assignment, Fit Check history, instance registration |
| ENGINEER | Technician actions plus asset, compatibility, document/photo, and tag management |
| ADMINISTRATOR | All actions including controlled archive/restore |

Phase 10 company authentication is separate and Settings-only. The server validates a short-lived Settings session and `settings.edit`; the UI lock is only a usability aid. Security denials are audited with request IDs without tokens or credentials. Production provider selection remains an IT decision.
