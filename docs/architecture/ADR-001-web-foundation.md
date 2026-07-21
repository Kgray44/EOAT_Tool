# ADR-001: EOAT Atlas web foundation

## Decision

EOAT Atlas will use a static React/TypeScript/Vite frontend with React Router and TanStack Query. The existing FastAPI service and MySQL database remain authoritative. The web client consumes generated TypeScript types from the FastAPI OpenAPI document and has no direct database access or duplicate business logic.

Production will serve static files through NGINX and reverse-proxy same-origin `/api` calls to FastAPI bound to localhost. Browser JavaScript never holds the desktop device token or a shared service credential. NGINX will own any future internal credential injection for anonymous read-only traffic.

The initial web rollout is read-only. Browser writes require production-ready SAML or LDAP and a separately designed session/CSRF boundary.

## Consequences

The desktop client and responsive web client can coexist over one FastAPI/MySQL source of truth. Phase 0 creates routes and an API-status foundation only; QR deep links, profile pages, editing, uploads, and production hosting remain deferred. Phase 1 should implement the EOAT QR-profile vertical slice at `/eoats/:identifier` using the generated contract rather than a web-specific model.
